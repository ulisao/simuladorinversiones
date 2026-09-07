"""
Tests del precio operativo en pesos y de que el monitor lo use.

El bug que estos tests existen para evitar: sondear una posición tomada en pesos
contra el precio del subyacente en dólares. Un CEDEAR de AAPL a $25.400 comparado
contra US$ 319 se ve como una pérdida del 98,7% y el gestor liquidaría la
posición en el primer tick.
"""
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import position_monitor_job
from app import broker_iol, models, precios
from app.database import Base


class ClienteFalso:
    """Doble de `IOLClient`: no habla con la red."""

    def __init__(self, cotizacion=None, error=None, configurado=True):
        self._cotizacion = cotizacion or {}
        self._error = error
        self._configurado = configurado

    @property
    def esta_configurado(self):
        # property, igual que en IOLClient: como método, el doble tapaba un bug
        # real (`if not cli.esta_configurado()` sobre un bool -> TypeError).
        return self._configurado

    def get_cotizacion(self, simbolo, mercado="bCBA"):
        if self._error:
            raise self._error
        return self._cotizacion


# ---------- precio_operativo ----------


def test_devuelve_el_ultimo_precio_en_pesos():
    cli = ClienteFalso({"ultimoPrecio": 25_400.0})
    assert precios.precio_operativo("AAPL", cliente=cli) == 25_400.0


def test_sin_iol_configurado_levanta_precio_error():
    cli = ClienteFalso(configurado=False)
    with pytest.raises(precios.PrecioError, match="IOL no configurado"):
        precios.precio_operativo("AAPL", cliente=cli)


def test_un_error_de_iol_se_traduce_a_precio_error():
    cli = ClienteFalso(error=broker_iol.IOLError("404 símbolo inexistente"))
    with pytest.raises(precios.PrecioError, match="no devolvió cotización"):
        precios.precio_operativo("XXXX", cliente=cli)


def test_un_error_inesperado_tampoco_se_propaga_crudo():
    cli = ClienteFalso(error=RuntimeError("la red explotó"))
    with pytest.raises(precios.PrecioError, match="error inesperado"):
        precios.precio_operativo("AAPL", cliente=cli)


@pytest.mark.parametrize("valor", [0, 0.0, -5, None, "", "n/d"])
def test_un_precio_no_operable_no_pasa(valor):
    """Fuera de rueda IOL puede devolver 0 o nulo: eso no es un precio."""
    cli = ClienteFalso({"ultimoPrecio": valor})
    with pytest.raises(precios.PrecioError, match="no operable"):
        precios.precio_operativo("AL30", cliente=cli)


def test_los_bonos_funcionan_igual_que_los_cedears():
    """`get_last_price` de yfinance falla con AL30; IOL no."""
    cli = ClienteFalso({"ultimoPrecio": 1_450.75})
    assert precios.precio_operativo("AL30", cliente=cli) == 1_450.75


# ---------- El monitor usa este precio, no el de yfinance ----------


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Sesion = sessionmaker(bind=engine)
    monkeypatch.setattr(position_monitor_job, "SessionLocal", Sesion)
    sesion = Sesion()
    yield sesion
    sesion.close()


def _abrir(db, ticker="AAPL", precio=1000.0):
    t = models.Trade(
        ticker=ticker, tipo="CEDEAR", estrategia="SWING",
        fecha_compra=date(2026, 9, 1), cantidad=10, precio_entrada=precio,
    )
    db.add(t)
    db.commit()
    return t


def test_el_ciclo_sondea_con_el_precio_en_pesos(db, monkeypatch):
    _abrir(db)
    pedidos = []
    monkeypatch.setattr(
        position_monitor_job.precios, "precio_operativo",
        lambda s, cliente=None: pedidos.append(s) or 1050.0,
    )
    monkeypatch.setattr(
        position_monitor_job, "procesar_trade",
        lambda db_, trade, precio, momento: {"ticker": trade.ticker, "precio": precio},
    )
    acciones = position_monitor_job.ciclo(ignorar_horario=True)
    assert pedidos == ["AAPL"]
    assert acciones[0]["precio"] == 1050.0


def test_si_no_hay_precio_se_saltea_y_no_gestiona(db, monkeypatch):
    """Mejor no gestionar el tick que gestionarlo con el precio equivocado."""
    _abrir(db)

    def sin_precio(simbolo, cliente=None):
        raise precios.PrecioError("IOL caído")

    monkeypatch.setattr(position_monitor_job.precios, "precio_operativo", sin_precio)
    llamadas = []
    monkeypatch.setattr(
        position_monitor_job, "procesar_trade",
        lambda *a, **k: llamadas.append(a) or None,
    )
    assert position_monitor_job.ciclo(ignorar_horario=True) == []
    assert llamadas == [], "no puede gestionar una posición sin precio confiable"


def test_una_posicion_sin_precio_no_frena_a_las_demas(db, monkeypatch):
    _abrir(db, "AL30")
    _abrir(db, "AAPL")

    def precio_parcial(simbolo, cliente=None):
        if simbolo == "AL30":
            raise precios.PrecioError("sin cotización")
        return 1100.0

    monkeypatch.setattr(position_monitor_job.precios, "precio_operativo", precio_parcial)
    monkeypatch.setattr(
        position_monitor_job, "procesar_trade",
        lambda db_, trade, precio, momento: {"ticker": trade.ticker},
    )
    acciones = position_monitor_job.ciclo(ignorar_horario=True)
    assert [a["ticker"] for a in acciones] == ["AAPL"]


def test_el_monitor_ya_no_importa_yfinance():
    """Fija el arreglo: si alguien vuelve a traer get_last_price, esto falla."""
    fuente = open(position_monitor_job.__file__, encoding="utf-8").read()
    assert "get_last_price" not in fuente
    assert "precios.precio_operativo" in fuente
