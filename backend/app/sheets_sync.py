"""
Sincronización de operaciones cerradas a Google Sheets (Tareas 6.1 y 6.2).

Espeja a la hoja `Trading_Log_IOL` una fila por operación **cerrada** del
simulador, con la estructura exacta de columnas A-K que fija el manual. Es una
bitácora de solo escritura: la app sigue siendo la fuente de verdad, la hoja
existe para poder mirar los números desde el celular sin abrirla.

Spec: `Manual_Integracion_Google_Sheets_Trading_Bot.docx`, secciones 1
(columnas A-K), 3 (cuenta de servicio) y 4 (`sheets_logger.py`).

## Tres desvíos deliberados del manual

| Qué dice el manual | Qué hace este módulo | Por qué |
|---|---|---|
| Comisiones al 0,6% por tramo, hardcodeadas | `calculations.compute_trade()` | El 0,6% del manual no coincide con el Excel: la tasa real es **0,7018%** por tramo (0,5% + 0,08%, +21% IVA). `calculations.py` es la única fuente de verdad matemática (CLAUDE.md), y además lee las tasas que el usuario tenga cargadas en `/config` |
| `oauth2client.ServiceAccountCredentials` | `google.oauth2.service_account.Credentials` | oauth2client está deprecado desde 2018 y **gspread 6 ya no lo acepta**: su `authorize()` espera credenciales de `google-auth` |
| `registrar_compra` + `registrar_venta`, una fila por evento | Una fila por operación cerrada | La Tarea 6.1 pide "una fila por operación cerrada" y leer de la base, no de parámetros sueltos. Dos filas por operación (COMPRA y VENTA) romperían el `CONTAR.SI(...;"CERRADA")` del Dashboard del manual, que asume una fila por operación |

## Cómo no duplica filas

`append_row` siempre agrega al final: la hoja no puede deduplicar sola. La marca
la lleva la base, en `Trade.sincronizado_sheets`, y se escribe **después** de que
la fila entró en la hoja.

```mermaid
flowchart TD
    A[POST /sync/sheets] --> B{¿configurado?}
    B -- no --> Z[sincronizadas=0<br/>+ motivo]
    B -- sí --> C[trades cerrados<br/>con sincronizado_sheets=false]
    C --> D{¿hay?}
    D -- no --> Y[sincronizadas=0<br/>nada pendiente]
    D -- sí --> E[append_rows en lote]
    E -- error --> X[no se marca nada<br/>se reintenta al próximo click]
    E -- ok --> F[marcar sincronizado_sheets=true]
    F --> G[commit]
```

> [!warning] El orden importa
> Se marca en la base **después** del `append_rows`. Si se marcara antes y la
> escritura fallara, esas operaciones no volverían a intentarse nunca y la hoja
> quedaría incompleta para siempre. Al revés, el peor caso es una fila repetida
> si el proceso muere justo entre la escritura y el commit — recuperable a mano,
> a diferencia de un dato que no se escribe nunca.

Igual que `market_data`, `risk_filters`, `smart_money` y `notifications`, este
módulo **nunca propaga una excepción** hacia el endpoint (regla de CLAUDE.md):
toda función devuelve un resultado controlado.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from . import config, crud, models
from .calculations import BrokerRates, compute_trade

logger = logging.getLogger(__name__)

# Scopes mínimos. El manual pide también el scope viejo de "spreadsheets/feeds"
# (API v3, apagada por Google en 2021); con estos dos alcanza y son los que
# documenta gspread hoy.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Encabezados A-K, textual del manual (sección 1). Se usan para crear la hoja si
# está vacía, y el orden define el orden de cada fila.
ENCABEZADOS = [
    "Fecha_Hora",
    "Ticker",
    "Tipo_Operacion",
    "Plazo",
    "Cantidad",
    "Precio_Entrada",
    "Precio_Salida",
    "Comisiones_IOL",
    "Resultado_Neto_$",
    "Rendimiento_%",
    "Estado",
]

# Plazo de liquidación: el sistema opera siempre en Contado Inmediato.
PLAZO_CI = "CI (t0)"


def esta_configurado() -> bool:
    """True si hay ruta de credenciales cargada y el archivo existe."""
    import os

    ruta = config.GOOGLE_CREDENTIALS_PATH
    return bool(ruta) and os.path.isfile(ruta)


def motivo_no_configurado() -> str:
    """Explica en castellano por qué no se puede sincronizar. Nunca vacío."""
    import os

    if not config.GOOGLE_CREDENTIALS_PATH:
        return (
            "Google Sheets no configurado: falta GOOGLE_CREDENTIALS_PATH en el entorno "
            "(ver .env.example). La Fase 6 es opcional; el resto de la app no la necesita."
        )
    if not os.path.isfile(config.GOOGLE_CREDENTIALS_PATH):
        return (
            f"No existe el archivo de credenciales en GOOGLE_CREDENTIALS_PATH "
            f"({config.GOOGLE_CREDENTIALS_PATH}). Ver la Tarea 0.4: hay que bajar el JSON "
            "de la cuenta de servicio desde Google Cloud Console."
        )
    return ""


def _abrir_hoja():
    """Autentica y devuelve la primera pestaña de la hoja. Lanza si algo falla.

    Solo la llaman funciones que ya atrapan todo: no es parte de la API pública.
    """
    import gspread
    from google.oauth2.service_account import Credentials

    credenciales = Credentials.from_service_account_file(
        config.GOOGLE_CREDENTIALS_PATH, scopes=SCOPES
    )
    cliente = gspread.authorize(credenciales)
    hoja = cliente.open(config.SHEETS_NOMBRE_HOJA).sheet1
    return hoja


def _asegurar_encabezados(hoja) -> None:
    """Escribe la fila A1:K1 si la hoja está vacía.

    El manual hace pegar los encabezados a mano. Hacerlo acá evita que la primera
    sincronización contra una hoja recién creada deje los datos sin título.
    """
    try:
        primera = hoja.row_values(1)
    except Exception:  # noqa: BLE001 — hoja vacía o sin permisos de lectura
        primera = []
    if not primera:
        hoja.update(range_name="A1:K1", values=[ENCABEZADOS])


def fila_desde_trade(trade: models.Trade, rates: BrokerRates) -> List[Any]:
    """Arma la fila A-K de una operación cerrada, con las comisiones reales.

    Las comisiones salen de `calculations.compute_trade` — las mismas que muestra
    el dashboard — y no del 0,6% hardcodeado del manual.
    """
    calc = compute_trade(
        cantidad=trade.cantidad,
        precio_entrada=trade.precio_entrada,
        precio_salida=trade.precio_salida,
        rates=rates,
    )

    # Fecha de la venta, que es lo que audita la fila. Si falta (no debería en una
    # cerrada), se cae a la de compra antes que dejar la celda vacía.
    fecha = trade.fecha_venta or trade.fecha_compra
    fecha_hora = datetime(fecha.year, fecha.month, fecha.day).strftime("%Y-%m-%d %H:%M")

    comisiones = (calc.comision_compra or 0.0) + (calc.comision_venta or 0.0)

    # `rendimiento_neto_pct` viene como fracción (0.0847 = 8,47%), igual que en el
    # Excel. La columna J del manual es un porcentaje con símbolo.
    pct = (calc.rendimiento_neto_pct or 0.0) * 100

    return [
        fecha_hora,
        trade.ticker,
        "VENTA",  # la fila audita la operación completa; el evento que la cierra es la venta
        PLAZO_CI,
        trade.cantidad,
        trade.precio_entrada,
        trade.precio_salida,
        round(comisiones, 2),
        calc.resultado_neto,
        f"{round(pct, 2)}%",
        "CERRADA",
    ]


def trades_pendientes(db: Session) -> List[models.Trade]:
    """Operaciones cerradas que todavía no se espejaron a la hoja."""
    return (
        db.query(models.Trade)
        .filter(
            models.Trade.precio_salida.isnot(None),
            models.Trade.sincronizado_sheets.is_(False),
        )
        .order_by(models.Trade.fecha_venta, models.Trade.id)
        .all()
    )


def sincronizar(db: Session) -> Dict[str, Any]:
    """Sube a la hoja las operaciones cerradas pendientes. Nunca lanza.

    Devuelve `{"sincronizadas": int, "pendientes": int, "motivo": str}`.
    `motivo` explica por qué no se sincronizó (queda vacío si salió bien).
    """
    if not esta_configurado():
        motivo = motivo_no_configurado()
        logger.info("Sync a Sheets omitido: %s", motivo)
        # `pendientes` es lo que quedó sin subir, no lo que se intentó: sin
        # credenciales sigue pendiente todo, y el frontend muestra ese número.
        return {"sincronizadas": 0, "pendientes": len(trades_pendientes(db)), "motivo": motivo}

    pendientes = trades_pendientes(db)
    if not pendientes:
        return {"sincronizadas": 0, "pendientes": 0, "motivo": ""}

    cfg = crud.get_or_create_broker_config(db)
    rates = crud._rates_from_config(cfg)

    try:
        hoja = _abrir_hoja()
        _asegurar_encabezados(hoja)
        filas = [fila_desde_trade(t, rates) for t in pendientes]
        # En lote: una sola llamada a la API en vez de N. La cuota gratuita de
        # Sheets es de 60 escrituras por minuto y por usuario — sincronizar 80
        # operaciones de a una fila la agotaría a mitad de camino.
        hoja.append_rows(filas, value_input_option="USER_ENTERED")
    except Exception as exc:  # noqa: BLE001 — red, permisos, hoja inexistente, cuota
        motivo = f"No se pudo escribir en Google Sheets: {exc}"
        logger.warning(motivo)
        # A propósito no se marca nada: se reintenta entero en el próximo click.
        return {"sincronizadas": 0, "pendientes": len(pendientes), "motivo": motivo}

    # Recién ahora, con las filas ya en la hoja, se marcan como sincronizadas.
    for trade in pendientes:
        trade.sincronizado_sheets = True
    db.commit()

    logger.info("Sync a Sheets: %d operación(es) espejadas", len(pendientes))
    return {"sincronizadas": len(pendientes), "pendientes": 0, "motivo": ""}


def estado(db: Session) -> Dict[str, Any]:
    """Cuántas operaciones esperan sincronización, sin tocar la red."""
    return {
        "configurado": esta_configurado(),
        "motivo": motivo_no_configurado(),
        "pendientes": len(trades_pendientes(db)),
    }
