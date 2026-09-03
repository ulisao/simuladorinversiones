export type EstadoPosicion = "ABIERTA" | "CERRADA";

export interface Trade {
  id: number;
  ticker: string;
  tipo: string;
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
}

export interface VixEstado {
  vix_actual: number | null;
  vix_previo: number | null;
  cambio_pct: number | null;
  veto: boolean;
  motivo: string | null;
}

export interface SenalCandidato {
  ticker: string;
  precio_entrada: number;
  stop_loss: number;
  take_profit: number;
  pct_riesgo: number;
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
  /** null en operación normal; string cuando el circuit breaker de VIX está activo. */
  veto_global: string | null;
  vix: VixEstado | null;
  candidatos: SenalCandidato[];
  descartados: SenalDescartada[];
}
