"""
Job de escaneo periódico (Tarea 10.1).

Corre solo, sin depender de que alguien abra la app: cada 10 minutos escanea el
universo llamando a `signals.escanear_senales()` **en proceso** (no por HTTP), y
escanea también el universo de bonos (Tarea 9.4) y manda por Telegram
cualquier señal que no haya notificado antes ese día. En
paralelo invoca el monitor de posiciones abiertas (`position_monitor_job`,
Tarea 3.6), con cadencia fina cerca del cierre preventivo de las 16:50.

> Este job **no ejecuta ninguna orden**: solo sugiere y notifica. El kill switch
> `MODO_FANTASMA` sigue en `true` y la Fase 11 todavía no existe.

## Flujo de un ciclo

```mermaid
flowchart TD
    T{{schedule}} --> H{¿rueda BYMA?<br/>L-V 11:00-17:00}
    H -- no --> FIN[No hace nada]
    H -- sí --> SEN[signals.escanear_senales]
    SEN --> V{¿veto global?}
    V -- sí --> AVISO[Telegram: escaneo bloqueado<br/>una vez por día]
    V -- no --> NUEVAS{¿señal no notificada hoy?}
    NUEVAS -- sí --> TG[Telegram: señal detectada]
    NUEVAS -- no --> SKIP[Se saltea, ya se avisó]
    H -- sí --> POS[position_monitor_job.ciclo]
    POS --> TG2[Telegram: ventas del gestor]
```

## Deduplicación

Un set en memoria con las claves `TICKER@YYYY-MM-DD` de lo ya notificado. Se
vacía al cambiar el día, así una señal que sigue vigente el martes vuelve a
avisar, pero no se repite doce veces el mismo lunes.

Uso:

    python scanner_job.py                          # bucle 24/7, respeta horario
    python scanner_job.py --una-vez                # un ciclo y sale
    python scanner_job.py --una-vez --ignorar-horario   # prueba fuera de rueda
    python scanner_job.py --reporte-semanal        # manda el reporte y sale
"""
import argparse
import logging
import sys
import time as _time_mod
from datetime import date, datetime
from typing import Any, Optional

import schedule

import position_monitor_job
from app import bond_signals, config, notifications, paper_trader, signals, weekly_report
from app.database import SessionLocal

logger = logging.getLogger("scanner")

# Cadencia del escaneo de señales, tal cual el manual
# (`schedule.every(10).minutes.do(...)`, sección 8).
INTERVALO_SENALES_MIN = 10

# El monitor de posiciones se consulta cada minuto, pero él decide si corresponde
# sondear: `position_monitor_job.intervalo_actual()` devuelve 300 s normalmente y
# 60 s a partir de las 16:40, para no perderse el cierre preventivo de las 16:50.
INTERVALO_LATIDO_MIN = 1

# Reporte semanal (Tarea 12.2): viernes después del cierre de rueda.
#
# OJO: `schedule` mide la hora del reloj del sistema, no la de `TZ_BYMA`. El
# horario de rueda sí se chequea en ART (`position_monitor_job.ahora_art`), pero
# este "17:30" es hora local del servidor. Por eso la Tarea 10.2 pide dejar el
# VPS en `America/Argentina/Buenos_Aires`: con esa zona horaria las dos cosas
# coinciden y el reporte sale media hora después de la campana.
REPORTE_SEMANAL_DIA = "friday"
REPORTE_SEMANAL_HORA = "17:30"

# Escaneo de bonos (Tarea 9.4). Habilitado desde el 2026-09-07: `IOLClient`
# (Tarea 8.1) ya trae las cotizaciones reales en pesos. Se puede apagar acá si
# alguna vez conviene correr solo el universo de CEDEARs.
ESCANEO_BONOS_HABILITADO = True


# ---------- Estado de deduplicación ----------

_notificadas: set[str] = set()
_dia_del_set: Optional[date] = None


def _clave(ticker: str, dia: date) -> str:
    return f"{ticker}@{dia.isoformat()}"


def _reset_si_cambio_el_dia(dia: date) -> None:
    """Vacía el set al cambiar de jornada: una señal vigente mañana vuelve a avisar."""
    global _dia_del_set
    if _dia_del_set != dia:
        _notificadas.clear()
        _dia_del_set = dia


def ya_notificada(ticker: str, dia: date) -> bool:
    return _clave(ticker, dia) in _notificadas


def marcar_notificada(ticker: str, dia: date) -> None:
    _notificadas.add(_clave(ticker, dia))


def reiniciar_estado() -> None:
    """Solo para los tests: deja el módulo como recién importado."""
    global _dia_del_set
    _notificadas.clear()
    _dia_del_set = None


# ---------- Ciclos ----------


def _abrir_en_paper(candidatos: list[dict], estrategia: str, tipo: str) -> list:
    """Abre las posiciones simuladas de los candidatos nuevos, si está habilitado.

    Va en su propia sesión y atrapa todo: que falle la apertura no puede tumbar
    el ciclo de escaneo, que ya hizo lo suyo (detectar y avisar).
    """
    if not paper_trader.habilitado() or not candidatos:
        return []

    db = SessionLocal()
    try:
        return paper_trader.abrir_desde_candidatos(
            db, candidatos, estrategia=estrategia, tipo=tipo
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error abriendo posiciones en paper: %s", exc)
        return []
    finally:
        db.close()


def ciclo_senales(ignorar_horario: bool = False) -> list[dict]:
    """Escanea y notifica lo nuevo. Devuelve los candidatos efectivamente avisados."""
    momento = position_monitor_job.ahora_art()

    if not ignorar_horario and not position_monitor_job.es_horario_de_rueda(momento):
        logger.debug("Fuera de rueda (%s), no se escanea", momento.strftime("%a %H:%M"))
        return []

    hoy = momento.date()
    _reset_si_cambio_el_dia(hoy)

    try:
        resultado = signals.escanear_senales()
    except Exception as exc:  # noqa: BLE001 — el bucle 24/7 no puede morirse acá
        logger.exception("Error escaneando señales: %s", exc)
        return []

    # Un veto global (VIX en pánico, mercado bajo su SMA200) se avisa una vez por
    # día: se usa la misma clave de dedup que un ticker, con un nombre reservado.
    veto = resultado.get("veto_global")
    if veto:
        if not ya_notificada("__VETO_GLOBAL__", hoy):
            _enviar(notifications.mensaje_veto_global(veto))
            marcar_notificada("__VETO_GLOBAL__", hoy)
        logger.info("Escaneo bloqueado: %s", veto)
        return []

    avisados = []
    for candidato in resultado.get("candidatos", []):
        ticker = candidato.get("ticker")
        if not ticker or ya_notificada(ticker, hoy):
            continue
        _enviar(notifications.mensaje_senal(candidato), parse_mode="HTML")
        marcar_notificada(ticker, hoy)
        avisados.append(candidato)

    logger.info(
        "Escaneo CEDEARs: %d candidato(s), %d nuevo(s) notificado(s), %d descartado(s)",
        len(resultado.get("candidatos", [])),
        len(avisados),
        len(resultado.get("descartados", [])),
    )

    # La apertura va después del aviso: si algo falla abriendo, el aviso ya salió
    # y la señal no se pierde.
    abiertas = _abrir_en_paper(avisados, config.ESTRATEGIA_SWING, "CEDEAR")
    if abiertas:
        logger.info("PAPER: %d posición(es) abiertas de CEDEARs", len(abiertas))

    bonos = _ciclo_bonos(hoy)
    abiertas_bonos = _abrir_en_paper(bonos, config.ESTRATEGIA_SWING, "BONO")
    if abiertas_bonos:
        logger.info("PAPER: %d posición(es) abiertas de bonos", len(abiertas_bonos))

    avisados.extend(bonos)
    return avisados


def _ciclo_bonos(hoy: date) -> list[dict]:
    """Escaneo de renta fija (Tarea 9.4), con la misma deduplicación.

    Va aparte del de CEDEARs a propósito: son universos, filtros y fuentes de
    precio distintos, y si IOL se cae los bonos tienen que fallar solos sin
    llevarse puesto el escaneo de acciones, que no depende de IOL.
    """
    if not ESCANEO_BONOS_HABILITADO:
        return []

    try:
        resultado = bond_signals.escanear_senales_bonos()
    except Exception as exc:  # noqa: BLE001 — el bucle 24/7 no puede morirse acá
        logger.exception("Error escaneando bonos: %s", exc)
        return []

    veto = resultado.get("veto_global")
    if veto:
        # Clave de dedup propia: un problema con IOL no tiene por qué silenciar
        # el aviso de un veto de VIX, ni al revés.
        if not ya_notificada("__VETO_BONOS__", hoy):
            _enviar(notifications.mensaje_veto_global(f"Bonos: {veto}"), parse_mode="HTML")
            marcar_notificada("__VETO_BONOS__", hoy)
        logger.info("Escaneo de bonos bloqueado: %s", veto)
        return []

    avisados = []
    for candidato in resultado.get("candidatos", []):
        # Los bonos usan `simbolo`, no `ticker`.
        simbolo = candidato.get("simbolo")
        if not simbolo or ya_notificada(simbolo, hoy):
            continue
        _enviar(
            notifications.mensaje_senal({**candidato, "ticker": simbolo}),
            parse_mode="HTML",
        )
        marcar_notificada(simbolo, hoy)
        avisados.append(candidato)

    logger.info(
        "Escaneo bonos: %d candidato(s), %d nuevo(s) notificado(s), %d descartado(s)",
        len(resultado.get("candidatos", [])),
        len(avisados),
        len(resultado.get("descartados", [])),
    )
    return avisados


# Última vez que se corrió el monitor de posiciones, para respetar su cadencia.
_ultimo_monitor: Optional[datetime] = None


def ciclo_posiciones(ignorar_horario: bool = False, forzar: bool = False) -> list[dict]:
    """Latido del monitor de posiciones, respetando su propia cadencia.

    `position_monitor_job.ciclo` ya notifica cada venta por Telegram; acá solo se
    decide *cuándo* corresponde llamarlo.
    """
    global _ultimo_monitor
    momento = position_monitor_job.ahora_art()

    if not forzar and _ultimo_monitor is not None:
        transcurrido = (momento - _ultimo_monitor).total_seconds()
        if transcurrido < position_monitor_job.intervalo_actual(momento):
            return []

    _ultimo_monitor = momento
    try:
        return position_monitor_job.ciclo(ignorar_horario=ignorar_horario)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error en el monitor de posiciones: %s", exc)
        return []


def ciclo(ignorar_horario: bool = False) -> dict[str, Any]:
    """Un ciclo completo: señales nuevas + monitor de posiciones."""
    senales = ciclo_senales(ignorar_horario=ignorar_horario)
    acciones = ciclo_posiciones(ignorar_horario=ignorar_horario, forzar=True)
    return {"senales_notificadas": senales, "acciones_gestor": acciones}


def _enviar(mensaje: str, parse_mode: Optional[str] = None) -> None:
    resultado = notifications.send_telegram(mensaje, parse_mode=parse_mode)
    if not resultado["enviado"]:
        logger.warning("No se pudo notificar por Telegram: %s", resultado["motivo"])


# ---------- Programación ----------


def programar(ignorar_horario: bool = False) -> None:
    """Registra los tres jobs en `schedule`."""
    schedule.every(INTERVALO_SENALES_MIN).minutes.do(
        ciclo_senales, ignorar_horario=ignorar_horario
    )
    schedule.every(INTERVALO_LATIDO_MIN).minutes.do(
        ciclo_posiciones, ignorar_horario=ignorar_horario
    )
    getattr(schedule.every(), REPORTE_SEMANAL_DIA).at(REPORTE_SEMANAL_HORA).do(
        weekly_report.enviar_reporte_semanal
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Escaneo periódico de señales + monitor de posiciones (no ejecuta órdenes)"
    )
    parser.add_argument("--una-vez", action="store_true", help="corre un solo ciclo y sale")
    parser.add_argument(
        "--ignorar-horario",
        action="store_true",
        help="escanea aunque el mercado esté cerrado (para probar)",
    )
    parser.add_argument(
        "--reporte-semanal",
        action="store_true",
        help="manda el reporte semanal (Tarea 12.2) y sale",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.reporte_semanal:
        resultado = weekly_report.enviar_reporte_semanal()
        logger.info("Reporte semanal: %s", resultado)
        return 0 if resultado["enviado"] else 1

    if args.una_vez:
        resumen = ciclo(ignorar_horario=args.ignorar_horario)
        logger.info(
            "Ciclo terminado: %d señal(es) notificada(s), %d acción(es) del gestor",
            len(resumen["senales_notificadas"]),
            len(resumen["acciones_gestor"]),
        )
        return 0

    _enviar(
        "🟢 <b>Scanner iniciado</b>\n"
        f"Escaneo cada {INTERVALO_SENALES_MIN} min en rueda BYMA "
        f"({position_monitor_job.RUEDA_APERTURA}-{position_monitor_job.RUEDA_CIERRE} ART).\n"
        "<i>Modo solo sugerir: no se ejecuta ninguna orden.</i>",
        parse_mode="HTML",
    )
    programar(ignorar_horario=args.ignorar_horario)
    logger.info("Scanner iniciado (señales cada %d min)", INTERVALO_SENALES_MIN)

    while True:
        try:
            schedule.run_pending()
        except KeyboardInterrupt:
            logger.info("Scanner detenido")
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error en el planificador: %s", exc)
        _time_mod.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
