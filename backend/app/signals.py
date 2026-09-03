"""
Orquestación del escaneo de señales de CEDEARs/acciones.

Orden de chequeos (Tarea 4.5, checklist de `pasar_ulises_31_2.docx` sección 5):

    VIX  →  régimen de mercado  →  [por ticker]  noticias → 7 filtros → anti-chase
    (global)      (global)                        FinBERT               vigencia

Los dos primeros son **globales**: cortan el escaneo entero sin evaluar ningún
ticker. Es a propósito — el checklist pide correr el filtro de mercado primero
justamente para descartar la watchlist en bloque en un día adverso y ahorrar
llamadas a la API.

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
from . import risk_filters
from . import smart_money
from . import technical_filters


def _respuesta_vacia(generado, universo, motivo, estado_vix, regimen=None) -> dict:
    """Escaneo cortado por un veto global: lista vacía, pero con el motivo."""
    return {
        "generado": generado,
        "universo": universo,
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

            # --- Por ticker 2: los 7 filtros técnicos ---
            valido, detalle = technical_filters.evaluate_7_filters(ticker)
            if not valido:
                descartados.append(
                    {"ticker": ticker, "motivo": detalle.get("motivo", "Vetado sin motivo informado")}
                )
                continue

            # --- Por ticker 3: vigencia de la señal (anti-chase, Tarea 4.4) ---
            # El `breakout_level` se congela dentro de `evaluate_7_filters`, en el
            # instante en que la señal técnica se valida: sobre ese número fijo se
            # mide el 1,0% de tolerancia, como pide el checklist del spec.
            precio = detalle.get("precio_entrada")
            breakout = detalle.get("breakout_level")
            if breakout is not None and precio is not None:
                vigente, motivo_vigencia = validador.is_signal_valid(precio, breakout)
                if not vigente:
                    descartados.append({"ticker": ticker, "motivo": motivo_vigencia})
                    continue

            candidatos.append(
                {
                    "ticker": detalle.get("ticker", ticker),
                    "precio_entrada": precio,
                    "stop_loss": detalle.get("stop_loss"),
                    "take_profit": detalle.get("take_profit"),
                    "pct_riesgo": detalle.get("pct_riesgo"),
                    "breakout_level": breakout,
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
        "veto_global": None,
        "vix": estado_vix,
        "regimen_mercado": regimen,
        "candidatos": candidatos,
        "descartados": descartados,
    }
