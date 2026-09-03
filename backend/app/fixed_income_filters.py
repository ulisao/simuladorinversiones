"""
Filtros institucionales de renta fija (bonos soberanos y provinciales).

Es el equivalente de `technical_filters.py` para bonos: la lógica de renta fija
es distinta a la de acciones/CEDEARs, porque un bono responde a variables de
crédito público (corte de cupón, paridad, spread en Contado Inmediato) y no a
earnings ni a fuerza relativa contra el S&P.

De los 7 filtros de la sección 2 del manual de bonos, acá viven los que se
pueden resolver con precio e histórico:

    1. Calendario de cupones  -> veto si hoy cae en la ventana de corte.
    5. Spread y profundidad   -> `check_spread_bid_ask` (necesita puntas de IOL).
    6. Volatilidad ATR        -> stop dinámico 1,5 x ATR con tope estricto de 3,0%.
    + tendencia vs. EMA20     -> veto si el bono cotiza por debajo de su media.

Los filtros 2 (Riesgo País), 3 (paridad), 4 (pendiente de curva) y 7 (spread
GD/AL) necesitan datos que todavía no tenemos (EMBI+, valor técnico, TIR) y
quedan fuera de este módulo.

Dos particularidades importantes de los bonos argentinos:

* **Casi no tienen histórico en Yahoo Finance.** Por eso `evaluate_bond_filters`
  tiene un modo degradado explícito: sin serie de al menos `RUEDAS_MINIMAS`
  ruedas no se puede calcular EMA20 ni ATR, así que se autoriza con el stop al
  tope estricto de `config.STOP_LOSS_MAX_PCT` y se deja constancia con
  `datos_limitados=True`. Ese camino se usa seguido, no es un caso de borde.
* **El tope de riesgo es estricto.** A diferencia de las acciones (que toleran
  hasta `STOP_LOSS_TOLERANCIA_PCT` = 3,5% antes de recortar), en bonos el manual
  recorta directo en `STOP_LOSS_MAX_PCT` = 3,0%.

Regla del repo (CLAUDE.md): los filtros devuelven `(bool, dict)` y el dict trae
`"motivo"` en español cuando el bool es `False`. Ningún parámetro de riesgo se
hardcodea acá: todo sale de `config.py`, documentado en `docs/parametros-riesgo.md`.

Referencia de spec: `docs/specs-txt/Manual_Maestro_Bot_Bonos_Soberanos_Provinciales.txt`,
secciones 2, 4, 5, 6 y 7 (el filtro de spread está extraído de `ejecutar_ciclo`
de `bot_bonds.py`, sección 7, y acá queda como función independiente y reusable).
"""
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from . import config
from .technical_filters import calculate_atr

# Período de la media móvil de tendencia. No es un parámetro de riesgo sino
# parte de la definición del filtro (el manual la llama "EMA 20"), por eso vive
# acá y no en `config.py`.
EMA_TENDENCIA_PERIODO = 20

# Mínimo de ruedas para confiar en EMA20 + ATR(14). Por debajo de esto se entra
# en el modo degradado del manual (sección 6).
RUEDAS_MINIMAS = 30

# Columnas OHLC que necesitan el ATR y la EMA.
COLUMNAS_REQUERIDAS = ("High", "Low", "Close")


# ---------- Helpers internos ----------


def _ahora() -> pd.Timestamp:
    """
    Momento actual. Aislado en una función para poder fijarlo en los tests
    (el veto por corte de cupón depende del mes y del día del calendario).
    """
    return pd.Timestamp.now()


def _a_float(valor: Any) -> Optional[float]:
    """Convierte a float, o devuelve None si el valor no es numérico / es NaN."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    if numero != numero:  # NaN
        return None
    return numero


def _serie_utilizable(df_historico: Any) -> bool:
    """`True` si el histórico alcanza para calcular EMA20 y ATR."""
    if df_historico is None or not isinstance(df_historico, pd.DataFrame):
        return False
    if len(df_historico) < RUEDAS_MINIMAS:
        return False
    return all(col in df_historico.columns for col in COLUMNAS_REQUERIDAS)


def _armar_resultado(
    simbolo: str,
    precio_entrada: float,
    stop_loss: float,
    detalle: str,
    datos_limitados: bool,
    ema20: Optional[float] = None,
    atr: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Arma el dict de una señal autorizada.

    El take-profit sale del ratio R/B de `config.TAKE_PROFIT_RATIO` aplicado al
    riesgo real de la operación (`precio - stop`), y `pct_riesgo` se informa en
    puntos porcentuales (3.0 = 3,0%), igual que en el manual y que en el módulo
    de acciones.
    """
    riesgo = precio_entrada - stop_loss
    take_profit = precio_entrada + riesgo * config.TAKE_PROFIT_RATIO
    pct_riesgo = (riesgo / precio_entrada) * 100 if precio_entrada > 0 else 0.0

    return {
        "simbolo": simbolo,
        "precio_entrada": round(precio_entrada, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "pct_riesgo": round(pct_riesgo, 2),
        "ratio_rb": config.TAKE_PROFIT_RATIO,
        "datos_limitados": datos_limitados,
        "ema20": round(ema20, 2) if ema20 is not None else None,
        "atr": round(atr, 4) if atr is not None else None,
        "detalle": detalle,
    }


# ---------- Filtro de liquidez: spread bid/ask en Contado Inmediato ----------


def check_spread_bid_ask(
    oferta_compra: Any,
    oferta_venta: Any,
    ultimo_precio: Any,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Filtro 5 del manual: spread bid/ask en Contado Inmediato.

    Un bono con las puntas muy separadas se compra caro y se vende barato: el
    costo de entrar y salir se come el objetivo. Se veta si el spread supera
    `config.SPREAD_BID_ASK_MAX` (0,6%).

    Extraído de `ejecutar_ciclo` de `bot_bonds.py` (sección 7 del manual), donde
    estaba inline; acá queda como función independiente para que la usen tanto
    el escaneo de señales como cualquier chequeo previo a mandar una orden.

    Args:
        oferta_compra: punta compradora (bid) en BYMA.
        oferta_venta: punta vendedora (ask) en BYMA.
        ultimo_precio: último precio operado, denominador del spread.

    Returns:
        `(True, dict)` si el spread es aceptable, `(False, dict)` si no.
        El dict siempre trae `"spread"` (fracción, ej. 0.004) y `"spread_pct"`
        (porcentaje, ej. 0.4) cuando se pudo calcular, y `"motivo"` en español
        cuando el bool es `False`. Puntas o último precio en cero / ausentes no
        rompen nada: se vetan como "sin cotización", nunca se divide por cero.
    """
    compra = _a_float(oferta_compra)
    venta = _a_float(oferta_venta)
    ultimo = _a_float(ultimo_precio)
    limite_pct = config.SPREAD_BID_ASK_MAX * 100

    if compra is None or venta is None or ultimo is None:
        return False, {
            "motivo": "VETO SPREAD: sin cotización (puntas o último precio no numéricos)",
            "spread": None,
            "spread_pct": None,
            "limite_pct": round(limite_pct, 2),
        }

    if ultimo <= 0 or compra <= 0 or venta <= 0:
        return False, {
            "motivo": (
                "VETO SPREAD: sin cotización "
                f"(punta compradora ${compra:.2f}, punta vendedora ${venta:.2f}, "
                f"último ${ultimo:.2f})"
            ),
            "spread": None,
            "spread_pct": None,
            "limite_pct": round(limite_pct, 2),
        }

    spread = (venta - compra) / ultimo
    spread_pct = spread * 100

    if venta < compra:
        return False, {
            "motivo": (
                "VETO SPREAD: puntas cruzadas (compradora "
                f"${compra:.2f} > vendedora ${venta:.2f}), cotización inconsistente"
            ),
            "spread": round(spread, 6),
            "spread_pct": round(spread_pct, 3),
            "limite_pct": round(limite_pct, 2),
        }

    if spread > config.SPREAD_BID_ASK_MAX:
        return False, {
            "motivo": (
                f"VETO SPREAD: spread bid/ask {spread_pct:.2f}% supera el máximo "
                f"de {limite_pct:.2f}% en Contado Inmediato"
            ),
            "spread": round(spread, 6),
            "spread_pct": round(spread_pct, 3),
            "limite_pct": round(limite_pct, 2),
        }

    return True, {
        "spread": round(spread, 6),
        "spread_pct": round(spread_pct, 3),
        "limite_pct": round(limite_pct, 2),
        "detalle": f"Spread {spread_pct:.2f}% dentro del máximo de {limite_pct:.2f}%",
    }


# ---------- Filtros técnicos y de calendario del bono ----------


def evaluate_bond_filters(
    simbolo: str,
    precio_mercado: Any,
    df_historico: Optional[pd.DataFrame] = None,
    ahora: Optional[pd.Timestamp] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Evalúa los filtros institucionales que autorizan (o vetan) la compra de un bono.

    Orden de evaluación:

    1. **Calendario de corte de cupón.** Si el símbolo figura en
       `config.MESES_CORTE_CUPON` y hoy cae en un mes de pago dentro de la
       ventana `config.CUPON_DIA_DESDE`..`config.CUPON_DIA_HASTA`, se veta: el
       precio se corta el día de pago y arruina el stop. Los provinciales que no
       están en el diccionario no tienen calendario cargado y pasan este filtro.
    2. **Modo degradado sin serie histórica.** Si `df_historico` es `None`, no es
       un DataFrame, tiene menos de `RUEDAS_MINIMAS` ruedas o le faltan columnas
       OHLC, no hay EMA20 ni ATR posibles: se autoriza con el stop al tope
       estricto de `config.STOP_LOSS_MAX_PCT` y se marca `datos_limitados=True`.
       Los bonos argentinos casi no tienen histórico en Yahoo Finance, así que
       este es el camino habitual hasta que haya datos de IOL.
    3. **Tendencia vs. EMA20.** Veto si el precio de mercado está por debajo de
       la EMA20 del histórico.
    4. **Volatilidad (ATR) y stop-loss.** `stop = precio - ATR_MULTIPLICADOR *
       ATR`, recortado a `config.STOP_LOSS_MAX_PCT` si el riesgo lo supera (en
       bonos el tope es estricto: no se aplica la tolerancia del 3,5% de las
       acciones).
    5. **Take-profit.** `precio + (precio - stop) * config.TAKE_PROFIT_RATIO`.

    Args:
        simbolo: símbolo del bono en BYMA, sin sufijo (`"AL30"`, `"BA37D"`). Para
            pedirle el histórico a Yahoo hay que agregarle `config.SUFIJO_YF_BYMA`.
        precio_mercado: último precio operado / precio de entrada evaluado.
        df_historico: OHLCV del bono (columnas High/Low/Close), o `None` si no hay.
        ahora: fecha a usar para el calendario de cupones. Por defecto, el momento
            actual; se inyecta en los tests para ejercitar el veto fuera de época.

    Returns:
        `(True, dict)` con `simbolo`, `precio_entrada`, `stop_loss`,
        `take_profit`, `pct_riesgo` (en puntos porcentuales), más `ratio_rb`,
        `datos_limitados`, `ema20`, `atr` y `detalle`.
        `(False, dict)` con `"motivo"` en español cuando algún filtro veta.

    El `df_historico` recibido nunca se modifica: la EMA y el ATR se calculan
    sobre una copia.
    """
    simbolo = (simbolo or "").strip().upper()
    if not simbolo:
        return False, {"motivo": "VETO SÍMBOLO: no se indicó el bono a evaluar"}

    precio = _a_float(precio_mercado)
    if precio is None or precio <= 0:
        return False, {
            "motivo": (
                f"VETO SIN COTIZACIÓN: {simbolo} sin último precio válido "
                f"(se recibió {precio_mercado!r})"
            ),
            "simbolo": simbolo,
        }

    momento = ahora if ahora is not None else _ahora()

    # 1. Calendario de corte de cupón (renta / amortización).
    meses_corte = config.MESES_CORTE_CUPON.get(simbolo, [])
    if momento.month in meses_corte and (
        config.CUPON_DIA_DESDE <= momento.day <= config.CUPON_DIA_HASTA
    ):
        return False, {
            "motivo": (
                f"VETO CORTE CUPÓN: {simbolo} paga renta/amortización en el mes "
                f"{momento.month} y hoy es {momento.day:02d}/{momento.month:02d}, "
                f"dentro de la ventana de corte (días {config.CUPON_DIA_DESDE} "
                f"a {config.CUPON_DIA_HASTA})"
            ),
            "simbolo": simbolo,
        }

    # 2. Modo degradado: sin serie histórica utilizable.
    if not _serie_utilizable(df_historico):
        ruedas = len(df_historico) if isinstance(df_historico, pd.DataFrame) else 0
        return True, _armar_resultado(
            simbolo=simbolo,
            precio_entrada=precio,
            stop_loss=precio * (1 - config.STOP_LOSS_MAX_PCT),
            datos_limitados=True,
            detalle=(
                f"Sin serie histórica suficiente ({ruedas} ruedas, se necesitan "
                f"{RUEDAS_MINIMAS}): no se evaluaron EMA20 ni ATR. Stop fijado al "
                f"tope estricto de {config.STOP_LOSS_MAX_PCT * 100:.1f}% y "
                f"take-profit por ratio R/B 1:{config.TAKE_PROFIT_RATIO:g}."
            ),
        )

    # A partir de acá se trabaja sobre una copia: el DataFrame del llamador (que
    # puede venir de la cache de `market_data`) no se toca.
    df = df_historico.copy()

    # 3. Tendencia: precio vs. EMA20.
    df["EMA20"] = df["Close"].ewm(span=EMA_TENDENCIA_PERIODO, adjust=False).mean()
    ema20 = _a_float(df["EMA20"].iloc[-1])
    if ema20 is None:
        return True, _armar_resultado(
            simbolo=simbolo,
            precio_entrada=precio,
            stop_loss=precio * (1 - config.STOP_LOSS_MAX_PCT),
            datos_limitados=True,
            detalle=(
                "EMA20 no calculable con la serie recibida: stop al tope estricto "
                f"de {config.STOP_LOSS_MAX_PCT * 100:.1f}%."
            ),
        )

    if precio < ema20:
        return False, {
            "motivo": (
                f"VETO TENDENCIA: {simbolo} cotiza a ${precio:.2f}, por debajo de "
                f"su EMA20 (${ema20:.2f})"
            ),
            "simbolo": simbolo,
            "precio_entrada": round(precio, 2),
            "ema20": round(ema20, 2),
        }

    # 4. Volatilidad dinámica (ATR) y stop-loss.
    try:
        serie_atr = calculate_atr(df)
        atr = _a_float(serie_atr.iloc[-1])
    except Exception:  # nunca romper el escaneo por un ATR que no se pudo calcular
        atr = None

    if atr is None or atr <= 0:
        return True, _armar_resultado(
            simbolo=simbolo,
            precio_entrada=precio,
            stop_loss=precio * (1 - config.STOP_LOSS_MAX_PCT),
            datos_limitados=True,
            ema20=ema20,
            detalle=(
                f"ATR({config.ATR_PERIODO}) no disponible con la serie recibida: "
                f"stop al tope estricto de {config.STOP_LOSS_MAX_PCT * 100:.1f}%. "
                f"Tendencia OK (precio ${precio:.2f} >= EMA20 ${ema20:.2f})."
            ),
        )

    stop_loss = precio - config.ATR_MULTIPLICADOR * atr
    pct_riesgo = (precio - stop_loss) / precio

    # Tope estricto del manual de bonos: 3,0% directo, sin la tolerancia del
    # 3,5% que sí usan las acciones/CEDEARs.
    recortado = False
    if pct_riesgo > config.STOP_LOSS_MAX_PCT:
        stop_loss = precio * (1 - config.STOP_LOSS_MAX_PCT)
        recortado = True

    detalle = (
        f"Tendencia OK (precio ${precio:.2f} >= EMA20 ${ema20:.2f}). "
        f"Stop por {config.ATR_MULTIPLICADOR:g} x ATR({config.ATR_PERIODO}) = "
        f"{config.ATR_MULTIPLICADOR * atr:.2f}"
    )
    if recortado:
        detalle += f", recortado al tope estricto de {config.STOP_LOSS_MAX_PCT * 100:.1f}%"
    detalle += "."

    return True, _armar_resultado(
        simbolo=simbolo,
        precio_entrada=precio,
        stop_loss=stop_loss,
        datos_limitados=False,
        ema20=ema20,
        atr=atr,
        detalle=detalle,
    )
