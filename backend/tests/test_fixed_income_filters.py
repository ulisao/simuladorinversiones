"""
Tests de `app/fixed_income_filters.py`.

Offline y determinístico. Los bonos argentinos casi no tienen histórico en Yahoo
Finance, así que las series se construyen a mano: es la única forma de ejercitar
los caminos de EMA20 y ATR, que con datos reales hoy no se alcanzan.

El veto por corte de cupón se prueba inyectando la fecha (`ahora=`), porque los
soberanos cortan en enero y julio y una corrida en cualquier otro mes lo dejaría
sin cubrir.
"""
import numpy as np
import pandas as pd
import pytest

from app import config
from app import fixed_income_filters as fif


def serie_bono(base: float, pendiente: float, n: int = 60) -> pd.DataFrame:
    idx = pd.date_range("2026-06-01", periods=n, freq="B")
    close = base + pendiente * np.arange(n)
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


# ---------- Veto por calendario de corte de cupón ----------


def test_vetea_dentro_de_la_ventana_de_corte_de_cupon():
    # AL30 corta en enero (mes 1); el día 5 cae en la ventana 1-12.
    valido, detalle = fif.evaluate_bond_filters(
        "AL30", 72.5, None, ahora=pd.Timestamp("2027-01-05")
    )

    assert valido is False
    assert "CUPÓN" in detalle["motivo"].upper()


def test_no_vetea_fuera_de_la_ventana_aunque_sea_mes_de_corte():
    valido, _ = fif.evaluate_bond_filters(
        "AL30", 72.5, None, ahora=pd.Timestamp("2027-01-20")
    )

    assert valido is True


def test_no_vetea_en_un_mes_sin_corte():
    valido, _ = fif.evaluate_bond_filters(
        "AL30", 72.5, None, ahora=pd.Timestamp("2027-03-05")
    )

    assert valido is True


def test_bono_sin_calendario_conocido_no_vetea_por_cupon():
    """Los provinciales no están en MESES_CORTE_CUPON: no se inventa un veto."""
    valido, _ = fif.evaluate_bond_filters(
        "BA37D", 61.2, None, ahora=pd.Timestamp("2027-01-05")
    )

    assert valido is True


# ---------- Modo degradado (sin histórico) ----------


def test_sin_historico_usa_el_tope_de_riesgo_y_lo_deja_asentado():
    valido, detalle = fif.evaluate_bond_filters(
        "AL30", 100.0, None, ahora=pd.Timestamp("2027-03-05")
    )

    assert valido is True
    assert detalle["datos_limitados"] is True
    assert detalle["pct_riesgo"] == pytest.approx(config.STOP_LOSS_MAX_PCT * 100)
    assert detalle["stop_loss"] == pytest.approx(97.0)


def test_el_take_profit_respeta_el_ratio_de_config():
    _, detalle = fif.evaluate_bond_filters(
        "AL30", 100.0, None, ahora=pd.Timestamp("2027-03-05")
    )

    riesgo = detalle["precio_entrada"] - detalle["stop_loss"]
    beneficio = detalle["take_profit"] - detalle["precio_entrada"]

    assert beneficio == pytest.approx(riesgo * config.TAKE_PROFIT_RATIO)


# ---------- Tendencia y ATR (con histórico) ----------


def test_vetea_si_cotiza_por_debajo_de_la_ema20():
    df = serie_bono(85.0, -0.20)
    precio = float(df["Close"].iloc[-1])

    valido, detalle = fif.evaluate_bond_filters(
        "GD30", precio, df, ahora=pd.Timestamp("2027-03-05")
    )

    assert valido is False
    assert "TENDENCIA" in detalle["motivo"].upper()


def test_en_tendencia_alcista_aprueba_con_stop_por_atr():
    df = serie_bono(65.0, 0.15)
    precio = float(df["Close"].iloc[-1])

    valido, detalle = fif.evaluate_bond_filters(
        "AL30", precio, df, ahora=pd.Timestamp("2027-03-05")
    )

    assert valido is True
    assert 0 < detalle["pct_riesgo"] <= config.STOP_LOSS_MAX_PCT * 100
    assert detalle["stop_loss"] < detalle["precio_entrada"] < detalle["take_profit"]


def test_el_riesgo_nunca_supera_el_tope_configurado():
    """Con un bono muy volátil, el stop por ATR se recorta al tope estricto."""
    idx = pd.date_range("2026-06-01", periods=60, freq="B")
    close = 70 + np.arange(60) * 0.1
    df = pd.DataFrame(
        {
            "Open": close,
            "High": close + 8.0,   # rango diario enorme => ATR grande
            "Low": close - 8.0,
            "Close": close,
            "Volume": np.full(60, 1_000_000.0),
        },
        index=idx,
    )
    precio = float(df["Close"].iloc[-1])

    valido, detalle = fif.evaluate_bond_filters(
        "AL30", precio, df, ahora=pd.Timestamp("2027-03-05")
    )

    assert valido is True
    assert detalle["pct_riesgo"] == pytest.approx(config.STOP_LOSS_MAX_PCT * 100)


def test_no_muta_el_dataframe_recibido():
    df = serie_bono(65.0, 0.15)
    columnas_antes = list(df.columns)

    fif.evaluate_bond_filters("AL30", 70.0, df, ahora=pd.Timestamp("2027-03-05"))

    assert list(df.columns) == columnas_antes


# ---------- Spread bid/ask ----------


def test_spread_angosto_pasa():
    ok, detalle = fif.check_spread_bid_ask(72.40, 72.60, 72.50)

    assert ok is True
    assert detalle["spread"] < config.SPREAD_BID_ASK_MAX


def test_spread_ancho_vetea():
    ok, detalle = fif.check_spread_bid_ask(71.00, 74.00, 72.50)

    assert ok is False
    assert "SPREAD" in detalle["motivo"].upper()


def test_sin_cotizacion_vetea_sin_dividir_por_cero():
    ok, detalle = fif.check_spread_bid_ask(0, 0, 0)

    assert ok is False
    assert detalle["spread"] is None
