"""
Toma automática de posiciones en **paper trading**.

Cierra el único paso manual que quedaba en el circuito: hasta ahora el scanner
detectaba una señal, avisaba por Telegram, y alguien tenía que cargarla a mano en
`/simulador` (es literalmente lo que pide la Tarea 10.4). Este módulo hace esa
carga solo, para que el período de validación no dependa de que haya alguien
mirando el celular a las 11:40 de un martes.

> [!warning] Esto NO opera en IOL
> No envía ninguna orden. Lo único que le pide a IOL es el **precio** (lectura).
> Las posiciones existen solo en `simulador.db` y se ven en el dashboard.
> `MODO_FANTASMA` sigue siendo el kill switch de la ejecución real, que no existe.

## El circuito, ahora completo

```mermaid
flowchart LR
    SC[scanner_job<br/>cada 10 min] --> SIG[señal nueva]
    SIG --> TG{{Telegram: aviso}}
    SIG --> PT[paper_trader<br/>abrir_si_corresponde]
    PT --> G{guardrails}
    G -- rechaza --> LOG[/motivo en el log/]
    G -- acepta --> TR[(Trade en la base)]
    TR --> PM[position_monitor_job<br/>gestiona la salida sola]
    PM --> DASH[/Dashboard/]
```

## Guardrails

Todos salen de `config.py`; ninguno está hardcodeado (regla de CLAUDE.md).

| Control | De dónde sale | Qué evita |
|---|---|---|
| Máximo de posiciones abiertas | `MAX_POSICIONES` | Quedar sobre-expuesto |
| Un solo ticket por activo | — | Duplicar la misma señal en dos ciclos |
| Monto por posición | `monto_por_posicion(estrategia)` | Que una sola apuesta se coma el cupo |
| Cupo por estrategia | `cupo_de(estrategia)` | Que swing se coma el capital de smart money |
| Piso de capital libre | `SALDO_MINIMO_OPERAR` | Abrir con las últimas monedas |
| Cantidad entera ≥ 1 | — | Comprar 0,4 CEDEARs |

> [!note] El precio de entrada es el de BYMA en pesos, no el de la señal
> Para CEDEARs, la señal trae el precio del **subyacente en USD** (yfinance), que
> es con lo que se calcula el patrón técnico. La posición se toma al precio real
> del CEDEAR en pesos, que sale de `precios.precio_operativo`. Son dos precios
> distintos del mismo activo y mezclarlos rompe todas las cuentas de plata — ver
> el docstring de `app/precios.py`.
"""
import logging
from datetime import date
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from . import config, crud, models, notifications, precios, schemas

logger = logging.getLogger(__name__)


def habilitado() -> bool:
    """True si el bot puede abrir posiciones de paper solo."""
    return config.PAPER_AUTO_HABILITADO


# ---------- Estado de la cartera simulada ----------


def _abiertos(db: Session) -> list[models.Trade]:
    return crud.listar_trades_abiertos(db)


def capital_comprometido(db: Session, estrategia: str) -> float:
    """ARS ya invertidos en posiciones abiertas de una estrategia (a precio de entrada)."""
    return sum(
        t.cantidad * t.precio_entrada
        for t in _abiertos(db)
        if (t.estrategia or config.ESTRATEGIA_SWING) == estrategia
    )


def _ya_tiene_posicion(db: Session, ticker: str) -> bool:
    objetivo = ticker.upper().strip()
    return any(t.ticker.upper().strip() == objetivo for t in _abiertos(db))


# ---------- Decisión ----------


def evaluar(
    db: Session,
    ticker: str,
    estrategia: str = config.ESTRATEGIA_SWING,
    precio: Optional[float] = None,
) -> Dict[str, Any]:
    """Decide si corresponde abrir, y con cuánto. No escribe nada.

    Devuelve `{"abrir": bool, "motivo": str, "cantidad": float, "precio": float}`.
    `motivo` explica el rechazo cuando `abrir` es False.
    """
    rechazo = lambda m: {"abrir": False, "motivo": m, "cantidad": 0.0, "precio": 0.0}  # noqa: E731

    if not habilitado():
        return rechazo("La toma automática está apagada (PAPER_AUTO_HABILITADO=false).")

    if _ya_tiene_posicion(db, ticker):
        return rechazo(f"Ya hay una posición abierta en {ticker}.")

    abiertos = len(_abiertos(db))
    if abiertos >= config.MAX_POSICIONES:
        return rechazo(
            f"Ya hay {abiertos} posición(es) abiertas y el máximo es {config.MAX_POSICIONES}."
        )

    # Precio real en pesos. Sin esto no se puede calcular ni la cantidad ni el
    # resultado, así que es un rechazo y no un default.
    if precio is None:
        try:
            precio = precios.precio_operativo(ticker)
        except precios.PrecioError as exc:
            return rechazo(f"Sin precio operativo: {exc}")
    if precio <= 0:
        return rechazo(f"Precio no operable para {ticker}: {precio!r}.")

    cupo = config.cupo_de(estrategia)
    usado = capital_comprometido(db, estrategia)
    libre = cupo - usado
    if libre < config.SALDO_MINIMO_OPERAR:
        return rechazo(
            f"Cupo de {estrategia} casi agotado: quedan ${libre:,.0f} de ${cupo:,.0f} "
            f"y el piso para operar es ${config.SALDO_MINIMO_OPERAR:,.0f}."
        )

    # El menor entre "lo que permite una posición" y "lo que queda del cupo".
    monto = min(config.monto_por_posicion(estrategia), libre)

    # Papeles enteros: no existen las fracciones de CEDEAR ni de bono.
    cantidad = float(int(monto // precio))
    if cantidad < 1:
        return rechazo(
            f"Con ${monto:,.0f} no alcanza para 1 papel de {ticker} a ${precio:,.2f}."
        )

    return {"abrir": True, "motivo": "", "cantidad": cantidad, "precio": precio}


# ---------- Ejecución (en la base, no en IOL) ----------


def abrir_si_corresponde(
    db: Session,
    ticker: str,
    estrategia: str = config.ESTRATEGIA_SWING,
    tipo: str = "CEDEAR",
    senal: str = "",
    precio: Optional[float] = None,
) -> Optional[models.Trade]:
    """Abre la posición simulada si pasa los guardrails. Nunca lanza.

    Devuelve el `Trade` creado, o None si no correspondía (con el motivo en el log).
    """
    trade, _motivo = _intentar(db, ticker, estrategia, tipo, senal, precio)
    return trade


def _intentar(
    db: Session,
    ticker: str,
    estrategia: str,
    tipo: str,
    senal: str,
    precio: Optional[float],
) -> tuple[Optional[models.Trade], str]:
    """`abrir_si_corresponde` pero devolviendo también el motivo del rechazo.

    Existe para que `abrir_desde_candidatos` arme su resumen sin volver a llamar
    a `evaluar` — que pediría el precio a IOL una segunda vez por cada candidato
    rechazado, y los rechazos son el caso común.
    """
    try:
        decision = evaluar(db, ticker, estrategia=estrategia, precio=precio)
    except Exception as exc:  # noqa: BLE001 — el ciclo 24/7 no puede morirse acá
        logger.exception("%s: error evaluando la apertura: %s", ticker, exc)
        return None, f"error evaluando: {exc}"

    if not decision["abrir"]:
        # DEBUG y no INFO a propósito: con un capital chico frente al precio de
        # los papeles, el rechazo es el caso normal y se repetiría en cada ciclo
        # de cada rueda. `abrir_desde_candidatos` deja un resumen por ciclo.
        logger.debug("%s: no se abre — %s", ticker, decision["motivo"])
        return None, decision["motivo"]

    try:
        trade = crud.create_trade(
            db,
            schemas.TradeCreate(
                ticker=ticker,
                tipo=tipo,
                estrategia=estrategia,
                fecha_compra=date.today(),
                cantidad=decision["cantidad"],
                precio_entrada=decision["precio"],
                senal=senal or "Apertura automática (paper)",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s: no se pudo registrar la operación: %s", ticker, exc)
        db.rollback()
        return None, f"no se pudo registrar: {exc}"

    invertido = decision["cantidad"] * decision["precio"]
    logger.info(
        "PAPER: abierta %s x%.0f a $%.2f (%s) — $%.0f",
        ticker,
        decision["cantidad"],
        decision["precio"],
        estrategia,
        invertido,
    )
    _notificar_apertura(trade, invertido)
    return trade, ""


def _notificar_apertura(trade: models.Trade, invertido: float) -> None:
    """Avisa por Telegram. Que falle el aviso no puede deshacer la apertura."""
    mensaje = (
        f"📝 <b>Posición simulada abierta</b>\n"
        f"<b>{notifications.esc(trade.ticker)}</b> · {notifications.esc(trade.estrategia)}\n"
        f"Cantidad: {trade.cantidad:.0f}\n"
        f"Precio de entrada: ${trade.precio_entrada:,.2f}\n"
        f"Invertido: ${invertido:,.0f}\n"
        f"<i>{notifications.esc(trade.senal or '')}</i>\n"
        f"<i>Paper trading: no se envió ninguna orden a IOL.</i>"
    )
    resultado = notifications.send_telegram(mensaje, parse_mode="HTML")
    if not resultado["enviado"]:
        logger.warning("No se pudo avisar la apertura: %s", resultado["motivo"])


def abrir_desde_candidatos(
    db: Session,
    candidatos: list,
    estrategia: str = config.ESTRATEGIA_SWING,
    tipo: str = "CEDEAR",
) -> list:
    """Recorre los candidatos de un escaneo e intenta abrir cada uno.

    Los bonos usan `simbolo` en vez de `ticker`; se acepta cualquiera de los dos.
    """
    abiertos = []
    rechazos: Dict[str, str] = {}
    for candidato in candidatos:
        simbolo = candidato.get("ticker") or candidato.get("simbolo")
        if not simbolo:
            continue
        trade, motivo = _intentar(
            db,
            simbolo,
            estrategia,
            candidato.get("tipo") or tipo,
            _senal_de(candidato),
            None,
        )
        if trade is not None:
            abiertos.append(trade)
        else:
            rechazos[simbolo] = motivo

    if rechazos:
        logger.info(
            "PAPER (%s): %d abierta(s), %d sin tomar — %s",
            tipo,
            len(abiertos),
            len(rechazos),
            "; ".join(f"{k}: {v}" for k, v in list(rechazos.items())[:3])
            + ("…" if len(rechazos) > 3 else ""),
        )
    return abiertos


def _senal_de(candidato: Dict[str, Any]) -> str:
    """Texto corto que queda guardado en la operación, para saber por qué se abrió."""
    partes = []
    if candidato.get("origen"):
        partes.append(str(candidato["origen"]))
    if candidato.get("rsi") is not None:
        partes.append(f"RSI {candidato['rsi']:.1f}")
    if candidato.get("stop_loss") is not None:
        partes.append(f"SL {candidato['stop_loss']:.2f}")
    if candidato.get("take_profit") is not None:
        partes.append(f"TP {candidato['take_profit']:.2f}")
    return " · ".join(partes) if partes else "Apertura automática (paper)"
