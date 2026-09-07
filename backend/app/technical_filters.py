"""
Filtros técnicos de validación (acciones y CEDEARs).

Dos capas:

1. **Piezas matemáticas** (`calculate_atr`, `calculate_ema`, `agregar_emas`):
   portadas del manual, sin efectos de red. Trabajan sobre un DataFrame OHLCV.
2. **`evaluate_7_filters(ticker)`**: el protocolo de 7 controles que decide si
   una compra queda autorizada, y con qué stop-loss y take-profit.

Referencia de spec: `Manual_Maestro_Bot_Inversion_IA_Completo.docx`, sección 6
(`technical_filters.py`).

Diferencias deliberadas contra el código del manual:

- **Nada hardcodeado.** El manual escribe `1.5`, `0.035`, `0.97`, `2.0` y `7`
  dentro de la función. Acá todo sale de `config` (documentado en
  `docs/parametros-riesgo.md`).
- **Siempre hay motivo.** El manual devuelve `False, {}` cuando faltan ruedas:
  un veto sin motivo se pierde en la respuesta del endpoint. Acá *todo* veto
  trae `detalle["motivo"]`.
- **Los históricos salen de `market_data.get_history`**, que cachea; el manual
  llama a `yf.Ticker(...).history()` una vez por ticker y otra por SPY, o sea
  el doble de llamadas a Yahoo por cada símbolo del universo.
- **`stock.calendar` se maneja en los dos formatos** (DataFrame en yfinance
  viejo, dict en las versiones nuevas), y si la fecha no se puede determinar
  **no se veta**: un dato faltante no puede inventar un veto.
"""
from typing import Any, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from . import config
from .market_data import MarketDataError, get_history


# ---------- Constantes estructurales ----------
# No son parámetros de riesgo (esos están en config.py): son requisitos del
# cálculo. La EMA50 necesita al menos 50 ruedas para no ser ruido, y la fuerza
# relativa del manual se mide contra el cierre de 30 ruedas atrás.

RUEDAS_MINIMAS = 50
RUEDAS_FUERZA_RELATIVA = 30

# Ventana del nivel de ruptura (`ta.highest(high[1], 20)` del spec del
# EntryValidator): máximo de los 20 máximos previos a la rueda actual.
RUEDAS_BREAKOUT = 20

# Ventana que se le pide a `market_data`: 60 ruedas, lo que usa el manual.
PERIODO_HISTORICO = "60d"

# Spans de las medias exponenciales que miran los filtros 2 y 3.
EMA_CORTA = 20
EMA_LARGA = 50


# ---------- Tarea 3.1: piezas matemáticas ----------


def calculate_atr(df: pd.DataFrame, period: Optional[int] = None) -> pd.Series:
    """
    Average True Range, portado del manual (sección 6).

    True Range de cada rueda = el mayor de:
      - high - low
      - |high - cierre_anterior|
      - |low  - cierre_anterior|

    y el ATR es la media móvil simple de ese True Range.

    Args:
        df: DataFrame OHLCV (necesita `High`, `Low`, `Close`).
        period: ruedas de la media móvil. Si es None usa `config.ATR_PERIODO`.

    Returns:
        Serie con el ATR alineada al índice de `df`. Las primeras
        `period - 1` posiciones son NaN (todavía no hay ventana completa).

    Raises:
        ValueError: si faltan columnas o el período no es un entero positivo.
    """
    periodo = config.ATR_PERIODO if period is None else int(period)
    if periodo <= 0:
        raise ValueError(f"El período del ATR tiene que ser un entero positivo, llegó {period!r}.")

    faltantes = [col for col in ("High", "Low", "Close") if col not in df.columns]
    if faltantes:
        raise ValueError(
            f"El DataFrame no tiene las columnas necesarias para el ATR: {faltantes}. "
            f"Columnas presentes: {list(df.columns)}."
        )

    high_low = df["High"] - df["Low"]
    high_close = np.abs(df["High"] - df["Close"].shift())
    low_close = np.abs(df["Low"] - df["Close"].shift())

    rangos = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = rangos.max(axis=1)  # equivale al np.max(ranges, axis=1) del manual

    return true_range.rolling(periodo).mean()


def calcular_stop_y_objetivo(precio_actual: float, atr: float) -> dict:
    """Stop-loss por ATR y take-profit con el ratio R/B, con el tope de config.

    Única implementación de la regla de riesgo por operación. La usan los tres
    generadores de señal (los 7 filtros, el RSI de la Tarea 3.7 y el consenso
    13F de la Tarea 5.4): cambia el disparador de cada señal, nunca la gestión
    del riesgo.

    Stop = precio − `ATR_MULTIPLICADOR` × ATR. Si eso deja el riesgo por encima
    de `STOP_LOSS_TOLERANCIA_PCT`, se recorta a `STOP_LOSS_MAX_PCT`.

    Returns:
        `{"stop_loss", "take_profit", "pct_riesgo", "stop_recortado"}`.
        `pct_riesgo` va en fracción (0.03), no en porcentaje.

    Raises:
        ValueError: si el precio o el ATR no son positivos.
    """
    precio_actual = float(precio_actual)
    atr = float(atr)
    if precio_actual <= 0:
        raise ValueError(f"El precio tiene que ser positivo, llegó {precio_actual!r}.")
    if atr <= 0:
        raise ValueError(f"El ATR tiene que ser positivo, llegó {atr!r}.")

    stop_loss = precio_actual - (config.ATR_MULTIPLICADOR * atr)
    pct_riesgo = (precio_actual - stop_loss) / precio_actual

    stop_recortado = pct_riesgo > config.STOP_LOSS_TOLERANCIA_PCT
    if stop_recortado:
        stop_loss = precio_actual * (1 - config.STOP_LOSS_MAX_PCT)
        pct_riesgo = config.STOP_LOSS_MAX_PCT

    return {
        "stop_loss": stop_loss,
        "take_profit": precio_actual + (precio_actual - stop_loss) * config.TAKE_PROFIT_RATIO,
        "pct_riesgo": pct_riesgo,
        "stop_recortado": stop_recortado,
    }


def calculate_ema(serie: pd.Series, span: int) -> pd.Series:
    """
    Media móvil exponencial de una serie de precios.

    Usa `adjust=False`, igual que el manual: cada valor pondera al anterior con
    alfa = 2 / (span + 1), que es la EMA clásica de análisis técnico (la que
    dibujan los gráficos de TradingView / IOL).

    Args:
        serie: serie de precios (normalmente `df["Close"]`).
        span: ventana de la EMA (20, 50, ...).

    Returns:
        Serie con la EMA, mismo índice que la entrada.

    Raises:
        ValueError: si `span` no es un entero positivo.
    """
    span = int(span)
    if span <= 0:
        raise ValueError(f"El span de la EMA tiene que ser un entero positivo, llegó {span!r}.")
    return serie.ewm(span=span, adjust=False).mean()


def agregar_emas(df: pd.DataFrame, spans: Sequence[int] = (EMA_CORTA, EMA_LARGA)) -> pd.DataFrame:
    """
    Devuelve una copia del DataFrame con una columna `EMA{span}` por cada span.

    **Trabaja sobre una copia a propósito**: `market_data.get_history` cachea
    sus DataFrames, y ensuciar el objeto cacheado con columnas calculadas se le
    filtraría al resto del escaneo.

    Args:
        df: DataFrame OHLCV (necesita `Close`).
        spans: ventanas a calcular. Por defecto (20, 50), las que miran los
            filtros de tendencia.

    Returns:
        Copia del DataFrame con las columnas `EMA20`, `EMA50`, ... agregadas.

    Raises:
        ValueError: si no hay columna `Close`.
    """
    if "Close" not in df.columns:
        raise ValueError(
            f"El DataFrame no tiene columna 'Close' para calcular las EMAs. "
            f"Columnas presentes: {list(df.columns)}."
        )

    resultado = df.copy()
    for span in spans:
        resultado[f"EMA{int(span)}"] = calculate_ema(resultado["Close"], span)
    return resultado


# ---------- Tarea 3.2: filtro 1 (earnings), auxiliares ----------


def _a_timestamp_naive(valor: Any) -> Optional[pd.Timestamp]:
    """Convierte cualquier fecha a `Timestamp` sin timezone, o None si no se puede."""
    if valor is None:
        return None
    try:
        fecha = pd.to_datetime(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isinstance(fecha, pd.Timestamp) or pd.isna(fecha):
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.tz_localize(None) if fecha.tz is None else fecha.tz_convert(None)
    return fecha.normalize()


def fecha_proximo_balance(calendario: Any) -> Optional[pd.Timestamp]:
    """
    Extrae la fecha del próximo balance de lo que devuelva `yf.Ticker().calendar`.

    yfinance cambió el formato entre versiones:
      - versiones viejas: DataFrame con la fecha en la primera celda
        (`cal.iloc[0, 0]`, que es lo que asume el manual);
      - versiones nuevas: `dict`, con `"Earnings Date"` apuntando a una lista de
        fechas.

    Se soportan los dos, más el caso de una fecha suelta. Si no se puede
    determinar nada, devuelve None — y el llamador **no vetea**: un dato que
    falta no puede inventar un veto.

    Returns:
        Timestamp sin timezone y normalizado a medianoche, o None.
    """
    if calendario is None:
        return None

    candidatas: list = []

    # Formato nuevo: dict {"Earnings Date": [date, ...], "Dividend Date": date, ...}
    if isinstance(calendario, dict):
        crudo = calendario.get("Earnings Date")
        if crudo is None:
            # Alguna versión intermedia usó otras claves: se busca cualquiera que
            # hable de earnings antes de rendirse.
            for clave, valor in calendario.items():
                texto = str(clave).lower()
                if "earnings" in texto and "date" in texto:
                    crudo = valor
                    break
        if crudo is None:
            return None
        if isinstance(crudo, (list, tuple, set, pd.Series, np.ndarray)):
            candidatas = list(crudo)
        else:
            candidatas = [crudo]

    # Formato viejo: DataFrame (el manual lee cal.iloc[0, 0])
    elif isinstance(calendario, pd.DataFrame):
        if calendario.empty:
            return None
        try:
            candidatas = [calendario.iloc[0, 0]]
        except (IndexError, KeyError):
            return None

    elif isinstance(calendario, pd.Series):
        if calendario.empty:
            return None
        candidatas = list(calendario.values)

    else:
        candidatas = [calendario]

    fechas = [f for f in (_a_timestamp_naive(c) for c in candidatas) if f is not None]
    if not fechas:
        return None

    # De haber varias, interesa la más próxima que todavía no pasó; si ya
    # pasaron todas, la última conocida (dará días negativos y no vetará).
    hoy = pd.Timestamp.now().normalize()
    futuras = [f for f in fechas if f >= hoy]
    return min(futuras) if futuras else max(fechas)


def dias_hasta_proximo_balance(ticker: str) -> Optional[int]:
    """
    Días que faltan para el próximo balance del ticker, o None si no se sabe.

    Es la única parte del módulo que le pega a yfinance directo: el calendario
    de earnings no es OHLCV y por eso no vive en `market_data`. Cualquier fallo
    (red, rate limit de Yahoo, formato inesperado) devuelve None, o sea "no se
    puede determinar" — nunca rompe ni vetea.
    """
    try:
        calendario = yf.Ticker(ticker).calendar
    except Exception:  # red, rate limit, parseo: nada de esto justifica un veto
        return None

    fecha = fecha_proximo_balance(calendario)
    if fecha is None:
        return None

    return int((fecha - pd.Timestamp.now().normalize()).days)


# ---------- Tarea 3.2: los 7 filtros ----------


def evaluate_7_filters(ticker: str) -> Tuple[bool, dict]:
    """
    Aplica el protocolo estricto de 7 capas antes de autorizar una compra.

    Controles, en orden:
      1. **Earnings** — veto si presenta balance dentro de
         `config.EARNINGS_DIAS_VETO` días.
      2. **Régimen de mercado** — veto si `config.TICKER_BENCHMARK` (SPY) cotiza
         por debajo de su EMA50.
      3. **Tendencia del activo** — veto si no se cumple precio > EMA20 > EMA50.
      4. **Fuerza relativa** — veto si el activo no le gana al benchmark en las
         últimas `RUEDAS_FUERZA_RELATIVA` ruedas.
      5. **ATR y stop-loss dinámico** — stop = precio − `ATR_MULTIPLICADOR` × ATR;
         si el riesgo pasa `STOP_LOSS_TOLERANCIA_PCT`, se recorta a
         `STOP_LOSS_MAX_PCT`.
      6. **Take-profit** — precio + (precio − stop) × `TAKE_PROFIT_RATIO`.
      7. **Datos suficientes** — veto si hay menos de `RUEDAS_MINIMAS` ruedas del
         activo o del benchmark. Se evalúa apenas se bajan los históricos,
         porque los controles 2 a 6 no tienen sentido sin esas ruedas.

    Args:
        ticker: símbolo de Yahoo Finance ("AAPL", "AL30.BA", ...).

    Returns:
        `(valido, detalle)`.

        - Con `valido=False`, `detalle["motivo"]` siempre explica el veto
          (nunca un dict vacío, a diferencia del manual).
        - Con `valido=True`, `detalle` trae `ticker`, `precio_entrada`,
          `stop_loss`, `take_profit` y `pct_riesgo` (en %, 2 decimales), más
          contexto: `atr`, `ema20`, `ema50`, retornos a 30 ruedas y si el stop
          se recortó por tolerancia.

    Nunca propaga excepciones: un `MarketDataError` se convierte en un veto con
    motivo, como pide CLAUDE.md para los módulos que hablan con internet.
    """
    simbolo = (ticker or "").strip().upper()
    if not simbolo:
        return False, {"motivo": "VETO DATOS: ticker vacío o inválido."}

    benchmark = config.TICKER_BENCHMARK

    # --- Filtro 1: calendario de balances (earnings) ---
    # Va primero porque no necesita histórico: si el balance es inminente, no
    # tiene sentido gastar dos descargas de Yahoo.
    dias_balance = dias_hasta_proximo_balance(simbolo)
    if dias_balance is not None and 0 <= dias_balance <= config.EARNINGS_DIAS_VETO:
        return False, {
            "ticker": simbolo,
            "motivo": f"VETO EARNINGS: presenta balance en {dias_balance} días.",
            "dias_hasta_balance": dias_balance,
        }

    # --- Históricos (con cache) ---
    try:
        df = get_history(simbolo, period=PERIODO_HISTORICO)
    except MarketDataError as e:
        return False, {"ticker": simbolo, "motivo": f"VETO DATOS: sin histórico de {simbolo}. {e}"}

    try:
        df_benchmark = get_history(benchmark, period=PERIODO_HISTORICO)
    except MarketDataError as e:
        return False, {
            "ticker": simbolo,
            "motivo": f"VETO DATOS: sin histórico del benchmark {benchmark}. {e}",
        }

    # --- Filtro 7: datos suficientes ---
    # El manual devuelve `False, {}` acá; nosotros siempre damos motivo.
    if len(df) < RUEDAS_MINIMAS or len(df_benchmark) < RUEDAS_MINIMAS:
        return False, {
            "ticker": simbolo,
            "motivo": (
                f"VETO DATOS: ruedas insuficientes para evaluar "
                f"({simbolo}: {len(df)}, {benchmark}: {len(df_benchmark)}; "
                f"se necesitan {RUEDAS_MINIMAS})."
            ),
            "ruedas_activo": len(df),
            "ruedas_benchmark": len(df_benchmark),
        }

    df = agregar_emas(df, spans=(EMA_CORTA, EMA_LARGA))
    df_benchmark = agregar_emas(df_benchmark, spans=(EMA_LARGA,))

    # --- Filtro 2: régimen de mercado (benchmark sobre su EMA50) ---
    cierre_benchmark = float(df_benchmark["Close"].iloc[-1])
    ema50_benchmark = float(df_benchmark[f"EMA{EMA_LARGA}"].iloc[-1])
    if cierre_benchmark < ema50_benchmark:
        return False, {
            "ticker": simbolo,
            "motivo": (
                f"VETO MERCADO: {benchmark} por debajo de su EMA{EMA_LARGA} "
                f"({cierre_benchmark:.2f} < {ema50_benchmark:.2f})."
            ),
        }

    # --- Filtro 3: tendencia del activo (precio > EMA20 > EMA50) ---
    precio_actual = float(df["Close"].iloc[-1])
    ema_corta = float(df[f"EMA{EMA_CORTA}"].iloc[-1])
    ema_larga = float(df[f"EMA{EMA_LARGA}"].iloc[-1])
    if not (precio_actual > ema_corta > ema_larga):
        return False, {
            "ticker": simbolo,
            "motivo": (
                f"VETO TÉCNICO: estructura no alcista, no se cumple "
                f"precio > EMA{EMA_CORTA} > EMA{EMA_LARGA} "
                f"({precio_actual:.2f} / {ema_corta:.2f} / {ema_larga:.2f})."
            ),
        }

    # --- Filtro 4: fuerza relativa vs. benchmark en 30 ruedas ---
    cierre_activo_previo = float(df["Close"].iloc[-RUEDAS_FUERZA_RELATIVA])
    cierre_benchmark_previo = float(df_benchmark["Close"].iloc[-RUEDAS_FUERZA_RELATIVA])
    if cierre_activo_previo <= 0 or cierre_benchmark_previo <= 0:
        return False, {
            "ticker": simbolo,
            "motivo": (
                f"VETO DATOS: cierre de hace {RUEDAS_FUERZA_RELATIVA} ruedas inválido "
                f"para medir fuerza relativa."
            ),
        }

    retorno_activo = (precio_actual / cierre_activo_previo) - 1
    retorno_benchmark = (cierre_benchmark / cierre_benchmark_previo) - 1
    if retorno_activo <= retorno_benchmark:
        return False, {
            "ticker": simbolo,
            "motivo": (
                f"VETO RS: no supera a {benchmark} en {RUEDAS_FUERZA_RELATIVA} ruedas "
                f"({retorno_activo * 100:.2f}% vs {retorno_benchmark * 100:.2f}%)."
            ),
            "retorno_activo_30d": round(retorno_activo * 100, 2),
            "retorno_benchmark_30d": round(retorno_benchmark * 100, 2),
        }

    # --- Filtro 5: volatilidad dinámica (ATR) y stop-loss ---
    atr = calculate_atr(df).iloc[-1]
    if pd.isna(atr) or float(atr) <= 0:
        return False, {
            "ticker": simbolo,
            "motivo": (
                f"VETO DATOS: ATR({config.ATR_PERIODO}) no calculable para {simbolo} "
                f"(valor {atr})."
            ),
        }
    atr = float(atr)

    # Filtros 5 y 6: stop por ATR (recortado al tope de config) y take-profit con
    # el ratio R/B exigido. La fórmula vive en `calcular_stop_y_objetivo`, que
    # comparten las tres fuentes de señal.
    riesgo = calcular_stop_y_objetivo(precio_actual, atr)
    stop_loss = riesgo["stop_loss"]
    pct_riesgo = riesgo["pct_riesgo"]
    stop_recortado = riesgo["stop_recortado"]
    take_profit = riesgo["take_profit"]

    # Nivel de ruptura, para el filtro anti-chase del EntryValidator (Tarea 4.4).
    # Se congela acá, en el instante en que la señal técnica se valida, como pide
    # el checklist de `pasar_ulises_31_2.docx`.
    #
    # Contra qué se mide sale de `config.BREAKOUT_REFERENCIA` (ver el comentario
    # de esa constante: el máximo de 20 ruedas es literal del spec, pero ahí la
    # entrada ES el cruce de ese máximo; acá la entrada es por tendencia).
    if config.BREAKOUT_REFERENCIA == "ema_corta":
        # El disparador real de nuestra señal: el filtro 3 exige precio > EMA20.
        breakout_level = float(ema_corta)
    else:
        # `ta.highest(high[1], 20)`: máximo de los N máximos ANTERIORES, sin
        # incluir la rueda actual — si la incluyera, el nivel nunca podría quedar
        # por debajo del precio y el filtro no vetaría nunca.
        breakout_level = float(df["High"].iloc[-(RUEDAS_BREAKOUT + 1):-1].max())

    return True, {
        "ticker": simbolo,
        "precio_entrada": round(precio_actual, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "pct_riesgo": round(pct_riesgo * 100, 2),
        "breakout_level": round(breakout_level, 2),
        # Contexto para el endpoint /senales y para auditar la señal después.
        "atr": round(atr, 4),
        f"ema{EMA_CORTA}": round(ema_corta, 2),
        f"ema{EMA_LARGA}": round(ema_larga, 2),
        "retorno_activo_30d": round(retorno_activo * 100, 2),
        "retorno_benchmark_30d": round(retorno_benchmark * 100, 2),
        "ratio_riesgo_beneficio": config.TAKE_PROFIT_RATIO,
        "stop_recortado_por_tolerancia": stop_recortado,
        "dias_hasta_balance": dias_balance,
    }
