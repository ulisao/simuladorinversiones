"""
Tests del tracker de consenso institucional (Tarea 5.4).

Sin red: los movimientos 13F se arman a mano y el precio actual se inyecta.
Lo que importa verificar acá:

* que **haga falta consenso** (varios fondos), no un fondo solo,
* que el peso en la cartera del fondo filtre el ruido,
* que el filtro anti-tarde funcione (los 13F llegan con hasta 45 días de rezago),
* que para **vender** alcance con un fondo, a diferencia de comprar.
"""
import pytest

from app import config, edgar_13f, wallstreet_tracker
from app.wallstreet_tracker import WallStreetAdvancedTracker


def _mov(fondo, ticker, tipo=edgar_13f.AUMENTO, peso=0.05, precio=100.0, valor=1_000_000.0):
    return {
        "fondo": fondo,
        "cik": "000",
        "ticker": ticker,
        "cusip": "x",
        "nombre": ticker,
        "tipo": tipo,
        "valor": valor,
        "peso_cartera": peso,
        "acciones": 1000.0,
        "acciones_previas": 500.0,
        "precio_promedio": precio,
    }


def _tracker(**kwargs):
    """Tracker con el universo acotado, para no depender de config.TICKERS_BYMA."""
    kwargs.setdefault("universo", ["NVDA", "AAPL", "KO", "MELI"])
    return WallStreetAdvancedTracker(**kwargs)


# Sin este proveedor el tracker saldría a buscar el precio a Yahoo.
def _precios(**kwargs):
    return dict(kwargs)


# ---------- Consenso ----------


def test_un_solo_fondo_no_alcanza():
    """Seguir a un fondo es seguir a una persona; el consenso es la señal."""
    movs = [_mov("Berkshire", "NVDA")]

    r = _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))

    assert r["compras"] == []
    assert "SIN CONSENSO" in r["descartados"][0]["motivo"]


def test_dos_fondos_generan_senal():
    movs = [_mov("Berkshire", "NVDA"), _mov("Renaissance", "NVDA")]

    r = _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))

    assert len(r["compras"]) == 1
    señal = r["compras"][0]
    assert señal["ticker"] == "NVDA"
    assert señal["consenso"] == 2
    assert sorted(señal["fondos"]) == ["Berkshire", "Renaissance"]
    assert señal["estrategia"] == config.ESTRATEGIA_SMART_MONEY


def test_el_minimo_de_consenso_es_configurable():
    movs = [_mov("A", "NVDA"), _mov("B", "NVDA"), _mov("C", "NVDA")]

    assert _tracker(min_consenso=3).procesar_reportes(movs, precios=_precios(NVDA=100.0))["compras"]
    assert not _tracker(min_consenso=4).procesar_reportes(movs, precios=_precios(NVDA=100.0))["compras"]


def test_una_venta_no_cuenta_para_el_consenso_de_compra():
    movs = [
        _mov("Berkshire", "NVDA", tipo=edgar_13f.AUMENTO),
        _mov("Bridgewater", "NVDA", tipo=edgar_13f.REDUCCION),
    ]

    r = _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))

    assert r["compras"] == []


def test_una_posicion_nueva_cuenta_igual_que_un_aumento():
    movs = [
        _mov("Berkshire", "NVDA", tipo=edgar_13f.NUEVA),
        _mov("Renaissance", "NVDA", tipo=edgar_13f.AUMENTO),
    ]

    assert _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))["compras"]


# ---------- Peso en la cartera del fondo ----------


def test_una_posicion_chica_para_el_fondo_no_cuenta():
    """Por debajo del peso mínimo la posición es ruido, no convicción."""
    movs = [_mov("A", "NVDA", peso=0.0001), _mov("B", "NVDA", peso=0.0001)]

    r = _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))

    assert r["compras"] == []
    assert "2 compraron sin alcanzar el peso mínimo" in r["descartados"][0]["motivo"]


def test_el_peso_minimo_sale_de_config():
    justo = config.SMART_MIN_PESO_CARTERA
    movs = [_mov("A", "NVDA", peso=justo), _mov("B", "NVDA", peso=justo)]

    assert _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))["compras"]


# ---------- Anti-tarde ----------


def test_si_el_papel_ya_volo_la_senal_se_descarta():
    """Los 13F salen con hasta 45 días de rezago: sin esto se compra siempre arriba."""
    movs = [_mov("A", "NVDA", precio=100.0), _mov("B", "NVDA", precio=100.0)]

    r = _tracker().procesar_reportes(movs, precios=_precios(NVDA=130.0))  # +30%

    assert r["compras"] == []
    assert "VETO TARDE" in r["descartados"][0]["motivo"]


def test_un_papel_que_bajo_desde_el_filing_pasa():
    movs = [_mov("A", "NVDA", precio=100.0), _mov("B", "NVDA", precio=100.0)]

    r = _tracker().procesar_reportes(movs, precios=_precios(NVDA=90.0))

    assert r["compras"][0]["delta_vs_fondos"] == pytest.approx(-0.10)


def test_el_precio_de_referencia_pondera_por_tamano():
    """Un fondo que puso $10.000M pesa más que uno que puso $50M."""
    movs = [
        _mov("Grande", "NVDA", precio=100.0, valor=10_000_000_000.0),
        _mov("Chico", "NVDA", precio=200.0, valor=50_000_000.0),
    ]

    r = _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))

    # Promedio simple daría 150; ponderado da ~100,5.
    assert r["compras"][0]["precio_promedio_fondos"] == pytest.approx(100.5, abs=0.1)


# ---------- Universo ----------


def test_un_papel_sin_cedear_habilitado_no_genera_senal():
    movs = [_mov("A", "GOOG"), _mov("B", "GOOG")]

    r = _tracker().procesar_reportes(movs, precios=_precios(GOOG=100.0))

    assert r["compras"] == []
    assert "FUERA DE UNIVERSO" in r["descartados"][0]["motivo"]


# ---------- Precio no disponible ----------


def test_un_ticker_sin_precio_se_descarta_sin_romper_el_barrido():
    movs = [_mov("A", "NVDA"), _mov("B", "NVDA"), _mov("A", "KO"), _mov("B", "KO")]

    def precio(ticker):
        if ticker == "NVDA":
            raise RuntimeError("Yahoo caído")
        return 100.0

    r = _tracker().procesar_reportes(movs, proveedor_precio=precio)

    assert [c["ticker"] for c in r["compras"]] == ["KO"], "KO se evaluó igual"
    assert any("SIN PRECIO" in d["motivo"] for d in r["descartados"])


def test_sin_precio_promedio_en_los_filings_se_descarta_con_motivo():
    movs = [_mov("A", "NVDA", precio=None), _mov("B", "NVDA", precio=None)]

    r = _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))

    assert r["compras"] == []
    assert "SIN DATOS" in r["descartados"][0]["motivo"]


# ---------- Riesgo de la señal ----------


def test_la_senal_trae_stop_y_objetivo(monkeypatch):
    import numpy as np
    import pandas as pd

    cierres = np.linspace(90, 100, 60)
    df = pd.DataFrame(
        {"Open": cierres, "High": cierres * 1.02, "Low": cierres * 0.98,
         "Close": cierres, "Volume": np.full(60, 1_000)},
        index=pd.date_range("2026-01-01", periods=60, freq="D"),
    )
    monkeypatch.setattr(wallstreet_tracker.market_data, "get_history", lambda t, period=None: df)

    movs = [_mov("A", "NVDA"), _mov("B", "NVDA")]
    señal = _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))["compras"][0]

    assert señal["stop_loss"] < 100.0 < señal["take_profit"]
    assert señal["pct_riesgo"] <= config.STOP_LOSS_MAX_PCT * 100 + 1e-9


def test_sin_historico_la_senal_sale_igual_con_el_riesgo_en_none(monkeypatch):
    """El consenso institucional vale aunque hoy no haya datos técnicos."""
    def revienta(ticker, period=None):
        raise RuntimeError("sin histórico")

    monkeypatch.setattr(wallstreet_tracker.market_data, "get_history", revienta)

    movs = [_mov("A", "NVDA"), _mov("B", "NVDA")]
    señal = _tracker().procesar_reportes(movs, precios=_precios(NVDA=100.0))["compras"][0]

    assert señal["stop_loss"] is None
    assert señal["ticker"] == "NVDA"


# ---------- Señales de venta ----------


def test_un_solo_fondo_saliendo_ya_avisa():
    """Asimetría deliberada: para entrar hace falta consenso, para salir no."""
    movs = [_mov("Bridgewater", "NVDA", tipo=edgar_13f.REDUCCION)]

    ventas = _tracker().senales_de_venta(movs, ["NVDA"])

    assert len(ventas) == 1
    assert "redujo" in ventas[0]["motivo"]


def test_un_cierre_se_describe_como_cierre():
    movs = [_mov("Bridgewater", "NVDA", tipo=edgar_13f.CIERRE)]

    assert "cerró" in _tracker().senales_de_venta(movs, ["NVDA"])[0]["motivo"]


def test_no_se_avisa_de_papeles_que_no_tenemos():
    movs = [_mov("Bridgewater", "NVDA", tipo=edgar_13f.CIERRE)]

    assert _tracker().senales_de_venta(movs, ["AAPL"]) == []


def test_un_aumento_no_es_senal_de_venta():
    movs = [_mov("Bridgewater", "NVDA", tipo=edgar_13f.AUMENTO)]

    assert _tracker().senales_de_venta(movs, ["NVDA"]) == []
