"""
Precios e histórico OHLCV vía Yahoo Finance (yfinance).

Regla del repo (CLAUDE.md): los módulos que hablan con internet nunca rompen el
proceso. Todo lo que pueda fallar acá —red caída, ticker inexistente, Yahoo
devolviendo vacío o rate-limiteando— se envuelve en `MarketDataError`, con un
mensaje en español listo para mostrar. Nunca se propaga una excepción cruda de
yfinance/requests hacia el endpoint.

Referencia de spec: Manual_Maestro_Bot_Inversion_IA_Completo, sección 6
(`yf.Ticker(ticker).history(period="60d")` es la base del cálculo de ATR y de
los 7 filtros técnicos).

⚠ ESTE PRECIO NO ES EL DEL CEDEAR (Tarea 2.1 del plan)
-------------------------------------------------------
`yf.Ticker("AAPL")` devuelve el precio de la **acción en EE.UU., en dólares**.
El CEDEAR de AAPL en BYMA cotiza **en pesos**, con un ratio de conversión y el
dólar CCL de por medio: son números completamente distintos.

Sirve para lo que este módulo existe —el **patrón técnico** (RSI, EMAs, ATR,
fuerza relativa, forma del gráfico)— porque el CEDEAR sigue de cerca el
movimiento porcentual del subyacente. **No sirve** para:

* calcular cuántos papeles comprar,
* mostrar un precio de entrada como si fuera operable,
* validar un spread bid/ask.

El precio real en pesos tiene que salir de la cotización de IOL (`IOLClient`,
Fase 8). Hasta entonces, todo lo que muestre este precio va marcado con
`ADVERTENCIA_PRECIO_REFERENCIA`.

Cache: `get_history` cachea en memoria por (ticker, period) durante
`TTL_CACHE_SEGUNDOS`. El escaneo de señales pide el mismo histórico muchas
veces seguidas —sobre todo el del benchmark SPY, una vez por cada ticker del
universo— y sin cache serían decenas de llamadas idénticas a Yahoo.
"""
import logging
import time
from typing import Dict, Tuple

import pandas as pd
import yfinance as yf

from . import config  # noqa: F401  (SUFIJO_YF_BYMA / TICKERS_BYMA, para quien los necesite)

# yfinance loguea por su cuenta cosas tipo "HTTP Error 404 ... symbol may be
# delisted" cuando el ticker no existe. Ese caso ya lo reportamos nosotros como
# `MarketDataError` con un mensaje en español, así que se silencia su logger
# para no ensuciar la salida del backend con ruido que parece un stacktrace.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


# ---------- Excepción propia ----------


class MarketDataError(Exception):
    """Error controlado al pedir datos de mercado (ticker inválido, sin datos o red caída)."""


# ---------- Advertencia de precio (Tarea 2.1) ----------

# Texto único: lo usan `/market/precio/{ticker}`, `/senales` y el frontend. Si
# cambia la redacción, cambia en un solo lugar.
ADVERTENCIA_PRECIO_REFERENCIA = (
    "Referencia técnica, no operable: es el precio de la acción subyacente en "
    "EE.UU. (USD), no el del CEDEAR en BYMA (ARS). Sirve para el patrón técnico, "
    "no para calcular cantidades ni el precio de entrada real."
)


# ---------- Cache en memoria con TTL ----------

# Cuánto vale un histórico antes de volver a pedirlo. 5 minutos: suficiente para
# que un escaneo completo del universo use una sola descarga por ticker, y corto
# como para no operar con velas viejas.
TTL_CACHE_SEGUNDOS = 300

# (ticker, period) -> (timestamp_de_descarga, DataFrame)
_cache_historial: Dict[Tuple[str, str], Tuple[float, pd.DataFrame]] = {}

# Período por defecto: 60 ruedas, lo que pide la spec para EMA50 + fuerza relativa.
PERIODO_DEFAULT = "60d"


def limpiar_cache() -> None:
    """Vacía la cache de históricos. Útil en tests o para forzar una relectura."""
    _cache_historial.clear()


def _normalizar_ticker(ticker: str) -> str:
    """Valida y normaliza el símbolo. Lanza `MarketDataError` si viene vacío."""
    if not isinstance(ticker, str) or not ticker.strip():
        raise MarketDataError("Ticker vacío o inválido: hay que pasar un símbolo, por ejemplo 'AAPL'.")
    return ticker.strip().upper()


# ---------- API pública ----------


def get_history(ticker: str, period: str = PERIODO_DEFAULT, usar_cache: bool = True) -> pd.DataFrame:
    """
    Devuelve el histórico OHLCV del ticker como DataFrame de pandas.

    Columnas tal como las devuelve yfinance: Open, High, Low, Close, Volume,
    Dividends y Stock Splits. El índice es la fecha (DatetimeIndex con tz).

    Args:
        ticker: símbolo de Yahoo Finance. Para instrumentos locales hay que
            agregarle `config.SUFIJO_YF_BYMA` (ej. "AL30.BA").
        period: ventana que acepta yfinance ("5d", "60d", "1y", ...).
        usar_cache: si es False ignora la cache y vuelve a pedirle a Yahoo.

    Returns:
        DataFrame OHLCV (una copia propia: el llamador puede agregarle columnas
        calculadas —EMA20, ATR— sin ensuciar lo cacheado).

    Raises:
        MarketDataError: ticker inexistente, sin datos en ese período, o fallo
            de red / de yfinance.
    """
    simbolo = _normalizar_ticker(ticker)
    clave = (simbolo, period)

    if usar_cache:
        cacheado = _cache_historial.get(clave)
        if cacheado is not None:
            momento, df_cacheado = cacheado
            if (time.time() - momento) < TTL_CACHE_SEGUNDOS:
                return df_cacheado.copy()

    try:
        df = yf.Ticker(simbolo).history(period=period)
    except MarketDataError:
        raise
    except Exception as e:  # red, parseo, rate limit de Yahoo: todo cae acá
        raise MarketDataError(
            f"No se pudo obtener el histórico de '{simbolo}' (período {period}): {e}"
        ) from e

    if df is None or df.empty:
        raise MarketDataError(
            f"Sin datos de mercado para '{simbolo}' (período {period}). "
            "Verificá el ticker; si es un instrumento local acordate del sufijo "
            f"'{config.SUFIJO_YF_BYMA}'."
        )

    _cache_historial[clave] = (time.time(), df)
    return df.copy()


def get_last_price(ticker: str) -> float:
    """
    Devuelve el último precio de cierre disponible del ticker.

    Usa una ventana corta ("5d") para cubrir fines de semana y feriados, y pasa
    por la misma cache que `get_history`.

    OJO: es el precio del subyacente en USD, no el del CEDEAR en ARS. Ver
    `ADVERTENCIA_PRECIO_REFERENCIA` y el encabezado del módulo.

    Raises:
        MarketDataError: ticker inexistente, sin datos o fallo de red.
    """
    simbolo = _normalizar_ticker(ticker)
    df = get_history(simbolo, period="5d")

    if "Close" not in df.columns:
        raise MarketDataError(
            f"La respuesta de Yahoo para '{simbolo}' no trae columna 'Close': {list(df.columns)}"
        )

    serie_cierres = df["Close"].dropna()
    if serie_cierres.empty:
        raise MarketDataError(f"Sin precios de cierre válidos para '{simbolo}'.")

    try:
        return float(serie_cierres.iloc[-1])
    except (TypeError, ValueError) as e:
        raise MarketDataError(f"Precio de cierre ilegible para '{simbolo}': {e}") from e
