"""
Tests de `app/technical_filters.py`.

Todo offline y determinístico: los DataFrames se construyen a mano para poder
verificar el ATR y las EMAs contra valores calculados aparte, y para ejercitar
los caminos de veto sin depender de cómo esté el mercado hoy.
"""
import numpy as np
import pandas as pd
import pytest

from app import config
from app import technical_filters as tf


def serie_ohlc(cierres: list[float]) -> pd.DataFrame:
    """DataFrame OHLCV mínimo, con rango diario fijo de 2 (High = Close+1, Low = Close-1)."""
    idx = pd.date_range("2026-01-01", periods=len(cierres), freq="B")
    close = np.array(cierres, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(len(cierres), 1_000_000.0),
        },
        index=idx,
    )


# ---------- Tarea 3.1: ATR ----------


def test_atr_de_una_serie_plana_es_el_rango_diario():
    """Con precio constante, el True Range es siempre High-Low = 2."""
    df = serie_ohlc([100.0] * 30)

    atr = tf.calculate_atr(df, period=14)

    assert atr.iloc[-1] == pytest.approx(2.0)


def test_atr_incorpora_el_gap_contra_el_cierre_previo():
    """Un salto de precio agranda el True Range por encima del rango intradiario."""
    plana = tf.calculate_atr(serie_ohlc([100.0] * 30), period=14).iloc[-1]
    con_gap = tf.calculate_atr(serie_ohlc([100.0] * 29 + [120.0]), period=14).iloc[-1]

    assert con_gap > plana


def test_atr_usa_el_periodo_de_config_por_defecto():
    df = serie_ohlc([100.0] * 40)

    por_defecto = tf.calculate_atr(df)
    explicito = tf.calculate_atr(df, period=config.ATR_PERIODO)

    assert por_defecto.iloc[-1] == pytest.approx(explicito.iloc[-1])


def test_atr_no_es_negativo_ni_nan_al_final():
    df = serie_ohlc(list(np.linspace(50, 80, 40)))

    atr = tf.calculate_atr(df)

    assert atr.iloc[-1] > 0
    assert not np.isnan(atr.iloc[-1])


# ---------- Tarea 3.1: EMAs ----------


def test_ema_de_serie_constante_es_esa_constante():
    serie = pd.Series([100.0] * 50)

    assert tf.calculate_ema(serie, 20).iloc[-1] == pytest.approx(100.0)


def test_ema_corta_reacciona_mas_rapido_que_la_larga():
    """En tendencia alcista, EMA20 tiene que quedar por encima de EMA50."""
    df = serie_ohlc(list(np.linspace(50, 100, 60)))

    con_emas = tf.agregar_emas(df)

    assert con_emas["EMA20"].iloc[-1] > con_emas["EMA50"].iloc[-1]


def test_agregar_emas_no_muta_el_dataframe_original():
    """Importa: `market_data.get_history` cachea sus DataFrames."""
    df = serie_ohlc([100.0] * 60)
    columnas_antes = list(df.columns)

    tf.agregar_emas(df)

    assert list(df.columns) == columnas_antes


# ---------- Tarea 3.2: los 7 filtros ----------


def test_siempre_devuelve_motivo_cuando_vetea(monkeypatch):
    """Requisito explícito: nunca `(False, {})` como en el manual original."""
    monkeypatch.setattr(
        tf, "get_history", lambda ticker, period="60d": serie_ohlc([100.0] * 10)
    )

    valido, detalle = tf.evaluate_7_filters("AAPL")

    assert valido is False
    assert detalle.get("motivo"), "un veto sin motivo pierde la trazabilidad de la decisión"


def test_datos_insuficientes_vetea_con_motivo(monkeypatch):
    monkeypatch.setattr(
        tf, "get_history", lambda ticker, period="60d": serie_ohlc([100.0] * 10)
    )

    _, detalle = tf.evaluate_7_filters("AAPL")

    assert "dato" in detalle["motivo"].lower() or "insuficiente" in detalle["motivo"].lower()


def test_error_de_market_data_se_traduce_a_veto_no_a_excepcion(monkeypatch):
    def explota(ticker, period="60d"):
        raise tf.MarketDataError(f"Sin datos de mercado para '{ticker}'")

    monkeypatch.setattr(tf, "get_history", explota)

    valido, detalle = tf.evaluate_7_filters("XXXX123")

    assert valido is False
    assert detalle.get("motivo")
