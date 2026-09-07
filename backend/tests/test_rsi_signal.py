"""
Tests de la señal alternativa por RSI (Tarea 3.7).

Todo offline: los históricos se arman a mano y `get_history` está mockeado.
Lo que importa verificar acá:

* que el RSI use suavizado de Wilder (con media simple los valores cruzan el
  umbral de 30 en ruedas distintas — la elección no es cosmética),
* que el chequeo de liquidez sea **no bloqueante** mientras no haya bid/ask
  reales, y bloqueante en cuanto los haya,
* que las dos fuentes de señal convivan en `/senales` sin pisarse.
"""
import numpy as np
import pandas as pd
import pytest

from app import config, rsi_signal, signals
from app.market_data import MarketDataError


# ---------- Históricos sintéticos ----------


def _df(cierres, ruedas_extra=60):
    """DataFrame OHLCV con `ruedas_extra` ruedas planas antes de `cierres`.

    Las ruedas planas dan de comer al ATR y a la media de Wilder sin mover el
    RSI hacia ningún lado; la señal la define la cola.
    """
    close = np.array([100.0] * ruedas_extra + list(cierres), dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(len(close), 1_000_000),
        },
        index=pd.date_range("2026-01-01", periods=len(close), freq="D"),
    )


def _caida_fuerte(ruedas=20, paso=0.97):
    """Cola de caídas consecutivas: lleva el RSI bien abajo de 30."""
    precio = 100.0
    salida = []
    for _ in range(ruedas):
        precio *= paso
        salida.append(precio)
    return salida


def _suba_fuerte(ruedas=20, paso=1.03):
    precio = 100.0
    salida = []
    for _ in range(ruedas):
        precio *= paso
        salida.append(precio)
    return salida


# ---------- calculate_rsi ----------


def test_una_racha_de_subas_da_rsi_100():
    """Sin ninguna baja en la ventana no hay división por cero: el RSI es 100."""
    serie = pd.Series(_suba_fuerte(40), dtype=float)

    rsi = rsi_signal.calculate_rsi(serie).iloc[-1]

    assert rsi == pytest.approx(100.0)


def test_una_racha_de_bajas_da_rsi_cercano_a_cero():
    serie = pd.Series(_caida_fuerte(40), dtype=float)

    rsi = rsi_signal.calculate_rsi(serie).iloc[-1]

    assert rsi < 5.0


def test_un_precio_plano_deja_el_rsi_neutro():
    """Sin subas ni bajas el RSI es 0/0: se define en 50, no en NaN."""
    serie = pd.Series([100.0] * 40, dtype=float)

    rsi = rsi_signal.calculate_rsi(serie).iloc[-1]

    assert rsi == pytest.approx(50.0)


def test_las_primeras_ruedas_son_nan():
    serie = pd.Series(np.linspace(100, 120, 30), dtype=float)

    rsi = rsi_signal.calculate_rsi(serie, period=14)

    assert rsi.iloc[:14].isna().all()
    assert not pd.isna(rsi.iloc[14])


def test_wilder_no_es_lo_mismo_que_media_simple():
    """Fija la elección de suavizado: si alguien la cambia, este test lo dice."""
    # Subas y bajas mezcladas: con una caída de ritmo constante los dos métodos
    # dan casi 0 y la diferencia no se vería.
    rng = np.random.default_rng(42)
    serie = pd.Series(100 + np.cumsum(rng.normal(0, 1.5, 60)), dtype=float)
    periodo = 14

    delta = serie.diff()
    subas, bajas = delta.clip(lower=0), -delta.clip(upper=0)
    simple = subas.rolling(periodo).mean() / bajas.rolling(periodo).mean()
    rsi_simple = 100 - (100 / (1 + simple))

    wilder = rsi_signal.calculate_rsi(serie, period=periodo)

    assert wilder.iloc[-1] != pytest.approx(rsi_simple.iloc[-1])


def test_periodo_invalido_levanta_error():
    with pytest.raises(ValueError):
        rsi_signal.calculate_rsi(pd.Series([1.0, 2.0]), period=0)


# ---------- chequear_liquidez ----------


def test_sin_puntas_el_chequeo_no_bloquea():
    """Mientras no haya cotización real de BYMA, no se puede vetar por spread."""
    pasa, detalle = rsi_signal.chequear_liquidez(None, None)

    assert pasa is True
    assert detalle["disponible"] is False
    assert detalle["spread"] is None


def test_un_spread_chico_pasa():
    pasa, detalle = rsi_signal.chequear_liquidez(bid=99.5, ask=100.0)

    assert pasa is True
    assert detalle["disponible"] is True
    assert detalle["spread"] == pytest.approx(0.005, abs=1e-4)


def test_un_spread_grande_veta():
    pasa, detalle = rsi_signal.chequear_liquidez(bid=97.0, ask=100.0)  # 3%

    assert pasa is False
    assert "VETO LIQUIDEZ" in detalle["motivo"]


def test_el_umbral_de_spread_sale_de_config():
    justo_abajo = 100.0 * (1 - config.LIQUIDEZ_SPREAD_MAX)

    pasa, _ = rsi_signal.chequear_liquidez(bid=justo_abajo, ask=100.0)

    assert pasa is True


def test_puntas_inconsistentes_no_bloquean():
    """Un ask menor al bid es dato roto, no falta de liquidez."""
    pasa, detalle = rsi_signal.chequear_liquidez(bid=100.0, ask=95.0)

    assert pasa is True
    assert detalle["disponible"] is False


# ---------- evaluar_rsi ----------


@pytest.fixture
def historico(monkeypatch):
    """Inyecta el histórico que devuelve `get_history` dentro de rsi_signal."""

    def _set(df):
        monkeypatch.setattr(rsi_signal, "get_history", lambda ticker, period=None: df)

    return _set


def test_sobreventa_dispara_la_senal(historico):
    historico(_df(_caida_fuerte()))

    valido, detalle = rsi_signal.evaluar_rsi("KO")

    assert valido is True
    assert detalle["origen"] == "RSI"
    assert detalle["rsi"] < config.RSI_SOBREVENTA
    assert detalle["precio_entrada"] > 0
    assert detalle["stop_loss"] < detalle["precio_entrada"]
    assert detalle["take_profit"] > detalle["precio_entrada"]


def test_sin_sobreventa_no_hay_senal_pero_si_motivo(historico):
    historico(_df(_suba_fuerte()))

    valido, detalle = rsi_signal.evaluar_rsi("KO")

    assert valido is False
    assert "SIN SEÑAL RSI" in detalle["motivo"]
    assert detalle["rsi"] >= config.RSI_SOBREVENTA


def test_el_riesgo_respeta_el_tope_de_config(historico):
    """El stop por ATR nunca puede quedar más lejos que STOP_LOSS_MAX_PCT."""
    historico(_df(_caida_fuerte()))

    _, detalle = rsi_signal.evaluar_rsi("KO")

    assert detalle["pct_riesgo"] <= config.STOP_LOSS_MAX_PCT * 100 + 1e-9


def test_el_ratio_riesgo_beneficio_es_el_de_config(historico):
    historico(_df(_caida_fuerte()))

    _, d = rsi_signal.evaluar_rsi("KO")

    riesgo = d["precio_entrada"] - d["stop_loss"]
    beneficio = d["take_profit"] - d["precio_entrada"]
    assert beneficio / riesgo == pytest.approx(config.TAKE_PROFIT_RATIO, abs=0.01)


def test_pocas_ruedas_se_descartan_con_motivo(historico):
    historico(_df(_caida_fuerte(5), ruedas_extra=10))

    valido, detalle = rsi_signal.evaluar_rsi("KO")

    assert valido is False
    assert "VETO DATOS" in detalle["motivo"]


def test_un_error_de_red_no_se_propaga(monkeypatch):
    def revienta(ticker, period=None):
        raise MarketDataError("Yahoo no responde")

    monkeypatch.setattr(rsi_signal, "get_history", revienta)

    valido, detalle = rsi_signal.evaluar_rsi("KO")

    assert valido is False
    assert "Yahoo no responde" in detalle["motivo"]


def test_un_spread_grande_veta_la_senal_aunque_haya_sobreventa(historico):
    historico(_df(_caida_fuerte()))

    valido, detalle = rsi_signal.evaluar_rsi("KO", bid=97.0, ask=100.0)

    assert valido is False
    assert "VETO LIQUIDEZ" in detalle["motivo"]


def test_sin_puntas_la_senal_sale_marcada_como_no_verificada(historico):
    historico(_df(_caida_fuerte()))

    _, detalle = rsi_signal.evaluar_rsi("KO")

    assert detalle["spread_verificado"] is False
    assert detalle["spread"] is None


# ---------- Convivencia de las dos fuentes en /senales ----------


VIX_NORMAL = {"vix_actual": 15.0, "veto": False, "motivo": "VIX normal (15.0)"}
REGIMEN_SANO = {"tipo": "CEDEAR", "aplica": True, "disponible": True, "motivo": "Mercado OK"}

DETALLE_7F = {
    "ticker": "NVDA",
    "precio_entrada": 100.0,
    "stop_loss": 97.0,
    "take_profit": 106.0,
    "pct_riesgo": 3.0,
    "breakout_level": 99.5,
}
DETALLE_RSI = {
    "ticker": "NVDA",
    "origen": "RSI",
    "precio_entrada": 100.0,
    "stop_loss": 97.0,
    "take_profit": 106.0,
    "pct_riesgo": 3.0,
    "rsi": 24.5,
}


def _escaneo(monkeypatch, pasa_7f, pasa_rsi):
    monkeypatch.setattr(signals.risk_filters, "estado_vix", lambda: VIX_NORMAL)
    monkeypatch.setattr(
        signals.entry_validator,
        "chequear_regimen_mercado",
        lambda tipo, validador=None: (True, REGIMEN_SANO),
    )
    monkeypatch.setattr(
        signals.risk_filters, "get_finbert_sentiment", lambda t: (True, 0.2, "OK")
    )
    monkeypatch.setattr(
        signals.smart_money,
        "contexto_smart_money",
        lambda t: {"rvol": 1.0, "es_acumulacion": False, "insiders_detectados": False,
                   "insiders_detalle": ""},
    )
    monkeypatch.setattr(
        signals.technical_filters,
        "evaluate_7_filters",
        lambda t: (True, dict(DETALLE_7F))
        if pasa_7f
        else (False, {"motivo": "VETO TÉCNICO: estructura no alcista"}),
    )
    monkeypatch.setattr(
        signals.rsi_signal,
        "evaluar_rsi",
        lambda t, bid=None, ask=None: (True, dict(DETALLE_RSI))
        if pasa_rsi
        else (False, {"rsi": 55.0, "motivo": "SIN SEÑAL RSI: en 55.00 (umbral 30)."}),
    )
    return signals.escanear_senales(["NVDA"])


def test_solo_los_7_filtros_marca_el_origen(monkeypatch):
    r = _escaneo(monkeypatch, pasa_7f=True, pasa_rsi=False)

    assert r["candidatos"][0]["origen"] == "7_FILTROS"
    assert r["candidatos"][0]["rsi"] == 55.0, "el RSI viaja igual, como contexto"


def test_solo_rsi_tambien_genera_candidato(monkeypatch):
    r = _escaneo(monkeypatch, pasa_7f=False, pasa_rsi=True)

    assert len(r["candidatos"]) == 1
    assert r["candidatos"][0]["origen"] == "RSI"
    assert r["candidatos"][0]["rsi"] == 24.5
    assert r["descartados"] == []


def test_cuando_coinciden_las_dos_el_origen_es_ambos(monkeypatch):
    r = _escaneo(monkeypatch, pasa_7f=True, pasa_rsi=True)

    assert r["candidatos"][0]["origen"] == "AMBOS"
    assert r["candidatos"][0]["breakout_level"] == 99.5, "manda el detalle de los 7 filtros"


def test_si_ninguna_pasa_se_descarta_con_los_dos_motivos(monkeypatch):
    r = _escaneo(monkeypatch, pasa_7f=False, pasa_rsi=False)

    assert r["candidatos"] == []
    motivo = r["descartados"][0]["motivo"]
    assert "VETO TÉCNICO" in motivo
    assert "SIN SEÑAL RSI" in motivo


def test_la_respuesta_avisa_que_los_precios_no_son_operables(monkeypatch):
    """Tarea 2.1: el precio de yfinance es el subyacente en USD, no el CEDEAR."""
    r = _escaneo(monkeypatch, pasa_7f=True, pasa_rsi=False)

    assert "no operable" in r["advertencia_precios"]
