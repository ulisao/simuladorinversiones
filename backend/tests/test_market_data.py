"""
Tests de `app.market_data`.

Los que pegan a internet están marcados con `@pytest.mark.network` y se saltean
solos si yfinance no está instalado o si Yahoo no responde (sin conexión, rate
limit): la suite no se rompe por eso. Los tests de cache y de validación de
entrada son offline y corren siempre.

Correr desde `backend/`:
    ./venv/Scripts/python.exe -m pytest tests/test_market_data.py -v
    ./venv/Scripts/python.exe -m pytest tests/test_market_data.py -v -m "not network"
"""
import time

import pytest

yf = pytest.importorskip("yfinance", reason="yfinance no instalado")
pd = pytest.importorskip("pandas", reason="pandas no instalado")

from app.market_data import (  # noqa: E402
    TTL_CACHE_SEGUNDOS,
    MarketDataError,
    get_history,
    get_last_price,
    limpiar_cache,
    _cache_historial,
)

TICKER_REAL = "AAPL"
TICKER_INVALIDO = "XXXX123"

COLUMNAS_OHLCV = {"Open", "High", "Low", "Close", "Volume"}


@pytest.fixture(autouse=True)
def _cache_limpia():
    """Cada test arranca con la cache vacía."""
    limpiar_cache()
    yield
    limpiar_cache()


def _saltear_si_no_hay_red(e: MarketDataError):
    """Sin conexión / Yahoo caído no es un test fallado: se saltea."""
    pytest.skip(f"Sin acceso a Yahoo Finance: {e}")


# ---------- Tests con red ----------


@pytest.mark.network
def test_get_last_price_ticker_real():
    try:
        precio = get_last_price(TICKER_REAL)
    except MarketDataError as e:
        _saltear_si_no_hay_red(e)
    assert isinstance(precio, float)
    assert precio > 0


@pytest.mark.network
def test_get_history_ticker_real():
    try:
        df = get_history(TICKER_REAL)
    except MarketDataError as e:
        _saltear_si_no_hay_red(e)
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert COLUMNAS_OHLCV.issubset(set(df.columns))


@pytest.mark.network
def test_ticker_invalido_lanza_error_controlado():
    with pytest.raises(MarketDataError) as info:
        get_history(TICKER_INVALIDO)
    assert TICKER_INVALIDO in str(info.value)


@pytest.mark.network
def test_get_last_price_ticker_invalido_lanza_error_controlado():
    with pytest.raises(MarketDataError):
        get_last_price(TICKER_INVALIDO)


# ---------- Tests offline ----------


def test_ticker_vacio_lanza_error_controlado():
    with pytest.raises(MarketDataError):
        get_history("")
    with pytest.raises(MarketDataError):
        get_last_price("   ")


def test_cache_devuelve_lo_guardado_sin_pegarle_a_yahoo(monkeypatch):
    """Con la cache fresca no se llama a yfinance."""
    df_falso = pd.DataFrame(
        {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [100]}
    )
    _cache_historial[("FAKE", "60d")] = (time.time(), df_falso)

    def _explotar(*args, **kwargs):
        raise AssertionError("No debería llamar a yfinance: la cache estaba fresca")

    monkeypatch.setattr("app.market_data.yf.Ticker", _explotar)
    df = get_history("fake")  # se normaliza a "FAKE"
    assert df["Close"].iloc[-1] == 1.5


def test_cache_vencida_vuelve_a_pedir_los_datos(monkeypatch):
    """Pasado el TTL, la entrada vieja se descarta y se vuelve a descargar."""
    df_viejo = pd.DataFrame({"Close": [1.0]})
    df_nuevo = pd.DataFrame(
        {"Open": [9.0], "High": [9.0], "Low": [9.0], "Close": [9.0], "Volume": [1]}
    )
    _cache_historial[("FAKE", "60d")] = (time.time() - TTL_CACHE_SEGUNDOS - 1, df_viejo)

    class _TickerFalso:
        def __init__(self, simbolo):
            self.simbolo = simbolo

        def history(self, period="60d"):
            return df_nuevo

    monkeypatch.setattr("app.market_data.yf.Ticker", _TickerFalso)
    df = get_history("FAKE")
    assert df["Close"].iloc[-1] == 9.0


def test_dataframe_vacio_se_traduce_a_error_controlado(monkeypatch):
    class _TickerVacio:
        def __init__(self, simbolo):
            pass

        def history(self, period="60d"):
            return pd.DataFrame()

    monkeypatch.setattr("app.market_data.yf.Ticker", _TickerVacio)
    with pytest.raises(MarketDataError):
        get_history("LOQUESEA")


def test_excepcion_de_red_queda_envuelta_en_marketdataerror(monkeypatch):
    class _TickerQueExplota:
        def __init__(self, simbolo):
            pass

        def history(self, period="60d"):
            raise ConnectionError("conexión rechazada")

    monkeypatch.setattr("app.market_data.yf.Ticker", _TickerQueExplota)
    with pytest.raises(MarketDataError) as info:
        get_history("AAPL")
    assert "conexión rechazada" in str(info.value)


def test_el_llamador_no_puede_ensuciar_la_cache():
    """`get_history` devuelve una copia: agregarle columnas no toca lo cacheado."""
    df_falso = pd.DataFrame({"Close": [1.0, 2.0, 3.0]})
    _cache_historial[("FAKE", "60d")] = (time.time(), df_falso)

    df = get_history("FAKE")
    df["EMA20"] = df["Close"] * 2

    _, df_en_cache = _cache_historial[("FAKE", "60d")]
    assert "EMA20" not in df_en_cache.columns
