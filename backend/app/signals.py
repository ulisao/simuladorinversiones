"""
Orquestación del escaneo de señales de CEDEARs/acciones.

Orden de chequeos (Tarea 4.5, checklist de `pasar_ulises_31_2.docx` sección 5):

    VIX  →  régimen de mercado  →  [por ticker]  noticias → señal → anti-chase
    (global)      (global)                        FinBERT            vigencia

Los dos primeros son **globales**: cortan el escaneo entero sin evaluar ningún
ticker. Es a propósito — el checklist pide correr el filtro de mercado primero
justamente para descartar la watchlist en bloque en un día adverso y ahorrar
llamadas a la API.

## Dos fuentes de señal que conviven (Tarea 3.7)

El paso "señal" son en realidad **dos evaluaciones independientes** sobre el
mismo ticker:

| Origen | Disparador | Anti-chase |
|---|---|---|
| `7_FILTROS` | tendencia + fuerza relativa + ATR (los 7 filtros de la Fase 3) | sí |
| `RSI` | RSI(14) por debajo de 30 (sobreventa) | no aplica |
| `AMBOS` | las dos coincidieron en el mismo ticker | — |

Alcanza con que **una** pase para que el ticker sea candidato, y el campo
`origen` dice cuál fue. Ninguna reemplaza a la otra: están las dos justamente
para comparar en el simulador cuál rinde mejor antes de elegir.

El anti-chase no se le aplica a la señal de RSI: mide si el precio "se escapó"
hacia arriba del nivel de ruptura, y una señal de sobreventa es por definición
lo contrario. Un ticker vetado por anti-chase todavía puede entrar por RSI.

Los vetos **globales** y el de noticias sí valen para las dos fuentes: son
controles de riesgo, no de estrategia.

Diferencia deliberada con el manual: acá **no se ejecuta ninguna orden**. El
escaneo solo sugiere, y nunca pierde el motivo por el que descartó un candidato:
todo lo vetado sale en `descartados`, con su motivo, para poder auditarlo.

Los módulos que hablan con internet ya devuelven resultados controlados, pero
igual se envuelve cada ticker en un try/except: un ticker roto no puede tumbar
el escaneo entero.
"""
from datetime import datetime
from typing import Optional

from . import config
from . import entry_validator
from . import market_data
from . import risk_filters
from . import rsi_signal
from . import smart_money
from . import technical_filters


# Valores del campo `origen` de cada candidato (Tarea 3.7).
ORIGEN_7_FILTROS = "7_FILTROS"
ORIGEN_RSI = rsi_signal.ORIGEN          # "RSI"
ORIGEN_AMBOS = "AMBOS"


def _evaluar_7_filtros(ticker: str, validador) -> tuple[bool, dict, str]:
    """Los 7 filtros técnicos más el anti-chase, como una sola fuente de señal.

    Devuelve `(pasa, detalle, motivo)`. `motivo` queda vacío cuando pasa.
    """
    valido, detalle = technical_filters.evaluate_7_filters(ticker)
    if not valido:
        return False, detalle, detalle.get("motivo", "Vetado sin motivo informado")

    # Vigencia de la señal (anti-chase, Tarea 4.4). El `breakout_level` se congela
    # dentro de `evaluate_7_filters`, en el instante en que la señal técnica se
    # valida: sobre ese número fijo se mide el 1,0% de tolerancia.
    precio = detalle.get("precio_entrada")
    breakout = detalle.get("breakout_level")
    if breakout is not None and precio is not None:
        vigente, motivo_vigencia = validador.is_signal_valid(precio, breakout)
        if not vigente:
            return False, detalle, motivo_vigencia

    return True, detalle, ""


def _motivo_combinado(motivo_7f: str, motivo_rsi: str) -> str:
    """Un solo motivo de descarte que no pierde ninguna de las dos razones.

    Regla del repo: los motivos de veto no se pierden nunca. Si el ticker no
    calificó por ninguna de las dos fuentes, tienen que salir las dos razones.
    """
    partes = [m for m in (motivo_7f, motivo_rsi) if m]
    if not partes:
        return "Vetado sin motivo informado"
    if len(partes) == 1:
        return partes[0]
    return f"{partes[0]} | {partes[1]}"


def _respuesta_vacia(generado, universo, motivo, estado_vix, regimen=None) -> dict:
    """Escaneo cortado por un veto global: lista vacía, pero con el motivo."""
    return {
        "generado": generado,
        "universo": universo,
        "advertencia_precios": market_data.ADVERTENCIA_PRECIO_REFERENCIA,
        "veto_global": motivo,
        "vix": estado_vix,
        "regimen_mercado": regimen,
        "candidatos": [],
        "descartados": [],
    }


def escanear_senales(
    tickers: Optional[list[str]] = None,
    tipo_instrumento: str = "CEDEAR",
) -> dict:
    """Recorre el universo de tickers y devuelve candidatos y descartados.

    Estructura devuelta:
        {
          "generado": ISO-8601,
          "universo": [...],
          "veto_global": None | str,     # VIX en pánico o mercado en tendencia bajista
          "vix": {...},                  # estado del VIX, siempre presente
          "regimen_mercado": {...},      # estado del benchmark, None si no se llegó a evaluar
          "candidatos": [ {...}, ... ],  # pasaron todos los filtros
          "descartados": [ {"ticker", "motivo"}, ... ],
        }
    """
    universo = tickers if tickers is not None else config.TICKERS_BYMA
    generado = datetime.now().isoformat(timespec="seconds")

    # --- Global 1: circuit breaker de VIX ---
    # Una sola lectura: `check_vix_circuit_breaker()` volvería a pegarle a Yahoo
    # y las dos respuestas podrían discrepar (si la segunda falla, saldría un
    # veto global con el VIX en verde al lado). El veto se deriva de este dict.
    estado_vix = risk_filters.estado_vix()
    if estado_vix.get("veto"):
        return _respuesta_vacia(generado, universo, estado_vix.get("motivo"), estado_vix)

    # --- Global 2: régimen de mercado del benchmark (Tarea 4.4) ---
    # Se corre antes del bucle: si el índice está bajo su SMA200 o liquidando,
    # se descarta toda la watchlist de un saque.
    validador = entry_validator.EntryValidator()
    mercado_ok, regimen = entry_validator.chequear_regimen_mercado(
        tipo_instrumento, validador=validador
    )
    if not mercado_ok:
        return _respuesta_vacia(
            generado, universo, regimen.get("motivo"), estado_vix, regimen
        )

    candidatos: list[dict] = []
    descartados: list[dict] = []

    for ticker in universo:
        try:
            # --- Por ticker 1: noticias ---
            noticias_ok, score, noticias_msg = risk_filters.get_finbert_sentiment(ticker)
            if not noticias_ok:
                descartados.append({"ticker": ticker, "motivo": noticias_msg})
                continue

            # --- Contexto: smart money. Informativo, NUNCA vetea (Tarea 5.2). ---
            contexto = smart_money.contexto_smart_money(ticker)

            # --- Por ticker 2: las dos fuentes de señal (Tarea 3.7) ---
            # Se evalúan las dos siempre, aunque la primera ya haya pasado: hace
            # falta saber si coincidieron para poder marcar `origen="AMBOS"` y
            # comparar después cuál fuente rinde mejor. No cuesta llamadas de red
            # extra — las dos leen el mismo histórico cacheado.
            pasa_7f, detalle_7f, motivo_7f = _evaluar_7_filtros(ticker, validador)
            pasa_rsi, detalle_rsi = rsi_signal.evaluar_rsi(ticker)

            if not pasa_7f and not pasa_rsi:
                descartados.append(
                    {
                        "ticker": ticker,
                        "motivo": _motivo_combinado(
                            motivo_7f, detalle_rsi.get("motivo", "")
                        ),
                    }
                )
                continue

            if pasa_7f and pasa_rsi:
                origen = ORIGEN_AMBOS
            elif pasa_7f:
                origen = ORIGEN_7_FILTROS
            else:
                origen = ORIGEN_RSI

            # Con las dos fuentes activas manda el detalle de los 7 filtros: trae
            # el `breakout_level` y el contexto de tendencia. Los precios son los
            # mismos (mismo cierre, mismo ATR, misma config de riesgo).
            detalle = detalle_7f if pasa_7f else detalle_rsi

            candidatos.append(
                {
                    "ticker": detalle.get("ticker", ticker),
                    "origen": origen,
                    "precio_entrada": detalle.get("precio_entrada"),
                    "stop_loss": detalle.get("stop_loss"),
                    "take_profit": detalle.get("take_profit"),
                    "pct_riesgo": detalle.get("pct_riesgo"),
                    "breakout_level": detalle.get("breakout_level"),
                    # El RSI viaja siempre que se haya podido calcular, aunque la
                    # señal la haya disparado la otra fuente: es contexto útil.
                    "rsi": detalle_rsi.get("rsi"),
                    "sentimiento_score": round(score, 4) if score is not None else None,
                    "rvol": contexto.get("rvol"),
                    "es_acumulacion": contexto.get("es_acumulacion"),
                    "insiders_detectados": contexto.get("insiders_detectados"),
                    "insiders_detalle": contexto.get("insiders_detalle"),
                }
            )
        except Exception as exc:  # pragma: no cover — red de seguridad del escaneo
            descartados.append(
                {"ticker": ticker, "motivo": f"Error inesperado evaluando {ticker}: {exc}"}
            )

    return {
        "generado": generado,
        "universo": universo,
        "advertencia_precios": market_data.ADVERTENCIA_PRECIO_REFERENCIA,
        "veto_global": None,
        "vix": estado_vix,
        "regimen_mercado": regimen,
        "candidatos": candidatos,
        "descartados": descartados,
    }
