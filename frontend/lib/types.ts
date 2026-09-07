export type EstadoPosicion = "ABIERTA" | "CERRADA";

export interface Trade {
  id: number;
  ticker: string;
  tipo: string;
  /** "SWING" (7 filtros / RSI) o "SMART_MONEY" (consenso 13F). */
  estrategia: string;
  fecha_compra: string;
  cantidad: number;
  precio_entrada: number;
  fecha_venta: string | null;
  precio_salida: number | null;
  senal: string | null;

  capital_bruto_invertido: number;
  comision_compra: number;
  costo_total_entrada: number;
  monto_bruto_venta: number | null;
  comision_venta: number | null;
  monto_neto_cobrado: number | null;
  resultado_neto: number | null;
  rendimiento_neto_pct: number | null;
  estado_posicion: EstadoPosicion;
}

export interface TradeCreateInput {
  ticker: string;
  tipo: string;
  /** "SWING" o "SMART_MONEY". El backend usa "SWING" si no viene. */
  estrategia?: string;
  fecha_compra: string;
  cantidad: number;
  precio_entrada: number;
  senal?: string;
}

export interface TradeCloseInput {
  fecha_venta: string;
  precio_salida: number;
  senal?: string;
}

/** Métricas de una sola estrategia (Tarea 5.5). */
export interface MetricasEstrategia {
  estrategia: string;
  /** ARS que le corresponden según el cupo de `config.py`. */
  cupo_asignado: number;
  capital_total_invertido: number;
  total_comisiones_pagadas: number;
  ganancia_perdida_neta_total: number;
  rentabilidad_neta_ponderada_pct: number;
  total_operaciones_ejecutadas: number;
  operaciones_ganadoras: number;
  operaciones_perdedoras: number;
  tasa_acierto_pct: number;
  posiciones_abiertas: number;
}

export interface Dashboard {
  capital_total_invertido: number;
  total_comisiones_pagadas: number;
  ganancia_perdida_neta_total: number;
  rentabilidad_neta_ponderada_pct: number;
  total_operaciones_ejecutadas: number;
  operaciones_ganadoras: number;
  operaciones_perdedoras: number;
  tasa_acierto_pct: number;
  veredicto: string;
  /** Desglose por estrategia. El total general son los campos de arriba. */
  por_estrategia: MetricasEstrategia[];
}

export interface BrokerConfig {
  id: number;
  comision_broker: number;
  derechos_mercado: number;
  iva: number;
  costo_efectivo_por_tramo: number;
  costo_efectivo_total_ida_y_vuelta: number;
}

export interface PrecioMercado {
  ticker: string;
  precio: number;
  /**
   * Tarea 2.1: hoy el precio sale de yfinance, que devuelve la acción
   * subyacente en USD — NO el CEDEAR en pesos de BYMA. Sirve para el patrón
   * técnico, no para calcular cantidades. Pasa a operable con IOL (Fase 8).
   */
  advertencia: string | null;
  operable: boolean;
}

export interface VixEstado {
  vix_actual: number | null;
  vix_previo: number | null;
  cambio_pct: number | null;
  veto: boolean;
  motivo: string | null;
}

/** Qué fuente disparó la señal (Tarea 3.7). Las dos conviven, no se reemplazan. */
export type OrigenSenal = "7_FILTROS" | "RSI" | "AMBOS";

export interface SenalCandidato {
  ticker: string;
  origen: OrigenSenal;
  precio_entrada: number;
  stop_loss: number;
  take_profit: number;
  pct_riesgo: number;
  /** RSI(14). Viaja aunque la señal la haya disparado la otra fuente. */
  rsi: number | null;
  /** Contexto informativo: puede venir null si el dato no se pudo obtener. */
  sentimiento_score: number | null;
  rvol: number | null;
  es_acumulacion: boolean | null;
  insiders_detectados: boolean | null;
  insiders_detalle: string | null;
}

export interface SenalDescartada {
  ticker: string;
  motivo: string;
}

export interface Senales {
  generado: string;
  /** Tickers que se escanearon en esta corrida. */
  universo: string[];
  /** Aviso fijo de que los precios son referencia técnica, no operables (Tarea 2.1). */
  advertencia_precios: string | null;
  /** null en operación normal; string cuando el circuit breaker de VIX está activo. */
  veto_global: string | null;
  vix: VixEstado | null;
  candidatos: SenalCandidato[];
  descartados: SenalDescartada[];
}

// ---------- Consenso institucional 13F (Tareas 5.3 a 5.5) ----------

export interface SenalSmartMoney {
  ticker: string;
  estrategia: string;
  origen: string;
  precio_entrada: number;
  /** Cuántos fondos distintos coincidieron. */
  consenso: number;
  fondos: string[];
  movimientos: { fondo: string; tipo: string; peso_cartera: number }[];
  peso_promedio: number;
  precio_promedio_fondos: number;
  /** Positivo = el papel ya subió desde el cierre del trimestre del filing. */
  delta_vs_fondos: number;
  stop_loss: number | null;
  take_profit: number | null;
  pct_riesgo: number | null;
  ratio_riesgo_beneficio: number | null;
}

export interface VentaSmartMoney {
  ticker: string;
  estrategia: string;
  fondo: string;
  tipo: string;
  motivo: string;
}

export interface FondoSeguido {
  cik: string;
  nombre: string;
  reporte: string;
  reporte_previo: string;
  presentado: string | null;
  posiciones: number;
  posiciones_mapeadas: number;
}

export interface SenalesSmartMoney {
  generado: string;
  estrategia: string;
  cupo_asignado: number;
  monto_por_posicion: number;
  advertencia_precios: string | null;
  fondos: FondoSeguido[];
  compras: SenalSmartMoney[];
  ventas: VentaSmartMoney[];
  descartados: SenalDescartada[];
  /** Fondos que no se pudieron leer. Nunca se pierde el motivo. */
  errores: string[];
}


// ---------- Cuenta real de IOL (Fase 8) ----------

export interface TenenciaIOL {
  simbolo: string | null;
  descripcion: string | null;
  tipo: string | null;
  moneda: string | null;
  cantidad: number;
  precio_promedio_compra: number;
  ultimo_precio: number;
  valorizado: number;
  ganancia_pct: number;
  ganancia_dinero: number;
}

/** Plata REAL de la cuenta comitente, no el paper trading del simulador. */
export interface SaldoIOL {
  disponible: number;
  moneda: string;
  titulos_valorizados: number;
  total: number;
  posiciones: TenenciaIOL[];
  consultado: string;
}

/** Dólar CCL implícito. Dato de contexto: no veta nada. */
export interface Ccl {
  ccl: number;
  bono_pesos: string;
  precio_pesos: number;
  bono_dolares: string;
  precio_dolares: number;
  fecha_hora: string | null;
}


// ---------- Señales de bonos (Tarea 9.4) ----------

export interface SenalBono {
  /** Ojo: los bonos usan `simbolo`, no `ticker`. */
  simbolo: string;
  tipo: string;
  /** Precio REAL en pesos de BYMA (viene de IOL), no la referencia en USD. */
  precio_entrada: number;
  stop_loss: number;
  take_profit: number;
  pct_riesgo: number;
  ratio_rb: number | null;
  moneda: string | null;
  fecha_hora: string | null;
  lote: number | null;
  lamina_minima: number | null;
  /** True cuando Yahoo no tiene serie del bono: el stop cae al tope estricto. */
  datos_limitados: boolean;
  ema20: number | null;
  atr: number | null;
  detalle: string | null;
  spread: number | null;
  spread_pct: number | null;
  /** False fuera del horario de rueda: el libro viene vacío y no se bloquea. */
  spread_disponible: boolean;
  spread_nota: string | null;
  bid: number | null;
  ask: number | null;
  sentimiento_score: number | null;
  sentimiento_motivo: string | null;
  rvol: number | null;
  es_acumulacion: boolean;
}

export interface BonoDescartado {
  simbolo: string;
  /** CUPON, NOTICIAS, COTIZACION, SPREAD, FILTROS o ERROR. */
  etapa: string;
  motivo: string;
}

export interface EstadoIOL {
  configurado: boolean;
  disponible: boolean;
  motivo: string;
}

export interface SenalesBonos {
  generado: string;
  universo: string[];
  nota_precios: string | null;
  veto_global: string | null;
  iol: EstadoIOL;
  candidatos: SenalBono[];
  descartados: BonoDescartado[];
}
