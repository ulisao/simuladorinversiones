"""
Filtros de entrada: régimen de mercado y vigencia de la señal (anti-chase).

Port de la clase `EntryValidator` de `docs/specs-txt/pasar_ulises_31_2.txt`
(secciones 1 a 3), más el enganche con `market_data` para traer el benchmark que
corresponde según el tipo de instrumento (sección 5, checklist de integración).

Dos filtros, en este orden:

1. **Contexto de mercado (`is_market_healthy`)** — el índice de referencia tiene
   que cotizar sobre su SMA200 diaria y no estar cayendo más de
   `config.ENTRADA_MERCADO_CAIDA_MAX` en la rueda. Va primero a propósito: si el
   día es adverso se descarta toda la watchlist de un saque, sin gastar una
   llamada a la API por cada ticker.
2. **Vigencia de señal (`is_signal_valid`)** — el precio actual tiene que estar
   por encima del `breakout_level` congelado al validar la señal técnica, pero no
   más de `config.ENTRADA_MAX_CHASE_PCT` por encima. Si el papel ya se escapó, el
   stop-loss del 3% queda demasiado lejos y se arruina el ratio riesgo/beneficio.

`can_open_position` es la compuerta final: corre el filtro 1 y recién después el 2.

Diferencias deliberadas contra el código de la spec:

- **Mensajes en español y con el formato de veto del repo** (`"VETO MERCADO: ..."`,
  `"VETO SEÑAL: ..."`, y `"COMPRA RECHAZADA: ..."` en la compuerta final), igual
  que `technical_filters.py`.
- **Nada hardcodeado**: los umbrales y el mapeo tipo -> benchmark salen de
  `config.py` (documentado en `docs/parametros-riesgo.md`).
- **Los datos que faltan no se asumen buenos.** La spec recibe tres floats y
  confía. Acá, si llega `None` / `NaN` / infinito, el filtro devuelve veto con
  motivo, nunca un `TypeError` hacia el endpoint.

Criterio ante error de red o datos insuficientes (regla de CLAUDE.md: este módulo
habla con internet y nunca rompe el proceso):

* **`datos_benchmark` -> resultado controlado, nunca excepción.** Devuelve el
  dict con `disponible=False` y `motivo` explicando qué pasó.
* **`chequear_regimen_mercado` -> fail-safe, VETA.** Mismo criterio que el
  circuit breaker de VIX en `risk_filters`: el régimen de mercado es riesgo
  sistémico, y sin saber si el índice está bajo su SMA200 o liquidándose no se
  abre posición. Lo contrario —dejar pasar— habilitaría el universo entero justo
  el día que Yahoo no responde, que es exactamente el escenario que este filtro
  existe para evitar. La única excepción es el instrumento que no tiene benchmark
  asignado (`BONO`, con `config.BENCHMARK_POR_TIPO["BONO"] = None`): ahí el
  filtro no aplica y se deja pasar, porque ese riesgo lo cubren los controles de
  `fixed_income_filters.py`.

Fuente de precios: `precio`, `sma200` y `cambio_diario_pct` salen todos del
**mismo** histórico diario de `market_data.get_history` (una sola descarga, que
además queda cacheada). Se prefirió eso a mezclar `get_last_price` —que pide otra
ventana ("5d") y sería una segunda llamada a Yahoo por escaneo— para que el
precio comparado contra la SMA200 y la variación diaria sean siempre coherentes
entre sí.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional, Tuple

from . import config
from .market_data import MarketDataError, get_history

logger = logging.getLogger(__name__)


# ---------- Constantes estructurales ----------
# No son parámetros de riesgo (esos están en config.py): son requisitos del
# cálculo. Para una SMA de 200 ruedas hacen falta ~200 velas diarias, así que la
# ventana de 60 días que usan los 7 filtros no alcanza: se pide un año.

PERIODO_HISTORICO_BENCHMARK = "1y"

# Mínimo de cierres para poder calcular la variación de la última rueda.
RUEDAS_MINIMAS_CAMBIO_DIARIO = 2


def _es_numero(valor: Any) -> bool:
    """True si `valor` es un número real y finito (descarta None, NaN, inf y bool)."""
    if valor is None or isinstance(valor, bool):
        return False
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError):
        return False


# ---------- Tarea 4.4: la clase de la spec ----------


class EntryValidator:
    """
    Valida las dos condiciones previas a cualquier orden de compra.

    Args:
        max_chase_pct: tolerancia máxima de persecución sobre el nivel de
            ruptura, en tanto por uno. Por defecto `config.ENTRADA_MAX_CHASE_PCT`
            (0.010 = 1,0%).
        market_min_change: caída diaria máxima tolerada en el índice, en tanto por
            uno y negativa. Por defecto `config.ENTRADA_MERCADO_CAIDA_MAX`
            (-0.010 = -1,0%).

    Raises:
        ValueError: si `max_chase_pct` es negativo o `market_min_change` positivo.
    """

    def __init__(
        self,
        max_chase_pct: float = config.ENTRADA_MAX_CHASE_PCT,
        market_min_change: float = config.ENTRADA_MERCADO_CAIDA_MAX,
    ) -> None:
        chase = config.ENTRADA_MAX_CHASE_PCT if max_chase_pct is None else max_chase_pct
        caida = config.ENTRADA_MERCADO_CAIDA_MAX if market_min_change is None else market_min_change

        if not _es_numero(chase) or float(chase) < 0:
            raise ValueError(
                f"max_chase_pct tiene que ser un número >= 0 (tanto por uno), "
                f"llegó {max_chase_pct!r}."
            )
        if not _es_numero(caida) or float(caida) > 0:
            raise ValueError(
                f"market_min_change tiene que ser un número <= 0 (tanto por uno), "
                f"llegó {market_min_change!r}."
            )

        self.max_chase_pct = float(chase)
        self.market_min_change = float(caida)

    def __repr__(self) -> str:  # pragma: no cover - sólo para depurar
        return (
            f"EntryValidator(max_chase_pct={self.max_chase_pct!r}, "
            f"market_min_change={self.market_min_change!r})"
        )

    # ----- Filtro 1: contexto de mercado -----

    def is_market_healthy(
        self,
        market_index_price: float,
        market_index_sma200: float,
        market_daily_change_pct: float,
    ) -> Tuple[bool, str]:
        """
        FILTRO 1: ¿el índice de referencia (SPY / QQQ / ^MERV) permite operar?

        Veta si el índice está por debajo de su SMA200 diaria (tendencia bajista
        general activa) o si la rueda cae más que `market_min_change`.

        Args:
            market_index_price: último precio del índice.
            market_index_sma200: SMA de `config.SMA_BENCHMARK_PERIODO` ruedas diarias.
            market_daily_change_pct: variación de la rueda en tanto por uno
                (-0.012 = -1,2%).

        Returns:
            `(True, motivo)` si el mercado está sano; `(False, motivo)` con el
            veto en formato `"VETO MERCADO: ..."` si no.
        """
        faltantes = [
            nombre
            for nombre, valor in (
                ("precio", market_index_price),
                ("SMA200", market_index_sma200),
                ("cambio diario", market_daily_change_pct),
            )
            if not _es_numero(valor)
        ]
        if faltantes:
            # Fail-safe, igual que el VIX: sin el dato no se autoriza la compra.
            return False, (
                "VETO MERCADO: no se pudo evaluar el régimen del índice, faltan datos "
                f"({', '.join(faltantes)})."
            )

        precio = float(market_index_price)
        sma200 = float(market_index_sma200)
        cambio = float(market_daily_change_pct)

        if sma200 <= 0:
            return False, f"VETO MERCADO: SMA200 del índice inválida ({sma200})."

        # 1. Tendencia macro del mercado.
        if precio < sma200:
            return False, (
                f"VETO MERCADO: índice por debajo de su SMA200 "
                f"({precio:.2f} < {sma200:.2f}), tendencia bajista general activa."
            )

        # 2. Caída intradiaria / día de pánico.
        if cambio < self.market_min_change:
            return False, (
                f"VETO MERCADO: día de venta masiva en el índice "
                f"({cambio * 100:.2f}% < {self.market_min_change * 100:.1f}%)."
            )

        return True, (
            f"Mercado saludable y apto para compras (índice {precio:.2f} sobre su "
            f"SMA200 {sma200:.2f}, rueda {cambio * 100:+.2f}%)."
        )

    # ----- Filtro 2: vigencia de la señal (anti-chase) -----

    def is_signal_valid(
        self,
        current_price: float,
        breakout_level: float,
        exigir_superar: Optional[bool] = None,
    ) -> Tuple[bool, str]:
        """
        FILTRO 2: ¿el activo sigue en zona de entrada respecto de la ruptura?

        `breakout_level` es el nivel congelado en el instante en que
        `technical_filters.evaluate_7_filters` validó la señal técnica: acá no se
        recalcula, se compara contra ese número fijo (checklist de la spec).

        Args:
            current_price: precio actual del activo.
            breakout_level: nivel de ruptura congelado al validar la señal.
            exigir_superar: si el precio tiene que haber superado ya el nivel.
                None (default) toma `config.BREAKOUT_EXIGE_SUPERAR`. En False solo
                se veta por extensión: entrar temprano en la tendencia no es
                "perseguir" el precio, y con `BREAKOUT_REFERENCIA` en máximo de N
                ruedas el piso inferior exigiría estar en máximos, que los 7
                filtros nunca pidieron.

        Returns:
            `(True, motivo)` si la entrada sigue vigente; `(False, motivo)` con el
            veto en formato `"VETO SEÑAL: ..."` si no.
        """
        faltantes = [
            nombre
            for nombre, valor in (
                ("precio actual", current_price),
                ("nivel de ruptura", breakout_level),
            )
            if not _es_numero(valor)
        ]
        if faltantes:
            return False, (
                "VETO SEÑAL: no se pudo evaluar la vigencia de la entrada, faltan datos "
                f"({', '.join(faltantes)})."
            )

        precio = float(current_price)
        ruptura = float(breakout_level)

        if ruptura <= 0:
            return False, f"VETO SEÑAL: nivel de ruptura inválido ({ruptura})."

        if exigir_superar is None:
            exigir_superar = getattr(config, "BREAKOUT_EXIGE_SUPERAR", True)

        if exigir_superar and precio < ruptura:
            return False, (
                f"VETO SEÑAL: el precio actual todavía no superó el nivel de ruptura "
                f"({precio:.2f} < {ruptura:.2f})."
            )

        distancia = (precio / ruptura) - 1.0

        # Se compara contra `ruptura * (1 + tolerancia)` —la fórmula literal de la
        # spec, `Precio_Actual <= Nivel_Ruptura * 1.010`— y no contra la distancia
        # calculada: con floats, 101.0 / 100.0 - 1 da 0.010000000000000009, o sea
        # que el borde exacto del 1,0% se vetaría por error de redondeo.
        limite = ruptura * (1.0 + self.max_chase_pct)
        if precio > limite:
            return False, (
                f"VETO SEÑAL: señal vencida, precio extendido un {distancia * 100:.2f}% "
                f"sobre la ruptura (máximo permitido: {self.max_chase_pct * 100:.1f}%)."
            )

        return True, (
            f"Entrada válida: en rango óptimo (+{distancia * 100:.2f}% de la ruptura, "
            f"máximo {self.max_chase_pct * 100:.1f}%)."
        )

    # ----- Compuerta final -----

    def can_open_position(
        self,
        current_price: float,
        breakout_level: float,
        market_price: float,
        market_sma200: float,
        market_change_pct: float,
    ) -> Tuple[bool, str]:
        """
        Compuerta lógica final: valida los dos filtros antes de autorizar la compra.

        El filtro de mercado va **primero** (checklist de la spec, sección 5): si
        el día es adverso se descarta la watchlist completa sin evaluar ticker por
        ticker, ahorrando peticiones a la API.

        Returns:
            `(True, "COMPRA APROBADA: ...")` o `(False, "COMPRA RECHAZADA: ...")`.
            El motivo del rechazo conserva su prefijo `VETO MERCADO:` /
            `VETO SEÑAL:` para poder identificar qué filtro cortó.
        """
        mercado_ok, motivo_mercado = self.is_market_healthy(
            market_price, market_sma200, market_change_pct
        )
        if not mercado_ok:
            return False, f"COMPRA RECHAZADA: {motivo_mercado}"

        senial_ok, motivo_senial = self.is_signal_valid(current_price, breakout_level)
        if not senial_ok:
            return False, f"COMPRA RECHAZADA: {motivo_senial}"

        return True, "COMPRA APROBADA: ambos filtros verificados con éxito."


# ---------- Datos del benchmark según el tipo de instrumento ----------


def ticker_benchmark(tipo_instrumento: str) -> Optional[str]:
    """
    Ticker del índice de referencia para un tipo de instrumento.

    `CEDEAR` -> SPY, `ACCION` -> ^MERV, `BONO` -> None (no tiene benchmark de
    régimen: ese riesgo lo miran los filtros de `fixed_income_filters`). Un tipo
    desconocido cae en `config.TICKER_BENCHMARK` (SPY), que es el default del
    resto del repo, y queda logueado como warning.
    """
    tipo = (tipo_instrumento or "").strip().upper()
    if tipo in config.BENCHMARK_POR_TIPO:
        return config.BENCHMARK_POR_TIPO[tipo]

    logger.warning(
        "Tipo de instrumento desconocido '%s': se usa el benchmark por defecto %s.",
        tipo_instrumento,
        config.TICKER_BENCHMARK,
    )
    return config.TICKER_BENCHMARK


def datos_benchmark(tipo_instrumento: str) -> Dict[str, Any]:
    """
    Trae precio, SMA200 diaria y variación de la última rueda del benchmark.

    Args:
        tipo_instrumento: `"CEDEAR"`, `"ACCION"` o `"BONO"` (el campo `tipo` del
            modelo `Trade`). No distingue mayúsculas ni espacios sobrantes.

    Returns:
        dict con:

        - `tipo` (str): el tipo normalizado en mayúsculas.
        - `ticker` (str | None): símbolo del índice usado, o None si el tipo no
          tiene benchmark asignado.
        - `precio` (float | None): último cierre del índice.
        - `sma200` (float | None): media simple de los últimos
          `config.SMA_BENCHMARK_PERIODO` cierres diarios.
        - `cambio_diario_pct` (float | None): variación de la última rueda contra
          la anterior, en tanto por uno (`-0.012` = -1,2%).
        - `aplica` (bool): False cuando el tipo no tiene benchmark (bonos).
        - `disponible` (bool): True sólo si `precio`, `sma200` y
          `cambio_diario_pct` son usables.
        - `motivo` (str | None): por qué no hay datos, cuando `disponible` es False.
        - `ruedas` (int): cierres válidos que trajo el histórico.

    Nunca lanza excepciones: red caída, ticker inexistente o histórico corto
    devuelven `disponible=False` con `motivo`.
    """
    tipo = (tipo_instrumento or "").strip().upper()
    simbolo = ticker_benchmark(tipo)

    base: Dict[str, Any] = {
        "tipo": tipo,
        "ticker": simbolo,
        "precio": None,
        "sma200": None,
        "cambio_diario_pct": None,
        "aplica": simbolo is not None,
        "disponible": False,
        "motivo": None,
        "ruedas": 0,
    }

    if simbolo is None:
        base["motivo"] = (
            f"El tipo '{tipo}' no tiene índice de referencia asignado en "
            "config.BENCHMARK_POR_TIPO: el filtro de régimen de mercado no aplica."
        )
        return base

    try:
        df = get_history(simbolo, period=PERIODO_HISTORICO_BENCHMARK)
    except MarketDataError as e:
        base["motivo"] = f"Sin histórico del benchmark {simbolo}: {e}"
        return base

    if "Close" not in df.columns:
        base["motivo"] = (
            f"El histórico de {simbolo} no trae columna 'Close': {list(df.columns)}."
        )
        return base

    cierres = df["Close"].dropna()
    base["ruedas"] = int(len(cierres))

    periodo_sma = int(config.SMA_BENCHMARK_PERIODO)
    minimo = max(periodo_sma, RUEDAS_MINIMAS_CAMBIO_DIARIO)
    if len(cierres) < minimo:
        base["motivo"] = (
            f"Ruedas insuficientes para la SMA{periodo_sma} de {simbolo}: "
            f"{len(cierres)} cierres válidos, se necesitan {minimo} "
            f"(período pedido: {PERIODO_HISTORICO_BENCHMARK})."
        )
        return base

    try:
        precio = float(cierres.iloc[-1])
        anterior = float(cierres.iloc[-2])
        sma200 = float(cierres.iloc[-periodo_sma:].mean())
    except (TypeError, ValueError) as e:  # cierres ilegibles: no rompe el escaneo
        base["motivo"] = f"Cierres ilegibles en el histórico de {simbolo}: {e}"
        return base

    if anterior <= 0 or not _es_numero(precio) or not _es_numero(sma200):
        base["motivo"] = (
            f"Cierres inválidos en el histórico de {simbolo} "
            f"(último {precio}, previo {anterior}, SMA{periodo_sma} {sma200})."
        )
        return base

    base.update(
        {
            "precio": precio,
            "sma200": sma200,
            "cambio_diario_pct": (precio / anterior) - 1.0,
            "disponible": True,
        }
    )
    return base


def chequear_regimen_mercado(
    tipo_instrumento: str,
    validador: Optional[EntryValidator] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Filtro 1 listo para el escaneo: trae el benchmark del tipo y lo evalúa.

    Devuelve `(bool, dict)` como el resto de los filtros del repo, con
    `dict["motivo"]` siempre presente cuando el bool es False.

    Args:
        tipo_instrumento: `"CEDEAR"`, `"ACCION"` o `"BONO"`.
        validador: `EntryValidator` a reutilizar en todo el escaneo. Si es None se
            instancia uno con los umbrales de `config`.

    Returns:
        `(habilitado, detalle)`. `detalle` es el dict de `datos_benchmark` con
        `motivo` pisado por el veto (o por el mensaje de mercado sano).

    Criterio ante error: **veta** (fail-safe), igual que el circuit breaker de
    VIX. La única excepción es el tipo sin benchmark (`BONO`), donde el filtro no
    aplica y se deja pasar.
    """
    validador = validador or EntryValidator()
    detalle = datos_benchmark(tipo_instrumento)

    if not detalle["aplica"]:
        # No es un error: los bonos no tienen índice de régimen en este sistema.
        return True, detalle

    if not detalle["disponible"]:
        detalle["motivo"] = (
            f"VETO MERCADO: no se pudo evaluar el régimen de {detalle['ticker']}. "
            f"{detalle['motivo']}"
        )
        return False, detalle

    sano, motivo = validador.is_market_healthy(
        detalle["precio"], detalle["sma200"], detalle["cambio_diario_pct"]
    )
    detalle["motivo"] = motivo
    return sano, detalle
