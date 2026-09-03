from datetime import date
from typing import Optional
from pydantic import BaseModel, ConfigDict


class BrokerConfigBase(BaseModel):
    comision_broker: float
    derechos_mercado: float
    iva: float


class BrokerConfigOut(BrokerConfigBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    costo_efectivo_por_tramo: float
    costo_efectivo_total_ida_y_vuelta: float


class TradeCreate(BaseModel):
    ticker: str
    tipo: str = "CEDEAR"
    fecha_compra: date
    cantidad: float
    precio_entrada: float
    senal: Optional[str] = ""


class TradeClose(BaseModel):
    fecha_venta: date
    precio_salida: float
    senal: Optional[str] = None


class TradeUpdate(BaseModel):
    ticker: Optional[str] = None
    tipo: Optional[str] = None
    fecha_compra: Optional[date] = None
    cantidad: Optional[float] = None
    precio_entrada: Optional[float] = None
    fecha_venta: Optional[date] = None
    precio_salida: Optional[float] = None
    senal: Optional[str] = None


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    tipo: str
    fecha_compra: date
    cantidad: float
    precio_entrada: float
    fecha_venta: Optional[date]
    precio_salida: Optional[float]
    senal: Optional[str]

    # Campos calculados (no se guardan, se derivan de calculations.py)
    capital_bruto_invertido: float
    comision_compra: float
    costo_total_entrada: float
    monto_bruto_venta: Optional[float]
    comision_venta: Optional[float]
    monto_neto_cobrado: Optional[float]
    resultado_neto: Optional[float]
    rendimiento_neto_pct: Optional[float]
    estado_posicion: str


class DashboardOut(BaseModel):
    capital_total_invertido: float
    total_comisiones_pagadas: float
    ganancia_perdida_neta_total: float
    rentabilidad_neta_ponderada_pct: float
    total_operaciones_ejecutadas: int
    operaciones_ganadoras: int
    operaciones_perdedoras: int
    tasa_acierto_pct: float
    veredicto: str


# ---------- Datos de mercado (Fase 2) ----------


class PrecioMercadoOut(BaseModel):
    ticker: str
    precio: float


# ---------- Riesgo (Fase 4) ----------


class EstadoVixOut(BaseModel):
    vix_actual: Optional[float]
    vix_previo: Optional[float]
    cambio_pct: Optional[float]
    veto: bool
    motivo: str


# ---------- Señales (Fases 3, 4 y 5) ----------


class SenalCandidato(BaseModel):
    ticker: str
    precio_entrada: Optional[float]
    # stop_loss / take_profit son la referencia R/B 1:2 al momento de la señal.
    # La salida real la gestiona PositionManager (TP1 50%, trailing, TP2, 16:50).
    stop_loss: Optional[float]
    take_profit: Optional[float]
    pct_riesgo: Optional[float]
    # Nivel de ruptura congelado, contra el que se mide el anti-chase.
    breakout_level: Optional[float] = None
    # Contexto informativo: no determina si la señal es válida (Tarea 5.2).
    sentimiento_score: Optional[float] = None
    rvol: Optional[float] = None
    es_acumulacion: Optional[bool] = None
    insiders_detectados: Optional[bool] = None
    insiders_detalle: Optional[str] = None


class SenalDescartada(BaseModel):
    ticker: str
    motivo: str


class RegimenMercadoOut(BaseModel):
    """Estado del benchmark (SPY / ^MERV) para el filtro de régimen (Tarea 4.4)."""

    tipo: Optional[str] = None
    ticker: Optional[str] = None
    precio: Optional[float] = None
    sma200: Optional[float] = None
    cambio_diario_pct: Optional[float] = None
    aplica: bool = True
    disponible: bool = True
    motivo: Optional[str] = None
    ruedas: Optional[int] = None


class SenalesOut(BaseModel):
    generado: str
    universo: list[str]
    # No None => un veto global (VIX en pánico o mercado bajo su SMA200) cortó el
    # escaneo antes de evaluar ningún ticker.
    veto_global: Optional[str] = None
    vix: EstadoVixOut
    regimen_mercado: Optional[RegimenMercadoOut] = None
    candidatos: list[SenalCandidato]
    descartados: list[SenalDescartada]
