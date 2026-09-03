"""
Tests del monitor de posiciones (Tarea 3.6) y de la venta parcial en `crud`.

Todo contra una base SQLite en memoria y con el precio inyectado: ningún test
de este archivo le pega a internet ni toca `simulador.db`.

Lo que más importa verificar acá es que la venta parcial **no rompe los cálculos
de `calculations.py`**: al partir la operación en dos registros, la suma de los
dos tiene que dar exactamente lo mismo que daría la posición entera.
"""
from datetime import date, datetime

import pytest
import pytz
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import crud, models
from app.calculations import BrokerRates, compute_trade
from app.config import TZ_BYMA
from app.database import Base


TASAS = BrokerRates(comision_broker=0.005, derechos_mercado=0.0008, iva=0.21)


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


def _trade_abierto(db, cantidad=10.0, precio=100.0, ticker="NVDA"):
    t = models.Trade(
        ticker=ticker,
        tipo="CEDEAR",
        fecha_compra=date(2026, 8, 3),
        cantidad=cantidad,
        precio_entrada=precio,
        senal="Señal IA",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# ---------- Venta parcial ----------


def test_la_venta_parcial_parte_la_operacion_en_dos(db):
    trade = _trade_abierto(db, cantidad=10.0)

    cerrado, remanente = crud.vender_parcial(
        db, trade, 5.0, 104.5, date(2026, 8, 4), "TP1_PARTIAL_50PCT (+4.50%)"
    )

    assert cerrado.cantidad == 5.0
    assert cerrado.precio_salida == 104.5
    assert remanente.id == trade.id
    assert remanente.cantidad == 5.0
    assert remanente.precio_salida is None, "el remanente tiene que seguir abierto"


def test_partir_la_operacion_no_altera_el_resultado_total(db):
    """La suma de los dos registros = la posición entera vendida al mismo precio."""
    entera = compute_trade(10.0, 100.0, 104.5, TASAS)

    trade = _trade_abierto(db, cantidad=10.0, precio=100.0)
    cerrado, remanente = crud.vender_parcial(
        db, trade, 5.0, 104.5, date(2026, 8, 4), "TP1"
    )
    mitad_a = compute_trade(cerrado.cantidad, cerrado.precio_entrada, 104.5, TASAS)
    mitad_b = compute_trade(remanente.cantidad, remanente.precio_entrada, 104.5, TASAS)

    assert mitad_a.resultado_neto + mitad_b.resultado_neto == pytest.approx(
        entera.resultado_neto, abs=0.01
    )


def test_vender_todo_cierra_el_registro_sin_crear_otro(db):
    trade = _trade_abierto(db, cantidad=10.0)

    cerrado, remanente = crud.vender_parcial(
        db, trade, 10.0, 108.0, date(2026, 8, 4), "TP2_CEILING_HIT"
    )

    assert remanente is None
    assert cerrado.id == trade.id
    assert db.query(models.Trade).count() == 1, "no se crea una fila vacía"


@pytest.mark.parametrize("cantidad", [0, -3, 11])
def test_cantidad_invalida_no_deja_la_base_inconsistente(db, cantidad):
    trade = _trade_abierto(db, cantidad=10.0)

    with pytest.raises(ValueError):
        crud.vender_parcial(db, trade, cantidad, 104.5, date(2026, 8, 4), "x")

    assert trade.cantidad == 10.0


def test_listar_trades_abiertos_ignora_los_cerrados(db):
    abierto = _trade_abierto(db, ticker="NVDA")
    cerrado = _trade_abierto(db, ticker="KO")
    crud.vender_parcial(db, cerrado, cerrado.cantidad, 99.0, date(2026, 8, 4), "SL")

    abiertos = crud.listar_trades_abiertos(db)

    assert [t.id for t in abiertos] == [abierto.id]


# ---------- Persistencia del estado ----------


def test_el_estado_del_gestor_se_guarda_y_se_actualiza(db):
    trade = _trade_abierto(db)

    crud.guardar_position_state(db, trade.id, {
        "is_tp1_hit": False, "is_closed": False, "max_price_since_tp1": 0.0,
        "current_stop_price": 97.0, "remaining_qty": 10.0,
    })
    crud.guardar_position_state(db, trade.id, {
        "is_tp1_hit": True, "is_closed": False, "max_price_since_tp1": 106.0,
        "current_stop_price": 104.7, "remaining_qty": 5.0,
    })

    fila = crud.get_position_state(db, trade.id)
    assert fila.is_tp1_hit is True
    assert fila.current_stop_price == pytest.approx(104.7)
    assert db.query(models.PositionState).count() == 1, "una sola fila por operación"


# ---------- Ciclo del monitor ----------


def _momento(hh, mm):
    return pytz.timezone(TZ_BYMA).localize(datetime(2026, 8, 3, hh, mm))  # lunes


def test_el_tp1_vende_la_mitad_y_deja_el_resto_abierto(db, monkeypatch):
    from app import position_manager
    import position_monitor_job as job

    trade = _trade_abierto(db, cantidad=10.0, precio=100.0)

    accion = job.procesar_trade(db, trade, 104.5, _momento(12, 0))

    assert accion["reason"] == position_manager.MOTIVO_TP1_PARCIAL
    assert accion["qty"] == 5
    assert crud.get_position_state(db, trade.id).is_tp1_hit is True
    assert db.query(models.Trade).count() == 2
    assert trade.cantidad == 5.0


def test_el_estado_sobrevive_entre_ciclos(db):
    """Segundo ciclo: el trailing tiene que seguir desde donde quedó, no reiniciarse."""
    import position_monitor_job as job

    trade = _trade_abierto(db, cantidad=10.0, precio=100.0)

    job.procesar_trade(db, trade, 104.5, _momento(12, 0))   # dispara TP1
    stop_tras_tp1 = crud.get_position_state(db, trade.id).current_stop_price

    job.procesar_trade(db, trade, 107.0, _momento(12, 30))  # nuevo pico
    stop_tras_pico = crud.get_position_state(db, trade.id).current_stop_price

    assert stop_tras_pico > stop_tras_tp1, "el trailing tiene que haber subido"

    job.procesar_trade(db, trade, 106.0, _momento(13, 0))   # baja sin tocar el stop
    assert crud.get_position_state(db, trade.id).current_stop_price == pytest.approx(
        stop_tras_pico
    ), "el stop nunca baja"


def test_el_stop_inicial_cierra_toda_la_posicion(db):
    from app import position_manager
    import position_monitor_job as job

    trade = _trade_abierto(db, cantidad=10.0, precio=100.0)

    accion = job.procesar_trade(db, trade, 96.5, _momento(12, 0))

    assert accion["reason"] == position_manager.MOTIVO_STOP_INICIAL
    assert trade.precio_salida == 96.5
    assert crud.listar_trades_abiertos(db) == []


def test_el_cierre_preventivo_liquida_el_remanente_a_las_1650(db):
    from app import position_manager
    import position_monitor_job as job

    trade = _trade_abierto(db, cantidad=10.0, precio=100.0)
    job.procesar_trade(db, trade, 104.5, _momento(12, 0))  # cobra TP1

    accion = job.procesar_trade(db, trade, 105.0, _momento(16, 50))

    assert accion["reason"] == position_manager.MOTIVO_CIERRE_PREVENTIVO
    assert crud.listar_trades_abiertos(db) == [], "no queda nada abierto overnight"


def test_sin_tp1_el_cierre_preventivo_no_dispara(db):
    import position_monitor_job as job

    trade = _trade_abierto(db, cantidad=10.0, precio=100.0)

    accion = job.procesar_trade(db, trade, 101.0, _momento(16, 55))

    assert accion is None, "sin TP1 cobrado la posición se mantiene"
    assert trade.precio_salida is None


def test_una_posicion_de_un_papel_no_manda_una_orden_vacia(db):
    """`total_qty // 2` da 0: no hay nada que vender, pero el estado avanza igual."""
    import position_monitor_job as job

    trade = _trade_abierto(db, cantidad=1.0, precio=100.0)

    accion = job.procesar_trade(db, trade, 104.5, _momento(12, 0))

    assert accion["qty"] == 0
    assert db.query(models.Trade).count() == 1, "no se creó un registro de venta vacío"
    assert crud.get_position_state(db, trade.id).is_tp1_hit is True


# ---------- Horario de rueda ----------


@pytest.mark.parametrize(
    "momento,esperado",
    [
        (_momento(10, 30), False),  # antes de la apertura
        (_momento(11, 0), True),    # apertura justa
        (_momento(14, 0), True),
        (_momento(17, 0), True),    # cierre justo
        (_momento(17, 30), False),  # después del cierre
    ],
)
def test_ventana_de_rueda(momento, esperado):
    import position_monitor_job as job

    assert job.es_horario_de_rueda(momento) is esperado


def test_el_fin_de_semana_no_es_rueda():
    import position_monitor_job as job

    sabado = pytz.timezone(TZ_BYMA).localize(datetime(2026, 8, 8, 13, 0))
    assert job.es_horario_de_rueda(sabado) is False


def test_cerca_del_cierre_el_sondeo_se_hace_mas_fino():
    """Si sondeáramos cada 5 min podríamos pasar de largo la ventana de las 16:50."""
    import position_monitor_job as job

    assert job.intervalo_actual(_momento(13, 0)) == job.INTERVALO_NORMAL_SEG
    assert job.intervalo_actual(_momento(16, 45)) == job.INTERVALO_CERCA_DEL_CIERRE_SEG
