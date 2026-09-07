"""
Señal de entrada por RSI de sobreventa (Tarea 3.7).

Fuente de señal **alternativa** a los 7 filtros de `technical_filters`,
deliberadamente mucho más simple: si el RSI(14) cae por debajo de 30, el papel
está sobrevendido y se sugiere la compra.

No reemplaza nada. Las dos fuentes conviven en `/senales`, cada candidato
marcado con su `origen`, justamente para poder comparar en el simulador cuál
rinde mejor con plata de papel antes de quedarse con una.

> [!note] Por qué no se usa `pandas-ta`
> La Tarea 3.7 pide agregar `pandas-ta` a `requirements.txt`. No se puede: esa
> librería arrastra `numba`, que hoy no soporta la versión de Python de este
> entorno (3.14) — el `pip install` falla al compilar. El RSI se calcula acá con
> pandas puro, que además es lo que ya hace el repo con el ATR y las EMAs en
> `technical_filters.py`: cero dependencias nuevas por una fórmula de 6 líneas.

El stop-loss y el take-profit salen del mismo criterio que los 7 filtros (ATR ×
`ATR_MULTIPLICADOR`, recortado a `STOP_LOSS_MAX_PCT`, R/B `TAKE_PROFIT_RATIO`):
cambia el *disparador* de la señal, no la gestión del riesgo.

Como todo lo que toca la red, ninguna función de acá propaga una excepción: se
devuelve `(False, {"motivo": ...})`, igual que `technical_filters`.
"""
import logging
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from . import config
from . import technical_filters
from .market_data import MarketDataError, get_history

logger = logging.getLogger(__name__)

# El RSI de N períodos necesita N+1 cierres para el primer valor, y bastantes
# más para que la media de Wilder se estabilice. Se pide el mismo mínimo que los
# 7 filtros para no tener dos criterios de "datos suficientes".
RUEDAS_MINIMAS = technical_filters.RUEDAS_MINIMAS

ORIGEN = "RSI"


# ---------- Cálculo ----------


def calculate_rsi(serie: pd.Series, period: Optional[int] = None) -> pd.Series:
    """
    Relative Strength Index con suavizado de Wilder.

    Wilder (media exponencial con alfa = 1/período), que es el RSI clásico y el
    que usa `pandas-ta` por defecto — no la media simple. Con media simple los
    valores difieren lo suficiente como para cruzar el umbral de 30 en ruedas
    distintas, así que la elección no es cosmética.

    Args:
        serie: precios de cierre.
        period: períodos del RSI. Si es None usa `config.RSI_PERIODO`.

    Returns:
        Serie de RSI (0-100) alineada al índice de `serie`. Las primeras
        `period` posiciones son NaN.

    Raises:
        ValueError: si el período no es un entero positivo.
    """
    periodo = config.RSI_PERIODO if period is None else int(period)
    if periodo <= 0:
        raise ValueError(f"El período del RSI tiene que ser un entero positivo, llegó {period!r}.")

    delta = serie.diff()
    subas = delta.clip(lower=0)
    bajas = -delta.clip(upper=0)

    media_subas = subas.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()
    media_bajas = bajas.ewm(alpha=1 / periodo, adjust=False, min_periods=periodo).mean()

    rs = media_subas / media_bajas
    rsi = 100 - (100 / (1 + rs))

    # Sin ninguna baja en la ventana, `rs` es infinito (o NaN si tampoco hubo
    # subas). El RSI de un papel que solo subió es 100, no NaN.
    rsi = rsi.where(media_bajas != 0, 100.0)
    return rsi.where(~((media_bajas == 0) & (media_subas == 0)), 50.0)


# ---------- Filtro de liquidez ----------


def chequear_liquidez(
    bid: Optional[float] = None, ask: Optional[float] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Descarta el papel si el spread bid/ask supera `config.LIQUIDEZ_SPREAD_MAX`.

    **Hoy es NO BLOQUEANTE, a propósito.** No hay de dónde sacar el libro de
    órdenes del CEDEAR en BYMA: `yfinance` da la acción del subyacente en EE.UU.
    (ver el encabezado de `market_data`). Sin bid/ask reales, la función devuelve
    `True` con `disponible=False` — la alternativa sería inventar un spread o
    vetar todo, y las dos son peores que decir "no sé".

    Cuando `IOLClient` (Fase 8) traiga bid/ask de verdad, se le pasan acá y el
    chequeo pasa a bloquear solo. La lógica ya está escrita y probada.

    Args:
        bid: mejor punta compradora. None si no hay dato.
        ask: mejor punta vendedora. None si no hay dato.

    Returns:
        `(pasa, detalle)`. `detalle` trae `spread`, `disponible` y, cuando no
        pasa, `motivo`.
    """
    if bid is None or ask is None:
        return True, {
            "spread": None,
            "disponible": False,
            "nota": (
                "Spread no verificado: falta cotización real de BYMA "
                "(requiere IOLClient, Fase 8). Chequeo no bloqueante."
            ),
        }

    bid, ask = float(bid), float(ask)
    if bid <= 0 or ask <= 0 or ask < bid:
        return True, {
            "spread": None,
            "disponible": False,
            "nota": f"Puntas inconsistentes (bid={bid}, ask={ask}): no se evalúa el spread.",
        }

    spread = (ask - bid) / ask
    if spread > config.LIQUIDEZ_SPREAD_MAX:
        return False, {
            "spread": round(spread, 5),
            "disponible": True,
            "motivo": (
                f"VETO LIQUIDEZ: spread bid/ask {spread * 100:.2f}% supera el máximo "
                f"de {config.LIQUIDEZ_SPREAD_MAX * 100:.1f}%."
            ),
        }

    return True, {"spread": round(spread, 5), "disponible": True}


# ---------- Señal ----------


def evaluar_rsi(
    ticker: str, bid: Optional[float] = None, ask: Optional[float] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Señal de compra si el ticker está sobrevendido según el RSI.

    Args:
        ticker: símbolo de Yahoo Finance.
        bid / ask: puntas reales, si alguna vez las hay (Fase 8).

    Returns:
        `(valido, detalle)`. Con `valido=False`, `detalle["motivo"]` siempre
        explica por qué. Con `valido=True`, `detalle` trae los mismos campos que
        `evaluate_7_filters` (`precio_entrada`, `stop_loss`, `take_profit`,
        `pct_riesgo`) más `rsi` y `origen`.
    """
    simbolo = ticker.strip().upper()

    # Mismo período que los 7 filtros a propósito: así las dos fuentes comparten
    # la entrada de cache de `market_data` y el escaneo no duplica llamadas.
    try:
        df = get_history(simbolo, period=technical_filters.PERIODO_HISTORICO)
    except MarketDataError as exc:
        return False, {"ticker": simbolo, "motivo": f"VETO DATOS: {exc}"}

    if len(df) < RUEDAS_MINIMAS:
        return False, {
            "ticker": simbolo,
            "motivo": (
                f"VETO DATOS: solo {len(df)} ruedas de {simbolo} "
                f"(se necesitan {RUEDAS_MINIMAS})."
            ),
        }

    rsi = calculate_rsi(df["Close"]).iloc[-1]
    if pd.isna(rsi):
        return False, {
            "ticker": simbolo,
            "motivo": f"VETO DATOS: RSI({config.RSI_PERIODO}) no calculable para {simbolo}.",
        }
    rsi = float(rsi)

    if rsi >= config.RSI_SOBREVENTA:
        return False, {
            "ticker": simbolo,
            "rsi": round(rsi, 2),
            "motivo": (
                f"SIN SEÑAL RSI: {simbolo} en {rsi:.2f}, no está sobrevendido "
                f"(umbral {config.RSI_SOBREVENTA:.0f})."
            ),
        }

    liquidez_ok, liquidez = chequear_liquidez(bid, ask)
    if not liquidez_ok:
        return False, {"ticker": simbolo, "rsi": round(rsi, 2), "motivo": liquidez["motivo"]}

    precio_actual = float(df["Close"].iloc[-1])
    if precio_actual <= 0:
        return False, {
            "ticker": simbolo,
            "motivo": f"VETO DATOS: último cierre inválido para {simbolo} ({precio_actual}).",
        }

    # Mismo criterio de riesgo que los 7 filtros: cambia el disparador de la
    # señal, no la gestión del riesgo.
    atr = technical_filters.calculate_atr(df).iloc[-1]
    if pd.isna(atr) or float(atr) <= 0:
        return False, {
            "ticker": simbolo,
            "motivo": (
                f"VETO DATOS: ATR({config.ATR_PERIODO}) no calculable para {simbolo} "
                f"(valor {atr})."
            ),
        }
    atr = float(atr)

    riesgo = technical_filters.calcular_stop_y_objetivo(precio_actual, atr)

    return True, {
        "ticker": simbolo,
        "origen": ORIGEN,
        "precio_entrada": round(precio_actual, 2),
        "stop_loss": round(riesgo["stop_loss"], 2),
        "take_profit": round(riesgo["take_profit"], 2),
        "pct_riesgo": round(riesgo["pct_riesgo"] * 100, 2),
        "rsi": round(rsi, 2),
        "atr": round(atr, 4),
        "ratio_riesgo_beneficio": config.TAKE_PROFIT_RATIO,
        "stop_recortado_por_tolerancia": riesgo["stop_recortado"],
        "spread": liquidez.get("spread"),
        "spread_verificado": liquidez.get("disponible", False),
    }
