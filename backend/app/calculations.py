"""
Réplica exacta, en Python, de las fórmulas del Excel:
- Simulador_Inversiones_IA_Paper_Trading.xlsx
  hoja 'Configuracion Broker' (celdas B5:B9) y 'Simulador Paper Trading'.

Mantener esto como única fuente de verdad de los cálculos: tanto el endpoint
de listado de operaciones como el de dashboard llaman a estas funciones.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class BrokerRates:
    comision_broker: float   # ej 0.005  -> 0.50%
    derechos_mercado: float  # ej 0.0008 -> 0.08%
    iva: float                # ej 0.21   -> 21%

    @property
    def costo_efectivo_por_tramo(self) -> float:
        # Excel: =(B5+B6)*(1+B7)
        return (self.comision_broker + self.derechos_mercado) * (1 + self.iva)

    @property
    def costo_efectivo_total_ida_y_vuelta(self) -> float:
        # Excel: =B8*2
        return self.costo_efectivo_por_tramo * 2


@dataclass
class TradeComputed:
    capital_bruto_invertido: float
    comision_compra: float
    costo_total_entrada: float
    monto_bruto_venta: Optional[float]
    comision_venta: Optional[float]
    monto_neto_cobrado: Optional[float]
    resultado_neto: Optional[float]
    rendimiento_neto_pct: Optional[float]
    estado_posicion: str  # ABIERTA | CERRADA


def compute_trade(
    cantidad: float,
    precio_entrada: float,
    precio_salida: Optional[float],
    rates: BrokerRates,
) -> TradeComputed:
    tasa = rates.costo_efectivo_por_tramo

    # Excel: G = E*F ; H = G*tasa ; I = G+H
    capital_bruto_invertido = cantidad * precio_entrada
    comision_compra = capital_bruto_invertido * tasa
    costo_total_entrada = capital_bruto_invertido + comision_compra

    if precio_salida is None:
        return TradeComputed(
            capital_bruto_invertido=round(capital_bruto_invertido, 2),
            comision_compra=round(comision_compra, 2),
            costo_total_entrada=round(costo_total_entrada, 2),
            monto_bruto_venta=None,
            comision_venta=None,
            monto_neto_cobrado=None,
            resultado_neto=None,
            rendimiento_neto_pct=None,
            estado_posicion="ABIERTA",
        )

    # Excel: M = E*K ; N = M*tasa ; O = M-N ; P = O-I ; Q = P/I
    monto_bruto_venta = cantidad * precio_salida
    comision_venta = monto_bruto_venta * tasa
    monto_neto_cobrado = monto_bruto_venta - comision_venta
    resultado_neto = monto_neto_cobrado - costo_total_entrada
    rendimiento_neto_pct = (
        resultado_neto / costo_total_entrada if costo_total_entrada else 0.0
    )

    return TradeComputed(
        capital_bruto_invertido=round(capital_bruto_invertido, 2),
        comision_compra=round(comision_compra, 2),
        costo_total_entrada=round(costo_total_entrada, 2),
        monto_bruto_venta=round(monto_bruto_venta, 2),
        comision_venta=round(comision_venta, 2),
        monto_neto_cobrado=round(monto_neto_cobrado, 2),
        resultado_neto=round(resultado_neto, 2),
        rendimiento_neto_pct=round(rendimiento_neto_pct, 4),
        estado_posicion="CERRADA",
    )
