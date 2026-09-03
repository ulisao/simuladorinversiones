"""
Tests de las fórmulas de comisión (`app/calculations.py`).

Fuente de verdad: `Simulador_Inversiones_IA_Paper_Trading.xlsx`
(hojas "Configuracion Broker" y "Simulador Paper Trading"). Las 5 operaciones
de ejemplo son las mismas que carga `backend/seed.py`.

Los valores esperados están calculados A MANO con las fórmulas del Excel y
escritos como literales: no se recalculan con `compute_trade()`, porque eso no
probaría nada. Se comparan con `pytest.approx(abs=0.01)` porque `compute_trade`
redondea los montos a 2 decimales (y el rendimiento a 4).

Fórmulas del Excel:
    tasa                     = (comision_broker + derechos_mercado) * (1 + iva)
    capital_bruto_invertido  = cantidad * precio_entrada
    comision_compra          = capital_bruto_invertido * tasa
    costo_total_entrada      = capital_bruto_invertido + comision_compra
    monto_bruto_venta        = cantidad * precio_salida
    comision_venta           = monto_bruto_venta * tasa
    monto_neto_cobrado       = monto_bruto_venta - comision_venta
    resultado_neto           = monto_neto_cobrado - costo_total_entrada
    rendimiento_neto_pct     = resultado_neto / costo_total_entrada
"""
import pytest

from app.calculations import BrokerRates, compute_trade

# Valores por defecto del broker (models.BrokerConfig): 0.50% / 0.08% / 21%.
TASAS_DEFAULT = BrokerRates(comision_broker=0.005, derechos_mercado=0.0008, iva=0.21)

# Tolerancias: un centavo para montos, un punto básico para porcentajes.
CENTAVO = 0.01
BPS = 0.0001


# ---------------------------------------------------------------------------
# Tasas del broker
# ---------------------------------------------------------------------------

def test_tasas_por_defecto_dan_07018_por_tramo_y_14036_ida_y_vuelta():
    """(0,50% + 0,08%) * 1,21 = 0,7018% por tramo; el doble ida y vuelta."""
    assert TASAS_DEFAULT.costo_efectivo_por_tramo == pytest.approx(0.007018, abs=1e-9)
    assert TASAS_DEFAULT.costo_efectivo_total_ida_y_vuelta == pytest.approx(
        0.014036, abs=1e-9
    )


# ---------------------------------------------------------------------------
# Las 5 operaciones de ejemplo de la planilla
# ---------------------------------------------------------------------------

def test_operacion_aapl_ganancia_por_take_profit():
    """AAPL: 25 x $12.500 -> $13.450. Take-profit, la operación cierra en verde.

    capital bruto   = 25 * 12500       = 312.500
    comision compra = 312500 * 0.007018=   2.193,125
    costo entrada   =                    314.693,125
    monto venta     = 25 * 13450       = 336.250
    comision venta  = 336250 * 0.007018=   2.359,8025
    neto cobrado    =                    333.890,1975
    resultado neto  =                     19.197,0725
    rendimiento     =                          6,1003%
    """
    r = compute_trade(25, 12500, 13450, TASAS_DEFAULT)

    assert r.estado_posicion == "CERRADA"
    assert r.capital_bruto_invertido == pytest.approx(312_500.00, abs=CENTAVO)
    assert r.comision_compra == pytest.approx(2_193.125, abs=CENTAVO)
    assert r.costo_total_entrada == pytest.approx(314_693.125, abs=CENTAVO)
    assert r.monto_bruto_venta == pytest.approx(336_250.00, abs=CENTAVO)
    assert r.comision_venta == pytest.approx(2_359.8025, abs=CENTAVO)
    assert r.monto_neto_cobrado == pytest.approx(333_890.1975, abs=CENTAVO)
    assert r.resultado_neto == pytest.approx(19_197.0725, abs=CENTAVO)
    assert r.rendimiento_neto_pct == pytest.approx(0.0610025, abs=BPS)


def test_operacion_nvda_perdida_por_stop_loss():
    """NVDA: 15 x $18.200 -> $17.600. Stop-loss; las comisiones agrandan la pérdida.

    costo entrada  = 273000 + 1.915,914 = 274.915,914
    neto cobrado   = 264000 - 1.852,752 = 262.147,248
    resultado neto =                      -12.768,666
    rendimiento    =                           -4,6446%
    """
    r = compute_trade(15, 18200, 17600, TASAS_DEFAULT)

    assert r.estado_posicion == "CERRADA"
    assert r.capital_bruto_invertido == pytest.approx(273_000.00, abs=CENTAVO)
    assert r.comision_compra == pytest.approx(1_915.914, abs=CENTAVO)
    assert r.costo_total_entrada == pytest.approx(274_915.914, abs=CENTAVO)
    assert r.monto_bruto_venta == pytest.approx(264_000.00, abs=CENTAVO)
    assert r.comision_venta == pytest.approx(1_852.752, abs=CENTAVO)
    assert r.monto_neto_cobrado == pytest.approx(262_147.248, abs=CENTAVO)
    assert r.resultado_neto == pytest.approx(-12_768.666, abs=CENTAVO)
    assert r.rendimiento_neto_pct == pytest.approx(-0.0464457, abs=BPS)


def test_operacion_nxe_ruptura_semanal_alcista():
    """NXE: 84 x $9.400 -> $10.150. La operación más grande de la planilla.

    costo entrada  = 789600 + 5.541,4128 = 795.141,4128
    neto cobrado   = 852600 - 5.983,5468 = 846.616,4532
    resultado neto =                        51.475,0404
    rendimiento    =                             6,4737%
    """
    r = compute_trade(84, 9400, 10150, TASAS_DEFAULT)

    assert r.estado_posicion == "CERRADA"
    assert r.capital_bruto_invertido == pytest.approx(789_600.00, abs=CENTAVO)
    assert r.comision_compra == pytest.approx(5_541.4128, abs=CENTAVO)
    assert r.costo_total_entrada == pytest.approx(795_141.4128, abs=CENTAVO)
    assert r.monto_bruto_venta == pytest.approx(852_600.00, abs=CENTAVO)
    assert r.comision_venta == pytest.approx(5_983.5468, abs=CENTAVO)
    assert r.monto_neto_cobrado == pytest.approx(846_616.4532, abs=CENTAVO)
    assert r.resultado_neto == pytest.approx(51_475.0404, abs=CENTAVO)
    assert r.rendimiento_neto_pct == pytest.approx(0.0647370, abs=BPS)


def test_operacion_meli_ganancia_absorbida_por_comisiones():
    """MELI: 8 x $38.500 -> $38.900. Sube +1,04% bruto y aun así pierde plata.

    Es el caso didáctico de la planilla: la suba bruta (+400 por papel = +3.200)
    no alcanza a cubrir el 1,4036% de comisión de ida y vuelta.

    costo entrada  = 308000 + 2.161,544  = 310.161,544
    neto cobrado   = 311200 - 2.184,0016 = 309.015,9984
    resultado neto =                        -1.145,5456
    rendimiento    =                            -0,3693%
    """
    r = compute_trade(8, 38500, 38900, TASAS_DEFAULT)

    assert r.estado_posicion == "CERRADA"
    assert r.capital_bruto_invertido == pytest.approx(308_000.00, abs=CENTAVO)
    assert r.comision_compra == pytest.approx(2_161.544, abs=CENTAVO)
    assert r.costo_total_entrada == pytest.approx(310_161.544, abs=CENTAVO)
    assert r.monto_bruto_venta == pytest.approx(311_200.00, abs=CENTAVO)
    assert r.comision_venta == pytest.approx(2_184.0016, abs=CENTAVO)
    assert r.monto_neto_cobrado == pytest.approx(309_015.9984, abs=CENTAVO)
    assert r.resultado_neto == pytest.approx(-1_145.5456, abs=CENTAVO)
    assert r.rendimiento_neto_pct == pytest.approx(-0.0036934, abs=BPS)
    # El precio subió, pero el resultado neto igual da negativo.
    assert r.monto_bruto_venta > r.capital_bruto_invertido
    assert r.resultado_neto < 0


def test_operacion_tsla_salida_preventiva():
    """TSLA: 12 x $22.100 -> $21.300. Salida preventiva por noticias.

    costo entrada  = 265200 + 1.861,1736 = 267.061,1736
    neto cobrado   = 255600 - 1.793,8008 = 253.806,1992
    resultado neto =                       -13.254,9744
    rendimiento    =                            -4,9633%
    """
    r = compute_trade(12, 22100, 21300, TASAS_DEFAULT)

    assert r.estado_posicion == "CERRADA"
    assert r.capital_bruto_invertido == pytest.approx(265_200.00, abs=CENTAVO)
    assert r.comision_compra == pytest.approx(1_861.1736, abs=CENTAVO)
    assert r.costo_total_entrada == pytest.approx(267_061.1736, abs=CENTAVO)
    assert r.monto_bruto_venta == pytest.approx(255_600.00, abs=CENTAVO)
    assert r.comision_venta == pytest.approx(1_793.8008, abs=CENTAVO)
    assert r.monto_neto_cobrado == pytest.approx(253_806.1992, abs=CENTAVO)
    assert r.resultado_neto == pytest.approx(-13_254.9744, abs=CENTAVO)
    assert r.rendimiento_neto_pct == pytest.approx(-0.0496327, abs=BPS)


# ---------------------------------------------------------------------------
# Casos borde
# ---------------------------------------------------------------------------

def test_posicion_abierta_sin_precio_de_salida():
    """Sin precio de salida la posición queda ABIERTA y los campos de venta en None."""
    r = compute_trade(25, 12500, None, TASAS_DEFAULT)

    assert r.estado_posicion == "ABIERTA"
    # El tramo de compra sí se calcula (mismos números que el caso AAPL cerrado).
    assert r.capital_bruto_invertido == pytest.approx(312_500.00, abs=CENTAVO)
    assert r.comision_compra == pytest.approx(2_193.125, abs=CENTAVO)
    assert r.costo_total_entrada == pytest.approx(314_693.125, abs=CENTAVO)
    # Todo lo que depende de la venta queda sin calcular.
    assert r.monto_bruto_venta is None
    assert r.comision_venta is None
    assert r.monto_neto_cobrado is None
    assert r.resultado_neto is None
    assert r.rendimiento_neto_pct is None


def test_comprar_y_vender_al_mismo_precio_pierde_el_costo_ida_y_vuelta():
    """Salir al precio de entrada nunca es neutro: se pagan los dos tramos.

    100 papeles a $1.000 -> bruto 100.000; comisión por tramo 701,80.
    costo entrada  = 100.701,80
    neto cobrado   =  99.298,20
    resultado neto =  -1.403,60  (= 1,4036% de 100.000)
    """
    r = compute_trade(100, 1000, 1000, TASAS_DEFAULT)

    assert r.costo_total_entrada == pytest.approx(100_701.80, abs=CENTAVO)
    assert r.monto_neto_cobrado == pytest.approx(99_298.20, abs=CENTAVO)
    assert r.resultado_neto == pytest.approx(-1_403.60, abs=CENTAVO)
    assert r.resultado_neto < 0
