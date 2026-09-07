"""
Tests del reporte semanal (Tarea 12.2).

Base SQLite en memoria y Telegram mockeado. Lo importante acá: que el reporte
**no invente números propios** — los totales tienen que coincidir exactamente
con `calculations.compute_trade`, que es la única fuente de verdad — y que la
ventana semanal (lunes a domingo, por `fecha_venta`) deje afuera lo que no
corresponde.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, notifications, weekly_report
from app.calculations import BrokerRates, compute_trade
from app.database import Base


TASAS = BrokerRates(comision_broker=0.005, derechos_mercado=0.0008, iva=0.21)

# Semana del lunes 2026-08-31 al domingo 2026-09-06.
LUNES = date(2026, 8, 31)
VIERNES = date(2026, 9, 4)
DOMINGO = date(2026, 9, 6)
SEMANA_ANTERIOR = date(2026, 8, 28)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    sesion = Session()
    try:
        yield sesion
    finally:
        sesion.close()


def _trade(db, ticker, cantidad, entrada, salida=None, fecha_venta=None, compra=None):
    t = models.Trade(
        ticker=ticker,
        tipo="CEDEAR",
        fecha_compra=compra or date(2026, 8, 24),
        cantidad=cantidad,
        precio_entrada=entrada,
        precio_salida=salida,
        fecha_venta=fecha_venta,
        senal="Señal IA",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ---------- Ventana semanal ----------


def test_la_semana_va_de_lunes_a_domingo():
    assert weekly_report.semana_de(VIERNES) == (LUNES, DOMINGO)
    assert weekly_report.semana_de(LUNES) == (LUNES, DOMINGO)
    assert weekly_report.semana_de(DOMINGO) == (LUNES, DOMINGO)


def test_solo_entran_las_cerradas_dentro_de_la_semana(db):
    _trade(db, "NVDA", 10, 100.0, 110.0, VIERNES)
    _trade(db, "VIEJA", 10, 100.0, 110.0, SEMANA_ANTERIOR)
    _trade(db, "ABIERTA", 10, 100.0)  # sin precio de salida

    resumen = weekly_report.resumen_semanal(db, hasta=VIERNES)

    assert resumen["desde"] == LUNES and resumen["hasta"] == DOMINGO
    assert [op["ticker"] for op in resumen["semana"]["detalle"]] == ["NVDA"]
    assert resumen["previo"]["operaciones"] == 1
    assert resumen["posiciones_abiertas"] == 1
    assert resumen["tickers_abiertos"] == ["ABIERTA"]


def test_una_operacion_abierta_no_cuenta_como_resultado(db):
    _trade(db, "ABIERTA", 10, 100.0)

    resumen = weekly_report.resumen_semanal(db, hasta=VIERNES)

    assert resumen["semana"]["operaciones"] == 0
    assert resumen["semana"]["resultado_neto"] == 0.0


# ---------- Los totales no se recalculan a mano ----------


def test_el_resultado_neto_coincide_con_calculations(db):
    _trade(db, "NVDA", 10, 100.0, 110.0, VIERNES)
    _trade(db, "KO", 20, 50.0, 48.0, VIERNES)

    esperado = (
        compute_trade(10, 100.0, 110.0, TASAS).resultado_neto
        + compute_trade(20, 50.0, 48.0, TASAS).resultado_neto
    )

    resumen = weekly_report.resumen_semanal(db, hasta=VIERNES)

    assert resumen["semana"]["resultado_neto"] == round(esperado, 2)
    assert resumen["semana"]["ganadoras"] == 1
    assert resumen["semana"]["perdedoras"] == 1
    assert resumen["semana"]["tasa_acierto_pct"] == 0.5


def test_las_comisiones_suman_los_dos_tramos(db):
    _trade(db, "NVDA", 10, 100.0, 110.0, VIERNES)
    c = compute_trade(10, 100.0, 110.0, TASAS)

    resumen = weekly_report.resumen_semanal(db, hasta=VIERNES)

    assert resumen["semana"]["comisiones"] == round(c.comision_compra + c.comision_venta, 2)


# ---------- Mensaje ----------


def test_el_mensaje_compara_contra_el_historico_previo(db):
    _trade(db, "VIEJA", 10, 100.0, 102.0, SEMANA_ANTERIOR)
    _trade(db, "NVDA", 10, 100.0, 115.0, VIERNES)

    resumen = weekly_report.resumen_semanal(db, hasta=VIERNES)
    msg = weekly_report.mensaje_reporte_semanal(resumen)

    assert "REPORTE SEMANAL" in msg
    assert "NVDA" in msg
    assert "VIEJA" not in msg, "el detalle es solo de la semana"
    assert "Acumulado previo" in msg
    assert "mejor que" in msg


def test_sin_historico_el_mensaje_lo_dice(db):
    _trade(db, "NVDA", 10, 100.0, 115.0, VIERNES)

    resumen = weekly_report.resumen_semanal(db, hasta=VIERNES)
    msg = weekly_report.mensaje_reporte_semanal(resumen)

    assert "Primera semana" in msg


def test_una_semana_sin_operaciones_igual_manda_mensaje(db):
    resumen = weekly_report.resumen_semanal(db, hasta=VIERNES)
    msg = weekly_report.mensaje_reporte_semanal(resumen)

    assert "Sin operaciones cerradas esta semana" in msg


def test_el_mensaje_recorta_el_detalle_largo(db):
    for i in range(weekly_report.MAX_OPERACIONES_DETALLADAS + 3):
        _trade(db, f"TK{i}", 10, 100.0, 110.0, VIERNES)

    resumen = weekly_report.resumen_semanal(db, hasta=VIERNES)
    msg = weekly_report.mensaje_reporte_semanal(resumen)

    assert "y 3 operación(es) más" in msg
    assert len(msg) <= notifications.LARGO_MAXIMO


# ---------- Envío ----------


def test_enviar_reporte_usa_parse_mode_html(db, monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        weekly_report.notifications,
        "send_telegram",
        lambda mensaje, parse_mode=None: llamadas.append((mensaje, parse_mode))
        or {"enviado": True, "motivo": ""},
    )
    _trade(db, "NVDA", 10, 100.0, 110.0, VIERNES)

    resultado = weekly_report.enviar_reporte_semanal(db=db, hasta=VIERNES)

    assert resultado["enviado"] is True
    assert llamadas[0][1] == "HTML"
    assert "NVDA" in llamadas[0][0]


def test_un_error_armando_el_reporte_no_se_propaga(db, monkeypatch):
    monkeypatch.setattr(
        weekly_report,
        "resumen_semanal",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("base rota")),
    )

    resultado = weekly_report.enviar_reporte_semanal(db=db, hasta=VIERNES)

    assert resultado["enviado"] is False
    assert "base rota" in resultado["motivo"]
