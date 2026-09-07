"""
Tests del desglose por estrategia y de la migración de esquema (Tarea 5.5).

Base SQLite en memoria. Lo que importa verificar acá:

* que el dashboard **separe** las dos estrategias en vez de mezclarlas (mezclarlas
  haría imposible saber cuál rinde),
* que los totales sigan siendo los de siempre — el desglose es aditivo,
* que la migración agregue `trades.estrategia` sobre una base **con datos**, que
  es lo que `create_all` no hace.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app import config, crud, migrations, models, schemas
from app.calculations import BrokerRates, compute_trade
from app.database import Base


TASAS = BrokerRates(comision_broker=0.005, derechos_mercado=0.0008, iva=0.21)

SWING = config.ESTRATEGIA_SWING
SMART = config.ESTRATEGIA_SMART_MONEY


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine)()
    try:
        yield sesion
    finally:
        sesion.close()


def _trade(db, ticker, estrategia=SWING, cantidad=10, entrada=100.0, salida=None):
    t = models.Trade(
        ticker=ticker,
        tipo="CEDEAR",
        estrategia=estrategia,
        fecha_compra=date(2026, 9, 1),
        cantidad=cantidad,
        precio_entrada=entrada,
        precio_salida=salida,
        fecha_venta=date(2026, 9, 4) if salida else None,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _de(dashboard, estrategia):
    return next(e for e in dashboard.por_estrategia if e.estrategia == estrategia)


# ---------- Desglose ----------


def test_las_dos_estrategias_aparecen_aunque_no_tengan_operaciones(db):
    """Un cupo asignado con cero operaciones es información, no un hueco."""
    d = crud.build_dashboard(db)

    assert {e.estrategia for e in d.por_estrategia} == {SWING, SMART}
    assert _de(d, SMART).total_operaciones_ejecutadas == 0


def test_cada_estrategia_lleva_su_propio_resultado(db):
    _trade(db, "NVDA", SWING, salida=110.0)     # gana
    _trade(db, "AAPL", SMART, salida=90.0)      # pierde

    d = crud.build_dashboard(db)

    assert _de(d, SWING).ganancia_perdida_neta_total > 0
    assert _de(d, SMART).ganancia_perdida_neta_total < 0
    assert _de(d, SWING).operaciones_ganadoras == 1
    assert _de(d, SMART).operaciones_perdedoras == 1


def test_el_total_general_no_cambia_con_el_desglose(db):
    _trade(db, "NVDA", SWING, salida=110.0)
    _trade(db, "AAPL", SMART, salida=90.0)

    d = crud.build_dashboard(db)
    suma = sum(e.ganancia_perdida_neta_total for e in d.por_estrategia)

    assert d.ganancia_perdida_neta_total == pytest.approx(suma, abs=0.01)
    assert d.total_operaciones_ejecutadas == sum(
        e.total_operaciones_ejecutadas for e in d.por_estrategia
    )


def test_el_desglose_coincide_con_calculations(db):
    """El dashboard no puede inventar números propios."""
    _trade(db, "NVDA", SMART, cantidad=10, entrada=100.0, salida=110.0)
    esperado = compute_trade(10, 100.0, 110.0, TASAS).resultado_neto

    assert _de(crud.build_dashboard(db), SMART).ganancia_perdida_neta_total == pytest.approx(
        round(esperado, 2)
    )


def test_las_posiciones_abiertas_se_cuentan_por_estrategia(db):
    _trade(db, "NVDA", SMART)                 # abierta
    _trade(db, "MELI", SMART)                 # abierta
    _trade(db, "AAPL", SWING, salida=110.0)   # cerrada

    d = crud.build_dashboard(db)

    assert _de(d, SMART).posiciones_abiertas == 2
    assert _de(d, SWING).posiciones_abiertas == 0


def test_cada_estrategia_informa_su_cupo(db):
    d = crud.build_dashboard(db)

    assert _de(d, SWING).cupo_asignado == pytest.approx(
        config.CAPITAL_TOTAL * config.CUPO_SWING
    )
    assert _de(d, SMART).cupo_asignado == pytest.approx(
        config.CAPITAL_TOTAL * config.CUPO_SMART_MONEY
    )


def test_una_estrategia_desconocida_igual_aparece(db):
    """Si alguien carga a mano una estrategia que no está en config, no se pierde."""
    _trade(db, "NVDA", "EXPERIMENTAL", salida=110.0)

    d = crud.build_dashboard(db)

    assert _de(d, "EXPERIMENTAL").total_operaciones_ejecutadas == 1
    assert _de(d, "EXPERIMENTAL").cupo_asignado == 0.0, "sin cupo configurado"


# ---------- Cupos de config ----------


def test_los_cupos_suman_el_capital_entero():
    assert config.CUPO_SWING + config.CUPO_SMART_MONEY == pytest.approx(1.0)


def test_el_monto_por_posicion_sale_del_cupo_de_su_estrategia():
    """Decisión de la Tarea 0.1: el límite por operación se aplica sobre el cupo."""
    swing = config.monto_por_posicion(SWING)
    smart = config.monto_por_posicion(SMART)

    assert swing == pytest.approx(
        config.CAPITAL_TOTAL * config.CUPO_SWING * config.LIMITE_POR_OPERACION
    )
    assert smart > swing, "el cupo de smart money es mayor (60/40)"


def test_una_posicion_nunca_se_pasa_del_cupo_de_su_estrategia():
    """Es la aritmética que hacía imposible el 50% sobre el capital total."""
    for estrategia in (SWING, SMART):
        assert config.monto_por_posicion(estrategia) <= config.cupo_de(estrategia)


# ---------- Alta de operaciones ----------


def test_una_operacion_nueva_es_swing_por_defecto(db):
    trade = crud.create_trade(
        db,
        schemas.TradeCreate(
            ticker="nvda", fecha_compra=date(2026, 9, 1), cantidad=10, precio_entrada=100.0
        ),
    )

    assert trade.estrategia == SWING


def test_se_puede_cargar_una_operacion_de_smart_money(db):
    trade = crud.create_trade(
        db,
        schemas.TradeCreate(
            ticker="nvda", estrategia="smart_money", fecha_compra=date(2026, 9, 1),
            cantidad=10, precio_entrada=100.0,
        ),
    )

    assert trade.estrategia == SMART, "se normaliza a mayúsculas"


# ---------- Migración ----------


def test_la_migracion_agrega_la_columna_sobre_una_base_con_datos():
    """`create_all` no toca tablas existentes: esto es lo que sí las migra."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    # Esquema viejo, sin `estrategia`, y con una operación ya cargada.
    with engine.begin() as cx:
        cx.execute(text(
            "CREATE TABLE trades (id INTEGER PRIMARY KEY, ticker VARCHAR, tipo VARCHAR, "
            "fecha_compra DATE, cantidad FLOAT, precio_entrada FLOAT, fecha_venta DATE, "
            "precio_salida FLOAT, senal VARCHAR)"
        ))
        cx.execute(text(
            "INSERT INTO trades (ticker, tipo, fecha_compra, cantidad, precio_entrada) "
            "VALUES ('AAPL', 'CEDEAR', '2026-09-01', 10, 100.0)"
        ))

    aplicadas = migrations.migrar(engine)

    assert "trades.estrategia" in aplicadas
    assert "estrategia" in [c["name"] for c in inspect(engine).get_columns("trades")]

    with engine.begin() as cx:
        fila = cx.execute(text("SELECT estrategia FROM trades")).scalar()
    assert fila == SWING, "lo que ya estaba cargado es swing: era la única estrategia"


def test_la_migracion_es_idempotente():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    assert migrations.migrar(engine) == [], "create_all ya la creó con la columna"
    assert migrations.migrar(engine) == []


def test_la_migracion_no_falla_si_la_tabla_no_existe():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    assert migrations.migrar(engine) == []
