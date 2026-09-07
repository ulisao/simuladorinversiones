"""
Modelos de datos (tablas).

Trade guarda solo los datos "crudos" que un humano carga (igual que en el Excel
original: fecha, ticker, cantidad, precios de entrada/salida). Todo lo demás
(comisiones, resultado neto, rendimiento %) se calcula al vuelo con las mismas
fórmulas que la planilla — así nunca se desincroniza un valor guardado con la
config de comisiones vigente.
"""
from sqlalchemy import Column, Integer, String, Float, Date
from .database import Base


class BrokerConfig(Base):
    """Espejo de la hoja 'Configuracion Broker' del Excel. Fila única (id=1)."""

    __tablename__ = "broker_config"

    id = Column(Integer, primary_key=True, default=1)
    comision_broker = Column(Float, nullable=False, default=0.005)       # 0.50%
    derechos_mercado = Column(Float, nullable=False, default=0.0008)     # 0.08%
    iva = Column(Float, nullable=False, default=0.21)                    # 21%


class Trade(Base):
    """Espejo de una fila de la hoja 'Simulador Paper Trading'."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String, nullable=False, index=True)
    tipo = Column(String, nullable=False, default="CEDEAR")  # CEDEAR | ACCION | BONO
    fecha_compra = Column(Date, nullable=False)
    cantidad = Column(Float, nullable=False)
    precio_entrada = Column(Float, nullable=False)
    fecha_venta = Column(Date, nullable=True)
    precio_salida = Column(Float, nullable=True)
    senal = Column(String, nullable=True, default="")  # motivo / señal IA, ej. "Take-Profit +7.6%"

    # Con qué estrategia se abrió la operación (Tarea 5.5). Cada una tiene su
    # propio cupo de capital (`config.CUPOS_POR_ESTRATEGIA`), así que el
    # dashboard tiene que poder separarlas: mezclarlas en un solo número haría
    # imposible saber cuál de las dos rinde.
    estrategia = Column(
        String, nullable=False, index=True, server_default="SWING", default="SWING"
    )


# ---------- Gestión de salidas (PositionManager) ----------

from datetime import datetime, timezone  # noqa: E402  (import local de esta sección)


def _ahora_utc() -> datetime:
    """`datetime.utcnow` está deprecado y sale en una versión futura de Python."""
    return datetime.now(timezone.utc)

from sqlalchemy import Boolean, DateTime, ForeignKey  # noqa: E402


class PositionState(Base):
    """
    Estado del gestor de salidas de una operación abierta.

    Existe para que el seguimiento no se pierda si el proceso se reinicia a mitad
    de rueda: sin esto, un reinicio después del TP1 volvería a armar el stop
    inicial de -3,0% y tiraría abajo el trailing ya ganado.

    Es una fila por operación (`trade_id` único), y va aparte de `Trade` a
    propósito: `Trade` guarda lo que carga un humano, esto guarda lo que calcula
    el bot. Los campos espejan los atributos de estado de
    `app.position_manager.PositionManager` (ver `a_dict()` / `desde_dict()`).

    Spec: `Pasar_ulises_31_de_agosto.docx`, sección 5 ("Persistencia de Estado").
    """

    __tablename__ = "position_states"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=False, unique=True, index=True)

    is_tp1_hit = Column(Boolean, nullable=False, default=False)   # ya se cobró el parcial del 50%
    is_closed = Column(Boolean, nullable=False, default=False)    # posición ya liquidada
    max_price_since_tp1 = Column(Float, nullable=False, default=0.0)  # high-water mark post-TP1
    current_stop_price = Column(Float, nullable=False)            # stop vigente (SL0 o trailing)
    remaining_qty = Column(Float, nullable=False)                 # cantidad todavía en cartera

    actualizado_en = Column(
        DateTime, nullable=False, default=_ahora_utc, onupdate=_ahora_utc
    )
