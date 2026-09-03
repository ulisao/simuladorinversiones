from datetime import date
from typing import Optional
from sqlalchemy.orm import Session

from . import models, schemas
from .calculations import BrokerRates, compute_trade


def get_or_create_broker_config(db: Session) -> models.BrokerConfig:
    cfg = db.query(models.BrokerConfig).first()
    if cfg is None:
        cfg = models.BrokerConfig(id=1)  # usa los defaults del modelo (valores BYMA/CNV estándar)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def update_broker_config(db: Session, data: schemas.BrokerConfigBase) -> models.BrokerConfig:
    cfg = get_or_create_broker_config(db)
    cfg.comision_broker = data.comision_broker
    cfg.derechos_mercado = data.derechos_mercado
    cfg.iva = data.iva
    db.commit()
    db.refresh(cfg)
    return cfg


def _rates_from_config(cfg: models.BrokerConfig) -> BrokerRates:
    return BrokerRates(
        comision_broker=cfg.comision_broker,
        derechos_mercado=cfg.derechos_mercado,
        iva=cfg.iva,
    )


def to_trade_out(trade: models.Trade, rates: BrokerRates) -> schemas.TradeOut:
    computed = compute_trade(trade.cantidad, trade.precio_entrada, trade.precio_salida, rates)
    return schemas.TradeOut(
        id=trade.id,
        ticker=trade.ticker,
        tipo=trade.tipo,
        fecha_compra=trade.fecha_compra,
        cantidad=trade.cantidad,
        precio_entrada=trade.precio_entrada,
        fecha_venta=trade.fecha_venta,
        precio_salida=trade.precio_salida,
        senal=trade.senal,
        capital_bruto_invertido=computed.capital_bruto_invertido,
        comision_compra=computed.comision_compra,
        costo_total_entrada=computed.costo_total_entrada,
        monto_bruto_venta=computed.monto_bruto_venta,
        comision_venta=computed.comision_venta,
        monto_neto_cobrado=computed.monto_neto_cobrado,
        resultado_neto=computed.resultado_neto,
        rendimiento_neto_pct=computed.rendimiento_neto_pct,
        estado_posicion=computed.estado_posicion,
    )


def list_trades(db: Session) -> list[models.Trade]:
    return db.query(models.Trade).order_by(models.Trade.fecha_compra.asc(), models.Trade.id.asc()).all()


def get_trade(db: Session, trade_id: int) -> Optional[models.Trade]:
    return db.query(models.Trade).filter(models.Trade.id == trade_id).first()


def create_trade(db: Session, data: schemas.TradeCreate) -> models.Trade:
    trade = models.Trade(
        ticker=data.ticker.upper().strip(),
        tipo=data.tipo,
        fecha_compra=data.fecha_compra,
        cantidad=data.cantidad,
        precio_entrada=data.precio_entrada,
        senal=data.senal or "",
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def update_trade(db: Session, trade: models.Trade, data: schemas.TradeUpdate) -> models.Trade:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(trade, field, value)
    db.commit()
    db.refresh(trade)
    return trade


def close_trade(db: Session, trade: models.Trade, data: schemas.TradeClose) -> models.Trade:
    trade.fecha_venta = data.fecha_venta
    trade.precio_salida = data.precio_salida
    if data.senal is not None:
        trade.senal = data.senal
    db.commit()
    db.refresh(trade)
    return trade


def delete_trade(db: Session, trade: models.Trade) -> None:
    db.delete(trade)
    db.commit()


def build_dashboard(db: Session) -> schemas.DashboardOut:
    cfg = get_or_create_broker_config(db)
    rates = _rates_from_config(cfg)
    trades = list_trades(db)

    capital_total_invertido = 0.0
    total_comisiones = 0.0
    ganancia_neta_total = 0.0
    cerradas = 0
    ganadoras = 0
    perdedoras = 0

    for t in trades:
        c = compute_trade(t.cantidad, t.precio_entrada, t.precio_salida, rates)
        capital_total_invertido += c.capital_bruto_invertido
        total_comisiones += c.comision_compra
        if c.estado_posicion == "CERRADA":
            total_comisiones += c.comision_venta or 0.0
            ganancia_neta_total += c.resultado_neto or 0.0
            cerradas += 1
            if (c.resultado_neto or 0) > 0:
                ganadoras += 1
            elif (c.resultado_neto or 0) < 0:
                perdedoras += 1

    rentabilidad_pct = (
        ganancia_neta_total / capital_total_invertido if capital_total_invertido else 0.0
    )
    tasa_acierto = (ganadoras / cerradas) if cerradas else 0.0
    veredicto = (
        "SISTEMA RENTABLE - LISTO PARA REAL"
        if ganancia_neta_total > 0
        else "SISTEMA A REVISAR - NO INVERTIR DINERO REAL"
    )

    return schemas.DashboardOut(
        capital_total_invertido=round(capital_total_invertido, 2),
        total_comisiones_pagadas=round(total_comisiones, 2),
        ganancia_perdida_neta_total=round(ganancia_neta_total, 2),
        rentabilidad_neta_ponderada_pct=round(rentabilidad_pct, 4),
        total_operaciones_ejecutadas=cerradas,
        operaciones_ganadoras=ganadoras,
        operaciones_perdedoras=perdedoras,
        tasa_acierto_pct=round(tasa_acierto, 4),
        veredicto=veredicto,
    )


# ---------- Gestión automática de salidas (Tareas 3.5 y 3.6) ----------
#
# La venta parcial del TP1 (50% de la posición) se resuelve **dividiendo la
# operación en dos registros**: uno cerrado por la parte vendida y otro que sigue
# abierto por el remanente. Se eligió así para no tocar `calculations.py`, que es
# la única fuente de verdad de las comisiones y está congelada por tests: cada
# registro se sigue calculando con la fórmula del Excel, sin casos especiales.


def listar_trades_abiertos(db: Session) -> list[models.Trade]:
    """Operaciones sin precio de salida, que son las que el monitor gestiona."""
    return (
        db.query(models.Trade)
        .filter(models.Trade.precio_salida.is_(None))
        .order_by(models.Trade.id)
        .all()
    )


def get_position_state(db: Session, trade_id: int) -> Optional[models.PositionState]:
    return (
        db.query(models.PositionState)
        .filter(models.PositionState.trade_id == trade_id)
        .first()
    )


def guardar_position_state(db: Session, trade_id: int, estado: dict) -> models.PositionState:
    """Persiste el estado del gestor (`PositionManager.a_dict()`) de una operación.

    Sin esto, un reinicio del proceso después del TP1 volvería a armar el stop
    inicial de -3,0% y tiraría abajo el trailing ya ganado.
    """
    fila = get_position_state(db, trade_id)
    if fila is None:
        fila = models.PositionState(trade_id=trade_id)
        db.add(fila)

    fila.is_tp1_hit = bool(estado["is_tp1_hit"])
    fila.is_closed = bool(estado["is_closed"])
    fila.max_price_since_tp1 = float(estado["max_price_since_tp1"])
    fila.current_stop_price = float(estado["current_stop_price"])
    fila.remaining_qty = float(estado["remaining_qty"])

    db.commit()
    db.refresh(fila)
    return fila


def vender_parcial(
    db: Session,
    trade: models.Trade,
    cantidad: float,
    precio_salida: float,
    fecha_venta: date,
    senal: str,
) -> tuple[models.Trade, Optional[models.Trade]]:
    """Vende parte de una posición abierta, partiéndola en dos registros.

    Devuelve `(cerrado, remanente)`. Si `cantidad` cubre toda la posición, cierra
    el registro original y `remanente` es None (no se crea una fila vacía).

    Lanza ValueError si la cantidad no es válida: es preferible fallar acá que
    dejar la base con una posición de cantidad negativa.
    """
    if cantidad <= 0:
        raise ValueError(f"Cantidad a vender inválida: {cantidad}")
    if cantidad > trade.cantidad:
        raise ValueError(
            f"No se puede vender {cantidad}: la posición {trade.id} tiene {trade.cantidad}"
        )

    # Venta total: no hace falta partir nada.
    if cantidad == trade.cantidad:
        trade.precio_salida = precio_salida
        trade.fecha_venta = fecha_venta
        trade.senal = senal
        db.commit()
        db.refresh(trade)
        return trade, None

    cerrado = models.Trade(
        ticker=trade.ticker,
        tipo=trade.tipo,
        fecha_compra=trade.fecha_compra,
        cantidad=cantidad,
        precio_entrada=trade.precio_entrada,
        fecha_venta=fecha_venta,
        precio_salida=precio_salida,
        senal=senal,
    )
    db.add(cerrado)

    trade.cantidad = trade.cantidad - cantidad

    db.commit()
    db.refresh(cerrado)
    db.refresh(trade)
    return cerrado, trade
