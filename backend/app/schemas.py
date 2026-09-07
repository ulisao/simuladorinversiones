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
    # "SWING" (7 filtros / RSI) o "SMART_MONEY" (consenso 13F). Ver Tarea 5.5.
    estrategia: str = "SWING"
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
    estrategia: Optional[str] = None
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
    estrategia: str = "SWING"
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


class MetricasEstrategia(BaseModel):
    """Las mismas métricas del dashboard, acotadas a una estrategia (Tarea 5.5)."""

    estrategia: str
    cupo_asignado: float          # ARS que le corresponden según config
    capital_total_invertido: float
    total_comisiones_pagadas: float
    ganancia_perdida_neta_total: float
    rentabilidad_neta_ponderada_pct: float
    total_operaciones_ejecutadas: int
    operaciones_ganadoras: int
    operaciones_perdedoras: int
    tasa_acierto_pct: float
    posiciones_abiertas: int


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
    # Desglose por estrategia. El total general sigue arriba, sin cambios.
    por_estrategia: list[MetricasEstrategia] = []


# ---------- Datos de mercado (Fase 2) ----------


class PrecioMercadoOut(BaseModel):
    ticker: str
    precio: float
    # Precio del subyacente en USD, NO el del CEDEAR en ARS (Tarea 2.1).
    advertencia: Optional[str] = None
    operable: bool = False


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
    # Qué fuente disparó la señal (Tarea 3.7): "7_FILTROS", "RSI" o "AMBOS".
    origen: str = "7_FILTROS"
    # OJO: es el precio del subyacente en USD, no el del CEDEAR en ARS.
    # Ver `advertencia_precios` en SenalesOut.
    precio_entrada: Optional[float]
    # stop_loss / take_profit son la referencia R/B 1:2 al momento de la señal.
    # La salida real la gestiona PositionManager (TP1 50%, trailing, TP2, 16:50).
    stop_loss: Optional[float]
    take_profit: Optional[float]
    pct_riesgo: Optional[float]
    # Nivel de ruptura congelado, contra el que se mide el anti-chase.
    breakout_level: Optional[float] = None
    # RSI(14) del ticker. Viaja siempre que se haya podido calcular, incluso si
    # la señal la disparó la otra fuente.
    rsi: Optional[float] = None
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
    # Advertencia fija sobre la unidad de los precios (Tarea 2.1). El frontend la
    # muestra al lado de cualquier precio que venga de yfinance.
    advertencia_precios: Optional[str] = None
    # No None => un veto global (VIX en pánico o mercado bajo su SMA200) cortó el
    # escaneo antes de evaluar ningún ticker.
    veto_global: Optional[str] = None
    vix: EstadoVixOut
    regimen_mercado: Optional[RegimenMercadoOut] = None
    candidatos: list[SenalCandidato]
    descartados: list[SenalDescartada]


# ---------- Notificaciones (Fase 7) ----------


class NotificacionOut(BaseModel):
    """Resultado de un intento de envío por Telegram.

    `enviado=False` no es un error de la API: el módulo de notificaciones nunca
    lanza, así que el motivo del fallo viaja acá con HTTP 200.
    """

    enviado: bool
    motivo: str = ""


# ---------- Consenso institucional 13F (Fase 5, Tareas 5.3 a 5.5) ----------


class SenalSmartMoney(BaseModel):
    ticker: str
    estrategia: str
    origen: str
    precio_entrada: float
    consenso: int
    fondos: list[str]
    movimientos: list[dict] = []
    peso_promedio: float
    precio_promedio_fondos: float
    # Cuánto se movió el precio desde el cierre del trimestre del filing.
    # Positivo = el papel ya subió desde que el fondo lo compró.
    delta_vs_fondos: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    pct_riesgo: Optional[float] = None
    ratio_riesgo_beneficio: Optional[float] = None


class VentaSmartMoney(BaseModel):
    ticker: str
    estrategia: str
    fondo: str
    tipo: str
    motivo: str


class FondoSeguido(BaseModel):
    cik: str
    nombre: str
    reporte: str
    reporte_previo: str
    presentado: Optional[str] = None
    posiciones: int
    posiciones_mapeadas: int


class SenalesSmartMoneyOut(BaseModel):
    generado: str
    estrategia: str
    cupo_asignado: float
    monto_por_posicion: float
    advertencia_precios: Optional[str] = None
    fondos: list[FondoSeguido]
    compras: list[SenalSmartMoney]
    ventas: list[VentaSmartMoney]
    descartados: list[SenalDescartada]
    # Fondos que no se pudieron leer. Nunca se pierde el motivo.
    errores: list[str] = []


# ---------- Cuenta real de IOL (Fase 8) ----------


class TenenciaIOL(BaseModel):
    """Una posición real de la cuenta comitente."""

    simbolo: Optional[str] = None
    descripcion: Optional[str] = None
    tipo: Optional[str] = None
    moneda: Optional[str] = None
    cantidad: float
    precio_promedio_compra: float
    ultimo_precio: float
    valorizado: float
    ganancia_pct: float
    ganancia_dinero: float


class SaldoIOLOut(BaseModel):
    """Saldo real de la cuenta de IOL (Tarea 8.2).

    Esto es **plata real**, a diferencia de todas las métricas del dashboard,
    que son paper trading. El frontend tiene que dejarlo visualmente claro.
    """

    disponible: float
    moneda: str = "peso_Argentino"
    titulos_valorizados: float = 0.0
    total: float = 0.0
    posiciones: list[TenenciaIOL] = []
    consultado: str


class CclOut(BaseModel):
    """Dólar Contado con Liquidación implícito (Tarea 8.4).

    Dato de contexto macro. **No veta nada**: los manuales lo mencionan como
    variable a monitorear, no como filtro automático.
    """

    ccl: float
    bono_pesos: str
    precio_pesos: float
    bono_dolares: str
    precio_dolares: float
    fecha_hora: Optional[str] = None


# ---------- Señales de bonos (Tarea 9.4) ----------


class SenalBono(BaseModel):
    """Candidato de renta fija. Ojo: la clave es `simbolo`, no `ticker`.

    Es consistente con `fixed_income_filters` y `risk_filters`, que ya usaban
    esa palabra para bonos.
    """

    simbolo: str
    tipo: str
    # Precio REAL en pesos de BYMA (viene de IOL), no la referencia técnica en
    # USD de yfinance que usan los CEDEARs.
    precio_entrada: float
    stop_loss: float
    take_profit: float
    pct_riesgo: float
    ratio_rb: Optional[float] = None
    moneda: Optional[str] = None
    fecha_hora: Optional[str] = None
    lote: Optional[float] = None
    lamina_minima: Optional[float] = None
    # True cuando Yahoo no tiene serie del bono: el stop cae al tope estricto.
    datos_limitados: bool = False
    ema20: Optional[float] = None
    atr: Optional[float] = None
    detalle: Optional[str] = None
    # Fracción (0.004 = 0,4%). `spread_disponible=False` fuera del horario de
    # rueda: el libro viene vacío y el chequeo no bloquea.
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    spread_disponible: bool = False
    spread_nota: Optional[str] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    sentimiento_score: Optional[float] = None
    sentimiento_motivo: Optional[str] = None
    rvol: Optional[float] = None
    es_acumulacion: bool = False


class BonoDescartado(BaseModel):
    simbolo: str
    # En qué paso se cayó: CUPON, NOTICIAS, COTIZACION, SPREAD, FILTROS o ERROR.
    etapa: str
    motivo: str


class EstadoIOL(BaseModel):
    configurado: bool
    disponible: bool
    motivo: str = ""


class SenalesBonosOut(BaseModel):
    generado: str
    universo: list[str]
    nota_precios: Optional[str] = None
    # No None => algo cortó el escaneo entero (IOL caído, por ejemplo).
    veto_global: Optional[str] = None
    iol: EstadoIOL
    candidatos: list[SenalBono]
    descartados: list[BonoDescartado]
