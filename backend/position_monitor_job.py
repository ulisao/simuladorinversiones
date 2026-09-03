"""
Monitor de posiciones abiertas del simulador (Tarea 3.6).

Recorre las operaciones con `estado_posicion="ABIERTA"`, consulta el precio
actual y le pasa cada tick a `PositionManager` (Tarea 3.5). Cuando el gestor
devuelve una acción de venta, la refleja en el simulador:

* venta **parcial** (TP1, 50%)  -> parte la operación en dos registros
  (`crud.vender_parcial`): uno cerrado por lo vendido, otro abierto por el resto.
* venta **total** (SL inicial, TP2, trailing, cierre 16:50) -> cierra el registro.

El estado del gestor se persiste en la tabla `PositionState` después de cada
tick, así un reinicio a mitad de rueda no pierde el TP1 ya cobrado ni el
trailing ya ganado (checklist de la spec, sección 5).

> Esto es **paper trading**: no toca la cuenta real de IOL ni envía órdenes.

Uso:

    # Un solo ciclo (lo que invoca el scanner de la Tarea 10.1)
    python -m position_monitor_job --una-vez

    # Bucle continuo respetando el horario de rueda
    python position_monitor_job.py

    # Prueba fuera de horario de mercado
    python position_monitor_job.py --una-vez --ignorar-horario
"""
import argparse
import logging
import sys
import time as _time_mod
from datetime import date, datetime, time
from typing import Optional

import pytz

from app import crud
from app.config import TZ_BYMA
from app.database import SessionLocal
from app.market_data import MarketDataError, get_last_price
from app.position_manager import PositionManager

logger = logging.getLogger("position_monitor")

# Rueda de BYMA. Fuera de esta ventana no hay precios nuevos que mirar.
RUEDA_APERTURA = time(11, 0)
RUEDA_CIERRE = time(17, 0)

# Cadencia normal y cadencia fina cerca del cierre preventivo de las 16:50: si
# sondeáramos cada 5 minutos podríamos pasar de largo la ventana y quedarnos con
# la posición abierta toda la noche, que es justo lo que la regla evita.
INTERVALO_NORMAL_SEG = 300
INTERVALO_CERCA_DEL_CIERRE_SEG = 60
VENTANA_FINA_DESDE = time(16, 40)


def ahora_art() -> datetime:
    return datetime.now(pytz.timezone(TZ_BYMA))


def es_horario_de_rueda(momento: Optional[datetime] = None) -> bool:
    """True si estamos en rueda de BYMA (lunes a viernes, 11:00-17:00 ART)."""
    momento = momento or ahora_art()
    if momento.weekday() >= 5:  # sábado / domingo
        return False
    return RUEDA_APERTURA <= momento.time() <= RUEDA_CIERRE


def intervalo_actual(momento: Optional[datetime] = None) -> int:
    """Segundos hasta el próximo sondeo, más corto cerca de las 16:50."""
    momento = momento or ahora_art()
    if VENTANA_FINA_DESDE <= momento.time() <= RUEDA_CIERRE:
        return INTERVALO_CERCA_DEL_CIERRE_SEG
    return INTERVALO_NORMAL_SEG


def _notificar(mensaje: str) -> None:
    """Aviso de cada acción del gestor.

    Hoy solo loguea. La Tarea 7.1 (Telegram) todavía no está hecha porque falta
    el token del bot; cuando exista, acá va el `send_telegram(mensaje)` y no hay
    que tocar nada más de este archivo.
    """
    logger.info(mensaje)


def _gestor_de(trade, estado_guardado: Optional[dict]) -> PositionManager:
    """Reconstruye el gestor de una operación, restaurando su estado si existe."""
    base = {
        "symbol": trade.ticker,
        "entry_price": trade.precio_entrada,
        "total_qty": trade.cantidad,
    }
    if estado_guardado:
        base.update(estado_guardado)
    return PositionManager.desde_dict(base)


def procesar_trade(db, trade, precio: float, momento: datetime) -> Optional[dict]:
    """Corre un tick sobre una operación y aplica la acción que devuelva.

    Devuelve la acción aplicada, o None si no hubo nada que hacer.
    """
    fila = crud.get_position_state(db, trade.id)
    estado_guardado = None
    if fila is not None:
        estado_guardado = {
            "is_tp1_hit": fila.is_tp1_hit,
            "is_closed": fila.is_closed,
            "max_price_since_tp1": fila.max_price_since_tp1,
            "current_stop_price": fila.current_stop_price,
            "remaining_qty": fila.remaining_qty,
        }

    gestor = _gestor_de(trade, estado_guardado)
    accion = gestor.on_tick(precio, momento)

    # Sin acción: igual se persiste, porque el trailing pudo haber subido.
    if accion is None:
        crud.guardar_position_state(db, trade.id, gestor.a_dict())
        return None

    cantidad = float(accion["qty"])
    motivo = f"{accion['reason']} ({accion['profit_pct']:+.2f}%)"

    # `total_qty // 2` puede dar 0 con posiciones de 1 papel: no hay orden que
    # mandar, pero el gestor igual pasó a estado post-TP1 y hay que guardarlo.
    if cantidad <= 0:
        crud.guardar_position_state(db, trade.id, gestor.a_dict())
        logger.warning(
            "%s: %s sin cantidad que vender (posición de %s papeles)",
            trade.ticker, accion["reason"], trade.cantidad,
        )
        return accion

    fecha = momento.date() if momento else date.today()
    cerrado, remanente = crud.vender_parcial(db, trade, cantidad, precio, fecha, motivo)

    crud.guardar_position_state(db, trade.id, gestor.a_dict())

    _notificar(
        f"[{trade.ticker}] {accion['reason']} — vendidos {cantidad:g} a ${precio:,.2f} "
        f"({accion['profit_pct']:+.2f}%)"
        + (f" · quedan {remanente.cantidad:g}" if remanente else " · posición cerrada")
    )
    return accion


def ciclo(ignorar_horario: bool = False) -> list[dict]:
    """Un barrido completo sobre las posiciones abiertas."""
    momento = ahora_art()

    if not ignorar_horario and not es_horario_de_rueda(momento):
        logger.debug("Fuera de rueda (%s), no se sondea", momento.strftime("%a %H:%M"))
        return []

    acciones: list[dict] = []
    db = SessionLocal()
    try:
        abiertos = crud.listar_trades_abiertos(db)
        if not abiertos:
            logger.debug("No hay posiciones abiertas")
            return []

        for trade in abiertos:
            try:
                precio = get_last_price(trade.ticker)
            except MarketDataError as exc:
                # Un ticker sin datos no puede frenar el resto del barrido: si
                # abortáramos acá, una posición rota dejaría a las demás sin
                # gestionar justo en la ventana del cierre preventivo.
                logger.warning("%s: sin precio (%s)", trade.ticker, exc)
                continue

            try:
                accion = procesar_trade(db, trade, precio, momento)
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s: error procesando el tick: %s", trade.ticker, exc)
                db.rollback()
                continue

            if accion:
                acciones.append(accion)
    finally:
        db.close()

    return acciones


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor de posiciones abiertas del simulador")
    parser.add_argument("--una-vez", action="store_true", help="corre un solo ciclo y sale")
    parser.add_argument(
        "--ignorar-horario",
        action="store_true",
        help="sondea aunque el mercado esté cerrado (para probar)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.una_vez:
        acciones = ciclo(ignorar_horario=args.ignorar_horario)
        logger.info("Ciclo terminado: %d acción(es)", len(acciones))
        return 0

    logger.info("Monitor iniciado (rueda %s-%s ART)", RUEDA_APERTURA, RUEDA_CIERRE)
    while True:
        try:
            ciclo(ignorar_horario=args.ignorar_horario)
        except KeyboardInterrupt:
            logger.info("Monitor detenido")
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error en el ciclo: %s", exc)
        _time_mod.sleep(intervalo_actual())


if __name__ == "__main__":
    sys.exit(main())
