"""
Notificaciones por Telegram (Tarea 7.1).

Único punto del backend que le habla a la API de Telegram. Igual que
`market_data`, `risk_filters` y `smart_money`, este módulo **nunca propaga una
excepción**: si el bot no está configurado, si Telegram responde mal o si se
cae la red, `send_telegram` devuelve `{"enviado": False, "motivo": ...}` y la
operación que lo llamó sigue su curso. Una notificación perdida no puede tirar
abajo el cierre de una operación ni un ciclo del scanner.

Spec: `Manual_Maestro_Bot_Inversion_IA_Completo.docx`, sección 8
(`bot_master.py`, función `send_telegram`).

> Desvío deliberado del manual: el manual usa `parse_mode="Markdown"`. Acá el
> default es texto plano y los armadores de mensaje piden `parse_mode="HTML"`
> explícitamente, escapando todo valor dinámico con `esc()`. Motivo: con
> Markdown legacy, un motivo como `TP1_PARTIAL_50PCT` rompe el parseo (los `_`
> abren cursiva) y Telegram devuelve HTTP 400 — justo en el mensaje que avisa
> que se vendió media posición. Ante un 400 de formato se reintenta una vez en
> texto plano, así el aviso llega igual aunque el formato falle.

## El token viaja en la URL (Tarea 8.3)

La API de Telegram no tiene header de autenticación: el token **es parte de la
ruta** (`/bot<TOKEN>/sendMessage`). Eso convierte a cualquier cosa que imprima
la URL en una filtración. `requests` mete la URL completa en el texto de sus
excepciones de red, y el `motivo` de este módulo sale por `logger` y por la
respuesta de `POST /notificaciones/test`.

```mermaid
flowchart LR
    EXC[requests lanza<br/>ConnectionError/Timeout<br/>con la URL completa] --> RED[_redactar<br/>tapa el token]
    RED --> MOT["motivo"]
    MOT --> LOG[logger.warning]
    MOT --> HTTP[respuesta HTTP<br/>/notificaciones/test]
```

> [!warning] Regla
> Todo texto derivado de una excepción o del cuerpo de una respuesta pasa por
> `_redactar()` antes de entrar en `motivo` o en un log.
"""
import html
import logging
from typing import Any, Dict, Optional

import requests

from . import config

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org"
TIMEOUT_SEG = 10

# Límite duro de la API de Telegram por mensaje. Si nos pasamos, la API rechaza
# el mensaje entero: preferimos recortar y avisar que quedarnos sin aviso.
LARGO_MAXIMO = 4096
MARCA_RECORTE = "\n[…mensaje recortado]"

MENSAJE_DE_PRUEBA = (
    "✅ <b>Simulador de Inversiones IA</b>\n"
    "Prueba de conexión con Telegram (Tarea 7.1).\n"
    "<i>Si ves esto, el bot puede notificarte.</i>"
)


MARCA_REDACTADO = "***TOKEN-OCULTO***"


def esta_configurado() -> bool:
    """True si hay token y chat_id cargados en el entorno."""
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _redactar(texto: str) -> str:
    """Tapa el `TELEGRAM_BOT_TOKEN` en cualquier texto antes de loguearlo o
    devolverlo (Tarea 8.3).

    Se aplica a todo lo que venga de una excepción de `requests` o del cuerpo de
    una respuesta: la URL de Telegram lleva el token adentro, y `requests` la
    incluye entera en el mensaje de sus errores de red.

    También tapa el `chat_id`, que no es un secreto pero identifica el destino.
    """
    salida = str(texto)
    for secreto in (config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID):
        if secreto:
            salida = salida.replace(str(secreto), MARCA_REDACTADO)
    return salida


def esc(valor: Any) -> str:
    """Escapa un valor dinámico para meterlo en un mensaje `parse_mode="HTML"`."""
    return html.escape(str(valor), quote=False)


def _recortar(mensaje: str) -> str:
    if len(mensaje) <= LARGO_MAXIMO:
        return mensaje
    return mensaje[: LARGO_MAXIMO - len(MARCA_RECORTE)] + MARCA_RECORTE


def send_telegram(mensaje: str, parse_mode: Optional[str] = None) -> Dict[str, Any]:
    """Manda un mensaje al chat configurado. Nunca lanza.

    Devuelve `{"enviado": bool, "motivo": str}`. `motivo` explica el fallo
    cuando `enviado` es False, y queda vacío cuando salió bien.
    """
    if not esta_configurado():
        motivo = (
            "Telegram no configurado: faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID "
            "en el entorno (ver .env.example)."
        )
        logger.warning(motivo)
        return {"enviado": False, "motivo": motivo}

    texto = _recortar(mensaje)
    url = f"{TELEGRAM_API_URL}/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload: Dict[str, Any] = {"chat_id": config.TELEGRAM_CHAT_ID, "text": texto}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        respuesta = requests.post(url, json=payload, timeout=TIMEOUT_SEG)
    except Exception as exc:  # noqa: BLE001 — red caída, DNS, timeout, lo que sea
        # `exc` trae la URL completa, y la URL lleva el token: redactar (8.3).
        motivo = _redactar(f"No se pudo contactar a Telegram: {exc}")
        logger.warning(motivo)
        return {"enviado": False, "motivo": motivo}

    if respuesta.status_code == 200:
        return {"enviado": True, "motivo": ""}

    # 400 con parse_mode = casi siempre formato inválido. Reintentamos en texto
    # plano: es preferible un aviso feo a ningún aviso.
    if respuesta.status_code == 400 and parse_mode:
        logger.warning(
            "Telegram rechazó el formato %s, reintentando en texto plano", parse_mode
        )
        return send_telegram(mensaje, parse_mode=None)

    detalle = _detalle_error(respuesta)
    motivo = f"Telegram respondió HTTP {respuesta.status_code}: {detalle}"
    logger.warning(motivo)
    return {"enviado": False, "motivo": motivo}


def _detalle_error(respuesta) -> str:
    """`description` del error de Telegram, o el cuerpo crudo si no viene JSON.

    Siempre redactado: un cuerpo de error o una página de proxy pueden venir con
    la URL del pedido adentro, y esa URL lleva el token.
    """
    try:
        cuerpo = respuesta.json()
    except Exception:  # noqa: BLE001
        return _redactar((getattr(respuesta, "text", "") or "")[:200])
    if isinstance(cuerpo, dict):
        return _redactar(str(cuerpo.get("description") or cuerpo)[:200])
    return _redactar(str(cuerpo)[:200])


# ---------- Armadores de mensaje ----------
# Todos devuelven HTML ya escapado: mandarlos con `parse_mode="HTML"`.


def _pct_de_fraccion(valor: Optional[float]) -> str:
    """`rendimiento_neto_pct` viene como fracción (0.0847), igual que en el Excel.

    Misma convención que `formatPct` del frontend: acá se multiplica por 100 una
    sola vez, al imprimir.
    """
    return "s/d" if valor is None else f"{valor * 100:+.2f}%"


def _monto(valor: Optional[float]) -> str:
    return "s/d" if valor is None else f"${valor:,.2f}"


def mensaje_cierre_operacion(trade) -> str:
    """Resumen de una operación cerrada (Tarea 7.2).

    Espera un `schemas.TradeOut` (o cualquier objeto con esos atributos): usa el
    `resultado_neto` ya calculado por `calculations.py`, nunca recalcula.
    """
    resultado = getattr(trade, "resultado_neto", None)
    rendimiento = getattr(trade, "rendimiento_neto_pct", None)
    gano = (resultado or 0) > 0
    icono = "🟢" if gano else ("🔴" if (resultado or 0) < 0 else "⚪")
    titulo = "POSICIÓN CERRADA CON GANANCIA" if gano else "POSICIÓN CERRADA"

    lineas = [
        f"{icono} <b>{esc(titulo)}</b>",
        f"• Activo: <code>{esc(trade.ticker)}</code> ({esc(trade.tipo)})",
        f"• Cantidad: {esc(f'{trade.cantidad:g}')} papeles",
        f"• Entrada: {esc(_monto(trade.precio_entrada))}"
        f" · Salida: {esc(_monto(trade.precio_salida))}",
        f"• Resultado neto: <b>{esc(_monto(resultado))}</b> ({esc(_pct_de_fraccion(rendimiento))})",
        f"• Comisiones: {esc(_monto(_comisiones_totales(trade)))}",
    ]
    senal = getattr(trade, "senal", None)
    if senal:
        lineas.append(f"• Señal: <i>{esc(senal)}</i>")
    return "\n".join(lineas)


def _comisiones_totales(trade) -> Optional[float]:
    compra = getattr(trade, "comision_compra", None)
    venta = getattr(trade, "comision_venta", None)
    if compra is None:
        return None
    return compra + (venta or 0.0)


def mensaje_senal(candidato: Dict[str, Any]) -> str:
    """Alerta de una señal válida detectada por el scanner (Tarea 10.1).

    Estilo tomado del mensaje de compra del manual, pero en modo sugerencia:
    este sistema **no ejecuta ninguna orden**.
    """
    lineas = [
        "🚀 <b>SEÑAL DETECTADA</b> (sugerencia, no se ejecutó nada)",
        f"• Activo: <code>{esc(candidato.get('ticker'))}</code>",
        f"• Precio de entrada: {esc(_monto(candidato.get('precio_entrada')))}",
        f"• Stop-Loss: {esc(_monto(candidato.get('stop_loss')))}"
        f" (-{esc(candidato.get('pct_riesgo'))}%)",
        f"• Take-Profit: {esc(_monto(candidato.get('take_profit')))} (R/B 1:2)",
    ]

    score = candidato.get("sentimiento_score")
    if score is not None:
        lineas.append(f"• FinBERT: {esc(f'{score:+.2f}')}")

    rvol = candidato.get("rvol")
    if rvol is not None:
        acumulacion = " (acumulación)" if candidato.get("es_acumulacion") else ""
        lineas.append(f"• RVOL: {esc(f'{rvol:.1f}')}x{esc(acumulacion)}")

    if candidato.get("insiders_detectados"):
        lineas.append(f"• Insiders: {esc(candidato.get('insiders_detalle') or 'sí')}")

    return "\n".join(lineas)


def mensaje_veto_global(motivo: str) -> str:
    """Circuit breaker de VIX o régimen de mercado adverso."""
    return (
        "⚠️ <b>ESCANEO BLOQUEADO</b>\n"
        f"{esc(motivo)}\n"
        "<i>No se permiten compras en este ciclo.</i>"
    )
