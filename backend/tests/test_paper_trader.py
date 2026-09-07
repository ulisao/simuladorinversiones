"""
Tests de la toma automática de posiciones en paper.

Lo que se verifica no es que sepa comprar — eso es una línea — sino que los
guardrails de `config.py` se respeten **todos**, porque cada uno que falle es
capital simulado mal asignado y, más adelante, un veredicto de rentabilidad que
no significa nada.

Nada acá le pega a IOL: el precio se inyecta o se mockea `precios.precio_operativo`.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config, models, paper_trader, precios, schemas
from app.database import Base

PRECIO = 1000.0


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine)()
    yield sesion
    sesion.close()


@pytest.fixture(autouse=True)
def habilitado(monkeypatch):
    """Por default en los tests la toma automática está encendida."""
    monkeypatch.setattr(config, "PAPER_AUTO_HABILITADO", True)


@pytest.fixture(autouse=True)
def sin_telegram(monkeypatch):
    monkeypatch.setattr(
        paper_trader.notifications, "send_telegram",
        lambda *a, **k: {"enviado": True, "motivo": ""},
    )


@pytest.fixture(autouse=True)
def capital_conocido(monkeypatch):
    """Fija el capital para que los montos de los tests no dependan del .env."""
    monkeypatch.setattr(config, "CAPITAL_TOTAL", 100_000.0)
    monkeypatch.setattr(config, "MAX_POSICIONES", 2)
    monkeypatch.setattr(config, "SALDO_MINIMO_OPERAR", 10_000.0)
    monkeypatch.setattr(config, "CUPOS_POR_ESTRATEGIA", {"SWING": 0.40, "SMART_MONEY": 0.60})
    monkeypatch.setattr(config, "LIMITE_POR_OPERACION", 0.50)


def _abrir_manual(db, ticker, cantidad=10, precio=PRECIO, estrategia="SWING"):
    t = models.Trade(
        ticker=ticker, tipo="CEDEAR", estrategia=estrategia,
        fecha_compra=date(2026, 9, 1), cantidad=cantidad, precio_entrada=precio,
    )
    db.add(t)
    db.commit()
    return t


# ---------- Interruptor ----------


def test_apagado_no_abre_nada(db, monkeypatch):
    monkeypatch.setattr(config, "PAPER_AUTO_HABILITADO", False)
    d = paper_trader.evaluar(db, "AAPL", precio=PRECIO)
    assert d["abrir"] is False and "apagada" in d["motivo"]


def test_encendido_abre(db):
    t = paper_trader.abrir_si_corresponde(db, "AAPL", precio=PRECIO)
    assert t is not None and t.ticker == "AAPL"


# ---------- Guardrails ----------


def test_no_duplica_un_activo_ya_abierto(db):
    _abrir_manual(db, "AAPL")
    d = paper_trader.evaluar(db, "AAPL", precio=PRECIO)
    assert d["abrir"] is False and "Ya hay una posición abierta" in d["motivo"]


def test_no_duplica_aunque_cambie_el_case(db):
    _abrir_manual(db, "AAPL")
    assert paper_trader.evaluar(db, "aapl", precio=PRECIO)["abrir"] is False


def test_respeta_el_maximo_de_posiciones(db):
    _abrir_manual(db, "AAPL")
    _abrir_manual(db, "NVDA")
    d = paper_trader.evaluar(db, "MELI", precio=PRECIO)
    assert d["abrir"] is False and "máximo es 2" in d["motivo"]


def test_una_posicion_cerrada_no_cuenta_para_el_maximo(db):
    t1 = _abrir_manual(db, "AAPL")
    t2 = _abrir_manual(db, "NVDA")
    t2.precio_salida = 1100.0
    t2.fecha_venta = date(2026, 9, 5)
    db.commit()
    assert paper_trader.evaluar(db, "MELI", precio=PRECIO)["abrir"] is True


def test_el_monto_sale_del_cupo_de_la_estrategia(db):
    """SWING: 100.000 * 0,40 de cupo, * 0,50 por operación = 20.000."""
    d = paper_trader.evaluar(db, "AAPL", estrategia="SWING", precio=PRECIO)
    assert d["cantidad"] == 20.0          # 20.000 / 1.000
    assert d["cantidad"] * PRECIO == 20_000.0


def test_smart_money_tiene_su_propio_cupo(db):
    """SMART_MONEY: 100.000 * 0,60 * 0,50 = 30.000."""
    d = paper_trader.evaluar(db, "AAPL", estrategia="SMART_MONEY", precio=PRECIO)
    assert d["cantidad"] == 30.0


def test_el_capital_ya_usado_descuenta_del_cupo(db):
    # SWING tiene 40.000 de cupo. Con 35.000 tomados quedan 5.000, por debajo
    # del piso de 10.000.
    _abrir_manual(db, "AAPL", cantidad=35, precio=1000.0, estrategia="SWING")
    d = paper_trader.evaluar(db, "NVDA", estrategia="SWING", precio=PRECIO)
    assert d["abrir"] is False and "Cupo de SWING casi agotado" in d["motivo"]


def test_el_cupo_de_una_estrategia_no_afecta_a_la_otra(db):
    _abrir_manual(db, "AAPL", cantidad=35, precio=1000.0, estrategia="SWING")
    assert paper_trader.evaluar(db, "NVDA", estrategia="SMART_MONEY", precio=PRECIO)["abrir"] is True


def test_no_compra_fracciones_de_papel(db):
    """Con 20.000 de cupo y un papel de 7.000 entran 2, no 2,857."""
    d = paper_trader.evaluar(db, "AAPL", precio=7000.0)
    assert d["cantidad"] == 2.0


def test_si_no_alcanza_para_un_papel_no_abre(db):
    d = paper_trader.evaluar(db, "BRKA", precio=999_999.0)
    assert d["abrir"] is False and "no alcanza para 1 papel" in d["motivo"]


# ---------- Precio ----------


def test_sin_precio_operativo_no_abre(db, monkeypatch):
    def explotar(simbolo, cliente=None):
        raise precios.PrecioError("IOL caído")

    monkeypatch.setattr(paper_trader.precios, "precio_operativo", explotar)
    d = paper_trader.evaluar(db, "AAPL")
    assert d["abrir"] is False and "Sin precio operativo" in d["motivo"]


def test_usa_el_precio_en_pesos_no_el_de_la_senal(db, monkeypatch):
    """El candidato trae USD 320 (yfinance); la posición se toma en pesos (IOL).

    Se usa $15.000 y no el precio real del CEDEAR de AAPL (~$25.400) porque a ese
    precio no entra ni un papel en el cupo de $20.000 — ver
    `test_un_cedear_mas_caro_que_el_cupo_no_se_puede_tomar`.
    """
    monkeypatch.setattr(paper_trader.precios, "precio_operativo", lambda s, cliente=None: 15_000.0)
    t = paper_trader.abrir_si_corresponde(db, "AAPL")
    assert t.precio_entrada == 15_000.0, "tomó el precio de la señal en vez del de BYMA"
    assert t.cantidad == 1.0


def test_un_cedear_mas_caro_que_el_cupo_no_se_puede_tomar(db, monkeypatch):
    """Con CAPITAL_TOTAL=100.000 el cupo por posición de swing es $20.000.

    Un CEDEAR de AAPL vale ~$25.400: no entra. No es un bug, es el capital
    configurado — pero conviene que quede fijado en un test, porque el síntoma
    (el bot nunca abre nada) es fácil de confundir con una falla.
    """
    monkeypatch.setattr(paper_trader.precios, "precio_operativo", lambda s, cliente=None: 25_400.0)
    d = paper_trader.evaluar(db, "AAPL")
    assert d["abrir"] is False and "no alcanza para 1 papel" in d["motivo"]


def test_un_precio_cero_no_abre(db):
    assert paper_trader.evaluar(db, "AAPL", precio=0.0)["abrir"] is False


# ---------- Efectos ----------


def test_la_operacion_queda_registrada_y_abierta(db, monkeypatch):
    monkeypatch.setattr(paper_trader.precios, "precio_operativo", lambda s, cliente=None: PRECIO)
    paper_trader.abrir_si_corresponde(db, "AAPL", senal="Breakout")
    t = db.query(models.Trade).filter_by(ticker="AAPL").one()
    assert t.precio_salida is None          # abierta, la gestiona el monitor
    assert t.senal == "Breakout"
    assert t.fecha_compra == date.today()


def test_avisa_por_telegram_al_abrir(db, monkeypatch):
    enviados = []
    monkeypatch.setattr(
        paper_trader.notifications, "send_telegram",
        lambda m, **k: enviados.append(m) or {"enviado": True, "motivo": ""},
    )
    paper_trader.abrir_si_corresponde(db, "AAPL", precio=PRECIO)
    assert len(enviados) == 1
    assert "AAPL" in enviados[0]
    assert "no se envió ninguna orden" in enviados[0].lower()


def test_si_telegram_falla_la_posicion_igual_queda_abierta(db, monkeypatch):
    monkeypatch.setattr(
        paper_trader.notifications, "send_telegram",
        lambda *a, **k: {"enviado": False, "motivo": "sin red"},
    )
    t = paper_trader.abrir_si_corresponde(db, "AAPL", precio=PRECIO)
    assert t is not None


def test_nunca_lanza_aunque_falle_todo(db, monkeypatch):
    def explotar(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(paper_trader, "evaluar", explotar)
    assert paper_trader.abrir_si_corresponde(db, "AAPL") is None


# ---------- Desde un escaneo ----------


def test_abre_desde_los_candidatos_de_un_escaneo(db, monkeypatch):
    monkeypatch.setattr(paper_trader.precios, "precio_operativo", lambda s, cliente=None: PRECIO)
    candidatos = [
        {"ticker": "AAPL", "origen": "7_FILTROS", "stop_loss": 970.0, "take_profit": 1060.0},
        {"ticker": "NVDA", "origen": "RSI", "rsi": 28.4},
    ]
    abiertas = paper_trader.abrir_desde_candidatos(db, candidatos)
    assert len(abiertas) == 2
    assert "7_FILTROS" in abiertas[0].senal
    assert "RSI 28.4" in abiertas[1].senal


def test_los_bonos_usan_simbolo_en_vez_de_ticker(db, monkeypatch):
    monkeypatch.setattr(paper_trader.precios, "precio_operativo", lambda s, cliente=None: PRECIO)
    abiertas = paper_trader.abrir_desde_candidatos(
        db, [{"simbolo": "AL30", "tipo": "BONO"}], tipo="BONO"
    )
    assert len(abiertas) == 1 and abiertas[0].ticker == "AL30" and abiertas[0].tipo == "BONO"


def test_el_maximo_corta_a_mitad_de_la_lista(db, monkeypatch):
    monkeypatch.setattr(paper_trader.precios, "precio_operativo", lambda s, cliente=None: PRECIO)
    candidatos = [{"ticker": t} for t in ("AAPL", "NVDA", "MELI", "KO")]
    abiertas = paper_trader.abrir_desde_candidatos(db, candidatos)
    assert len(abiertas) == config.MAX_POSICIONES


def test_no_pide_el_precio_dos_veces_por_candidato_rechazado(db, monkeypatch):
    """Con capital chico el rechazo es el caso común: re-evaluar duplicaría las
    llamadas a IOL en cada ciclo de cada rueda."""
    llamadas = []
    monkeypatch.setattr(
        paper_trader.precios, "precio_operativo",
        lambda s, cliente=None: llamadas.append(s) or 999_999.0,   # nunca alcanza
    )
    abiertas = paper_trader.abrir_desde_candidatos(
        db, [{"simbolo": "AL30"}, {"simbolo": "GD30"}], tipo="BONO"
    )
    assert abiertas == []
    assert llamadas == ["AL30", "GD30"], f"pidió el precio de más: {llamadas}"
