"""
Reporte semanal automático (Tarea 12.2).

Arma un resumen de las operaciones **cerradas** en la semana y lo compara contra
lo que venía dando el sistema antes de esa semana ("lo que venía dando el modo
paper trading" del alcance de la tarea). Lo manda por Telegram.

Reglas que respeta:

* No recalcula comisiones: todo sale de `calculations.compute_trade`, que es la
  única fuente de verdad. Este módulo solo agrupa y compara.
* Una operación pertenece a la semana por su `fecha_venta` (cuándo se realizó el
  resultado), no por la de compra.
* La semana es lunes a domingo en horario local — la misma convención que usa
  cualquier resumen de rueda argentino.

Lo dispara `scanner_job.py` los viernes después del cierre, o a mano con
`python scanner_job.py --reporte-semanal`.
"""
import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

from . import crud, models, notifications
from .calculations import BrokerRates, compute_trade
from .database import SessionLocal

logger = logging.getLogger(__name__)

# Cuántas operaciones cerradas se detallan una por una antes de resumir. Con más
# que esto el mensaje se vuelve ilegible en el celular (y roza los 4096 chars).
MAX_OPERACIONES_DETALLADAS = 12


def semana_de(dia: Optional[date] = None) -> tuple[date, date]:
    """Lunes y domingo de la semana que contiene `dia` (hoy por defecto)."""
    dia = dia or date.today()
    lunes = dia - timedelta(days=dia.weekday())
    return lunes, lunes + timedelta(days=6)


def _acumular(trades, rates: BrokerRates) -> Dict[str, Any]:
    """Totales de un conjunto de operaciones cerradas."""
    capital = 0.0
    comisiones = 0.0
    resultado = 0.0
    ganadoras = 0
    perdedoras = 0
    detalle = []

    for t in trades:
        c = compute_trade(t.cantidad, t.precio_entrada, t.precio_salida, rates)
        capital += c.capital_bruto_invertido
        comisiones += c.comision_compra + (c.comision_venta or 0.0)
        resultado += c.resultado_neto or 0.0
        if (c.resultado_neto or 0) > 0:
            ganadoras += 1
        elif (c.resultado_neto or 0) < 0:
            perdedoras += 1
        detalle.append(
            {
                "ticker": t.ticker,
                "fecha_venta": t.fecha_venta,
                "resultado_neto": round(c.resultado_neto or 0.0, 2),
                "rendimiento_neto_pct": c.rendimiento_neto_pct,
                "senal": t.senal or "",
            }
        )

    cerradas = len(detalle)
    return {
        "operaciones": cerradas,
        "ganadoras": ganadoras,
        "perdedoras": perdedoras,
        "capital_invertido": round(capital, 2),
        "comisiones": round(comisiones, 2),
        "resultado_neto": round(resultado, 2),
        # Misma definición que el dashboard: resultado sobre capital invertido.
        "rentabilidad_pct": round(resultado / capital, 4) if capital else 0.0,
        "tasa_acierto_pct": round(ganadoras / cerradas, 4) if cerradas else 0.0,
        "detalle": detalle,
    }


def resumen_semanal(db, hasta: Optional[date] = None) -> Dict[str, Any]:
    """Resumen de la semana de `hasta`, más el acumulado previo para comparar."""
    desde, fin = semana_de(hasta)
    rates = crud._rates_from_config(crud.get_or_create_broker_config(db))

    cerradas = (
        db.query(models.Trade)
        .filter(models.Trade.precio_salida.isnot(None))
        .filter(models.Trade.fecha_venta.isnot(None))
        .order_by(models.Trade.fecha_venta, models.Trade.id)
        .all()
    )

    de_la_semana = [t for t in cerradas if desde <= t.fecha_venta <= fin]
    previas = [t for t in cerradas if t.fecha_venta < desde]
    abiertas = crud.listar_trades_abiertos(db)

    return {
        "desde": desde,
        "hasta": fin,
        "semana": _acumular(de_la_semana, rates),
        "previo": _acumular(previas, rates),
        "posiciones_abiertas": len(abiertas),
        "tickers_abiertos": [t.ticker for t in abiertas],
    }


# ---------- Armado del mensaje ----------


def _pct(valor: Optional[float]) -> str:
    """Fracción (0.0312) a porcentaje con signo (+3.12%). Para resultados y deltas."""
    return "s/d" if valor is None else f"{valor * 100:+.2f}%"


def _pct_simple(valor: Optional[float]) -> str:
    """Igual que `_pct` pero sin signo: una tasa de acierto no es un delta."""
    return "s/d" if valor is None else f"{valor * 100:.2f}%"


def _monto(valor: Optional[float]) -> str:
    return "s/d" if valor is None else f"${valor:,.2f}"


def _comparacion(semana: Dict[str, Any], previo: Dict[str, Any]) -> list[str]:
    """Líneas que comparan la semana contra el acumulado anterior."""
    esc = notifications.esc
    if not previo["operaciones"]:
        return [
            "<i>Primera semana con operaciones cerradas: no hay histórico "
            "contra el que comparar.</i>"
        ]

    delta_rent = semana["rentabilidad_pct"] - previo["rentabilidad_pct"]
    delta_acierto = semana["tasa_acierto_pct"] - previo["tasa_acierto_pct"]
    veredicto = "mejor que" if delta_rent > 0 else ("peor que" if delta_rent < 0 else "igual que")
    return [
        f"• Acumulado previo: {esc(_pct(previo['rentabilidad_pct']))} en "
        f"{previo['operaciones']} operación(es), acierto {esc(_pct_simple(previo['tasa_acierto_pct']))}",
        f"• Esta semana rindió <b>{esc(veredicto)}</b> el promedio previo "
        f"({esc(_pct(delta_rent))} de rentabilidad, {esc(_pct(delta_acierto))} de acierto)",
    ]


def mensaje_reporte_semanal(resumen: Dict[str, Any]) -> str:
    """Mensaje HTML listo para `send_telegram(..., parse_mode="HTML")`."""
    esc = notifications.esc
    semana = resumen["semana"]
    icono = "🟢" if semana["resultado_neto"] > 0 else ("🔴" if semana["resultado_neto"] < 0 else "⚪")

    lineas = [
        f"📊 <b>REPORTE SEMANAL</b> ({esc(resumen['desde'])} → {esc(resumen['hasta'])})",
        "",
    ]

    if not semana["operaciones"]:
        lineas.append("Sin operaciones cerradas esta semana.")
    else:
        lineas += [
            f"{icono} Resultado neto: <b>{esc(_monto(semana['resultado_neto']))}</b> "
            f"({esc(_pct(semana['rentabilidad_pct']))})",
            f"• Operaciones cerradas: {semana['operaciones']} "
            f"({semana['ganadoras']} ganadoras / {semana['perdedoras']} perdedoras)",
            f"• Tasa de acierto: {esc(_pct_simple(semana['tasa_acierto_pct']))}",
            f"• Capital movido: {esc(_monto(semana['capital_invertido']))}",
            f"• Comisiones pagadas: {esc(_monto(semana['comisiones']))}",
            "",
            "<b>Detalle</b>",
        ]
        for op in semana["detalle"][:MAX_OPERACIONES_DETALLADAS]:
            # `rendimiento_neto_pct` es una fracción (0.0847), como en el Excel.
            lineas.append(
                f"• <code>{esc(op['ticker'])}</code> {esc(_monto(op['resultado_neto']))} "
                f"({esc(_pct(op['rendimiento_neto_pct']))})"
            )
        restantes = semana["operaciones"] - MAX_OPERACIONES_DETALLADAS
        if restantes > 0:
            lineas.append(f"• <i>…y {restantes} operación(es) más</i>")

    lineas += ["", "<b>Contra el histórico</b>"] + _comparacion(semana, resumen["previo"])

    abiertas = resumen["posiciones_abiertas"]
    if abiertas:
        tickers = ", ".join(resumen["tickers_abiertos"])
        lineas += ["", f"📌 Posiciones abiertas: {abiertas} ({esc(tickers)})"]

    return "\n".join(lineas)


def enviar_reporte_semanal(db=None, hasta: Optional[date] = None) -> Dict[str, Any]:
    """Arma el reporte y lo manda. Nunca lanza: devuelve el resultado del envío."""
    propia = db is None
    db = db or SessionLocal()
    try:
        resumen = resumen_semanal(db, hasta)
        mensaje = mensaje_reporte_semanal(resumen)
    except Exception as exc:  # noqa: BLE001 — un reporte roto no puede tumbar el job
        logger.exception("No se pudo armar el reporte semanal: %s", exc)
        return {"enviado": False, "motivo": f"Error armando el reporte: {exc}"}
    finally:
        if propia:
            db.close()

    resultado = notifications.send_telegram(mensaje, parse_mode="HTML")
    if not resultado["enviado"]:
        logger.warning("Reporte semanal no enviado: %s", resultado["motivo"])
    return resultado
