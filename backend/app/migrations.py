"""
Migraciones mínimas del esquema SQLite.

`Base.metadata.create_all` crea tablas que no existen, pero **no toca las que ya
están**: una columna nueva en un modelo no aparece sola en una base con datos.
Hasta ahora eso no importaba porque el esquema no había cambiado; la Tarea 5.5
agrega `trades.estrategia` y `simulador.db` ya tiene operaciones cargadas.

No se trae Alembic para esto: son ALTER TABLE de una línea sobre SQLite, y una
herramienta de migraciones con su directorio de versiones sería más máquina de la
que el problema pide. Si el esquema empieza a moverse seguido, ahí sí conviene.

Cada migración es idempotente: mira el estado real de la tabla antes de tocar
nada, así arrancar el backend dos veces seguidas no falla.
"""
import logging
from typing import List

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _columnas(engine: Engine, tabla: str) -> List[str]:
    inspector = inspect(engine)
    if tabla not in inspector.get_table_names():
        return []
    return [c["name"] for c in inspector.get_columns(tabla)]


def _agregar_columna(engine: Engine, tabla: str, columna: str, definicion: str) -> bool:
    """Agrega una columna si falta. Devuelve True si la agregó."""
    if not _columnas(engine, tabla):
        return False  # la tabla todavía no existe: la crea create_all, ya con la columna
    if columna in _columnas(engine, tabla):
        return False

    with engine.begin() as conexion:
        conexion.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}"))
    logger.info("Migración: %s.%s agregada", tabla, columna)
    return True


def migrar(engine: Engine) -> List[str]:
    """Corre todas las migraciones pendientes. Devuelve las que aplicó.

    Se llama al levantar la app, después de `create_all`.
    """
    aplicadas = []

    # Tarea 5.5: cada operación sabe con qué estrategia se abrió.
    # Las que ya estaban cargadas son todas de swing técnico — es la única
    # estrategia que existía cuando se registraron.
    if _agregar_columna(
        engine, "trades", "estrategia", "VARCHAR NOT NULL DEFAULT 'SWING'"
    ):
        aplicadas.append("trades.estrategia")

    # Tarea 6.2: marca de sincronización a Google Sheets. Las operaciones que ya
    # estaban cargadas arrancan en 0 (no sincronizadas): la hoja está vacía la
    # primera vez, así que corresponde que el primer sync las suba todas.
    if _agregar_columna(
        engine, "trades", "sincronizado_sheets", "BOOLEAN NOT NULL DEFAULT 0"
    ):
        aplicadas.append("trades.sincronizado_sheets")

    return aplicadas
