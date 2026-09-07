"""
Tests de `app/position_manager.py`.

Todo offline y determinístico: los precios se arman a mano y la hora se inyecta
por `timestamp`, así la regla de las 16:50 se prueba sin depender del reloj ni de
la zona horaria de la máquina donde corran los tests.

Con entrada en 100,00 y los parámetros de `config`, los umbrales quedan redondos:

    SL inicial   97,00   (-3,0%)
    TP1         104,50   (+4,5%)
    piso        103,50   (+3,5%)
    TP2         108,00   (+8,0%)
"""
from datetime import date, datetime

import pytest
import pytz

from app import config
from app import position_manager as pm
from app.position_manager import PositionManager


ENTRADA = 100.0
CANTIDAD = 100

# Horas ART inyectables: una en plena rueda y otra sobre el cierre preventivo.
HORA_RUEDA = datetime(2026, 9, 1, 11, 30)
HORA_CIERRE = datetime(2026, 9, 1, 16, 50)


def manager(entry_price: float = ENTRADA, total_qty: float = CANTIDAD) -> PositionManager:
    """PositionManager estándar sobre el que corren casi todos los casos."""
    return PositionManager("AAPL", entry_price, total_qty)


def llevar_a_post_tp1(gestor: PositionManager) -> dict:
    """Dispara el TP1 y devuelve la orden, para arrancar los casos de la fase 3."""
    return gestor.on_tick(104.5, HORA_RUEDA)


# ---------- Construcción y parámetros ----------


def test_el_estado_inicial_sale_de_config():
    gestor = manager()

    assert gestor.sl_initial_pct == config.SALIDA_SL_INICIAL_PCT
    assert gestor.tp1_pct == config.SALIDA_TP1_PCT
    assert gestor.trailing_pullback == config.SALIDA_TRAILING_PULLBACK
    assert gestor.min_guaranteed_pct == config.SALIDA_PISO_GARANTIZADO_PCT
    assert gestor.tp2_pct == config.SALIDA_TP2_PCT
    assert gestor.market_close_cutoff == config.SALIDA_HORA_CIERRE_PREVENTIVO
    assert gestor.tz_nombre == config.TZ_BYMA


def test_el_stop_inicial_es_la_entrada_menos_3_por_ciento():
    gestor = manager()

    assert gestor.current_stop_price == pytest.approx(97.0)
    assert gestor.is_tp1_hit is False
    assert gestor.is_closed is False
    assert gestor.remaining_qty == CANTIDAD
    assert gestor.max_price_since_tp1 == 0.0


@pytest.mark.parametrize("entrada,cantidad", [(0, 100), (-1.0, 100), (100.0, 0), (100.0, -5)])
def test_entrada_o_cantidad_no_positivas_levantan_error(entrada, cantidad):
    with pytest.raises(ValueError):
        PositionManager("AAPL", entrada, cantidad)


def test_precio_invalido_en_el_tick_levanta_error():
    """Un 0 del feed dispararía un stop-loss espurio: mejor que reviente el tick."""
    with pytest.raises(ValueError):
        manager().on_tick(0.0, HORA_RUEDA)


# ---------- Secuencia completa: entrada → TP1 → trailing que sube → salida ----------


def test_secuencia_completa_de_las_cuatro_fases():
    """
    El recorrido del criterio de aceptación, en orden:
    entrada sin acción → TP1 parcial → nueva suba que levanta el stop →
    retroceso de 1,2% que liquida el remanente.
    """
    gestor = manager()
    acciones = []

    # Fase 1: el precio se mueve dentro del rango, no pasa nada.
    for precio in (100.0, 101.3, 103.9, 104.49):
        assert gestor.on_tick(precio, HORA_RUEDA) is None

    # Fase 2: toca +4,5% → vende el 50% y arma el trailing en el piso garantizado.
    tp1 = gestor.on_tick(104.5, HORA_RUEDA)
    acciones.append(tp1["reason"])

    assert tp1["action"] == "SELL"
    assert tp1["reason"] == pm.MOTIVO_TP1_PARCIAL == "TP1_PARTIAL_50PCT"
    assert tp1["qty"] == 50
    assert tp1["price"] == pytest.approx(104.5)
    assert tp1["profit_pct"] == pytest.approx(4.5)
    # 104,5 * (1 - 0,012) = 103,246 < piso 103,5 → manda el piso garantizado.
    assert tp1["new_stop_price"] == pytest.approx(103.5)
    assert gestor.current_stop_price == pytest.approx(103.5)
    assert gestor.is_tp1_hit is True
    assert gestor.is_closed is False
    assert gestor.remaining_qty == 50

    # Fase 3: nueva suba → el stop persigue al precio.
    assert gestor.on_tick(106.0, HORA_RUEDA) is None
    assert gestor.max_price_since_tp1 == pytest.approx(106.0)
    assert gestor.current_stop_price == pytest.approx(104.728)  # 106 * 0,988

    # Fase 4: retroceso de 1,2% desde el pico → liquida el remanente.
    trailing = gestor.on_tick(104.7, HORA_RUEDA)
    acciones.append(trailing["reason"])

    assert trailing["action"] == "SELL"
    assert trailing["reason"] == pm.MOTIVO_TRAILING == "TRAILING_STOP_1.2PCT_HIT"
    assert trailing["qty"] == 50
    assert trailing["profit_pct"] == pytest.approx(4.7)
    assert gestor.is_closed is True
    assert gestor.remaining_qty == 0

    assert acciones == ["TP1_PARTIAL_50PCT", "TRAILING_STOP_1.2PCT_HIT"]


def test_el_trailing_es_monotono_creciente_y_no_baja_con_el_precio():
    gestor = manager()
    llevar_a_post_tp1(gestor)

    gestor.on_tick(106.0, HORA_RUEDA)
    stop_en_el_pico = gestor.current_stop_price
    assert stop_en_el_pico == pytest.approx(104.728)

    # El precio baja pero no toca el stop: el stop NO acompaña la baja.
    assert gestor.on_tick(105.0, HORA_RUEDA) is None
    assert gestor.current_stop_price == pytest.approx(stop_en_el_pico)
    assert gestor.max_price_since_tp1 == pytest.approx(106.0)

    # Vuelve a subir pero sin superar el pico: tampoco recalcula.
    assert gestor.on_tick(105.8, HORA_RUEDA) is None
    assert gestor.current_stop_price == pytest.approx(stop_en_el_pico)

    # Supera el pico: recién ahí el stop sube.
    assert gestor.on_tick(107.0, HORA_RUEDA) is None
    assert gestor.current_stop_price == pytest.approx(105.716)  # 107 * 0,988
    assert gestor.current_stop_price > stop_en_el_pico


def test_el_piso_garantizado_no_se_pierde_aunque_el_precio_recorte_enseguida():
    """Post-TP1 el peor caso posible para el remanente es +3,5%."""
    gestor = manager()
    llevar_a_post_tp1(gestor)

    # Se toca el piso exacto que calculó el gestor: 100 * 1,035 da 103,49999999999999
    # en punto flotante, así que un 103.5 literal quedaría un ULP por encima.
    assert gestor.current_stop_price == pytest.approx(103.5)
    salida = gestor.on_tick(gestor.current_stop_price, HORA_RUEDA)

    assert salida["reason"] == pm.MOTIVO_TRAILING
    assert salida["profit_pct"] == pytest.approx(3.5)


# ---------- Fase 1: stop-loss inicial ----------


def test_stop_loss_inicial_liquida_el_100_por_ciento_antes_del_tp1():
    gestor = manager()

    assert gestor.on_tick(98.0, HORA_RUEDA) is None

    salida = gestor.on_tick(97.0, HORA_RUEDA)

    assert salida["action"] == "SELL"
    assert salida["reason"] == pm.MOTIVO_STOP_INICIAL == "INITIAL_STOP_LOSS_HIT"
    assert salida["qty"] == CANTIDAD
    assert salida["profit_pct"] == pytest.approx(-3.0)
    assert gestor.is_closed is True
    assert gestor.is_tp1_hit is False
    assert gestor.remaining_qty == 0


def test_despues_del_tp1_el_stop_inicial_queda_cancelado():
    """El precio vuelve por debajo de 97 pero ya no existe el SL0: sale por trailing."""
    gestor = manager()
    llevar_a_post_tp1(gestor)

    salida = gestor.on_tick(96.0, HORA_RUEDA)

    assert salida["reason"] == pm.MOTIVO_TRAILING
    assert salida["qty"] == 50


# ---------- Fase 4: TP2 techo ----------


def test_tp2_techo_cierra_el_remanente_en_mas_8_por_ciento():
    gestor = manager()
    llevar_a_post_tp1(gestor)

    assert gestor.on_tick(107.0, HORA_RUEDA) is None

    salida = gestor.on_tick(108.0, HORA_RUEDA)

    assert salida["action"] == "SELL"
    assert salida["reason"] == pm.MOTIVO_TP2_TECHO == "TP2_CEILING_HIT"
    assert salida["qty"] == 50
    assert salida["profit_pct"] == pytest.approx(8.0)
    assert gestor.is_closed is True
    assert gestor.remaining_qty == 0


def test_el_tp2_no_dispara_antes_del_tp1():
    """Un salto directo a +8% cobra primero el parcial; el techo queda para el tick siguiente."""
    gestor = manager()

    primero = gestor.on_tick(108.0, HORA_RUEDA)
    assert primero["reason"] == pm.MOTIVO_TP1_PARCIAL

    segundo = gestor.on_tick(108.0, HORA_RUEDA)
    assert segundo["reason"] == pm.MOTIVO_TP2_TECHO


# ---------- Cierre preventivo 16:50 hs ART ----------


def test_cierre_preventivo_1650_liquida_el_remanente():
    gestor = manager()
    llevar_a_post_tp1(gestor)
    gestor.on_tick(106.0, HORA_RUEDA)

    salida = gestor.on_tick(105.5, HORA_CIERRE)

    assert salida["action"] == "SELL"
    assert salida["reason"] == pm.MOTIVO_CIERRE_PREVENTIVO == "END_OF_DAY_CUTOFF_1650"
    assert salida["qty"] == 50
    assert salida["price"] == pytest.approx(105.5)
    assert salida["profit_pct"] == pytest.approx(5.5)
    assert salida["note"] == pm.NOTA_CIERRE_PREVENTIVO
    assert gestor.is_closed is True
    assert gestor.remaining_qty == 0


def test_el_cierre_preventivo_no_dispara_si_todavia_no_cobro_tp1():
    """Sin TP1 la posición sigue viva con su SL0: la regla de las 16:50 no aplica."""
    gestor = manager()

    assert gestor.on_tick(101.0, HORA_CIERRE) is None
    assert gestor.is_closed is False
    assert gestor.remaining_qty == CANTIDAD

    # Y a esa misma hora el SL0 sigue funcionando.
    salida = gestor.on_tick(96.0, HORA_CIERRE)
    assert salida["reason"] == pm.MOTIVO_STOP_INICIAL


def test_el_cierre_preventivo_no_dispara_un_minuto_antes():
    gestor = manager()
    llevar_a_post_tp1(gestor)

    assert gestor.on_tick(105.0, datetime(2026, 9, 1, 16, 49, 59)) is None
    assert gestor.is_closed is False

    salida = gestor.on_tick(105.0, datetime(2026, 9, 1, 16, 50, 0))
    assert salida["reason"] == pm.MOTIVO_CIERRE_PREVENTIVO


def test_el_cierre_preventivo_tiene_prioridad_sobre_el_trailing():
    """A las 16:50 se liquida por horario aunque el precio también toque el stop."""
    gestor = manager()
    llevar_a_post_tp1(gestor)

    salida = gestor.on_tick(103.0, HORA_CIERRE)

    assert salida["reason"] == pm.MOTIVO_CIERRE_PREVENTIVO


def test_un_timestamp_con_zona_horaria_se_convierte_a_hora_art():
    """19:50 UTC son las 16:50 en Buenos Aires (UTC-3)."""
    gestor = manager()
    llevar_a_post_tp1(gestor)

    en_rueda = pytz.utc.localize(datetime(2026, 9, 1, 19, 49))
    sobre_el_cierre = pytz.utc.localize(datetime(2026, 9, 1, 19, 50))

    assert gestor.on_tick(105.0, en_rueda) is None

    salida = gestor.on_tick(105.0, sobre_el_cierre)
    assert salida["reason"] == pm.MOTIVO_CIERRE_PREVENTIVO


# ---------- Posición cerrada ----------


def test_una_posicion_cerrada_ignora_los_ticks_siguientes():
    gestor = manager()
    gestor.on_tick(97.0, HORA_RUEDA)

    assert gestor.is_closed is True
    assert gestor.on_tick(120.0, HORA_RUEDA) is None
    assert gestor.on_tick(50.0, HORA_CIERRE) is None
    assert gestor.remaining_qty == 0


# ---------- Cantidad impar ----------


def test_cantidad_impar_deja_el_papel_de_mas_en_el_remanente():
    """7 papeles: el TP1 vende 3 (7 // 2) y quedan 4 para el trailing."""
    gestor = manager(total_qty=7)

    tp1 = gestor.on_tick(104.5, HORA_RUEDA)
    assert tp1["qty"] == 3
    assert gestor.remaining_qty == 4

    salida = gestor.on_tick(103.4, HORA_RUEDA)
    assert salida["reason"] == pm.MOTIVO_TRAILING
    assert salida["qty"] == 4
    assert gestor.remaining_qty == 0
    assert tp1["qty"] + salida["qty"] == 7


def test_cantidad_de_un_solo_papel_no_vende_nada_en_el_tp1():
    """Con 1 papel el parcial es 0: la posición entera sale recién por trailing/TP2."""
    gestor = manager(total_qty=1)

    tp1 = gestor.on_tick(104.5, HORA_RUEDA)
    assert tp1["qty"] == 0
    assert gestor.remaining_qty == 1
    assert gestor.is_tp1_hit is True

    salida = gestor.on_tick(108.0, HORA_RUEDA)
    assert salida["reason"] == pm.MOTIVO_TP2_TECHO
    assert salida["qty"] == 1


# ---------- Persistencia del estado ----------


def test_el_estado_sobrevive_un_reinicio_a_mitad_de_rueda():
    gestor = manager()
    llevar_a_post_tp1(gestor)
    gestor.on_tick(106.0, HORA_RUEDA)

    restaurado = PositionManager.desde_dict(gestor.a_dict())

    assert restaurado.symbol == "AAPL"
    assert restaurado.entry_price == pytest.approx(100.0)
    assert restaurado.total_qty == CANTIDAD
    assert restaurado.is_tp1_hit is True
    assert restaurado.is_closed is False
    assert restaurado.max_price_since_tp1 == pytest.approx(106.0)
    assert restaurado.current_stop_price == pytest.approx(104.728)
    assert restaurado.remaining_qty == 50

    # Y sigue la rueda donde la dejó: el trailing ya ganado no se pierde.
    salida = restaurado.on_tick(104.7, HORA_RUEDA)
    assert salida["reason"] == pm.MOTIVO_TRAILING
    assert salida["qty"] == 50


def test_desde_dict_acepta_el_subconjunto_que_guarda_position_state():
    """La tabla guarda 5 campos de estado; el resto sale del Trade y de config."""
    restaurado = PositionManager.desde_dict(
        {
            "symbol": "NVDA",
            "entry_price": 100.0,
            "total_qty": 100,
            "is_tp1_hit": True,
            "is_closed": False,
            "max_price_since_tp1": 106.0,
            "current_stop_price": 104.728,
            "remaining_qty": 50,
        }
    )

    assert restaurado.tp1_pct == config.SALIDA_TP1_PCT
    assert restaurado.on_tick(104.7, HORA_RUEDA)["reason"] == pm.MOTIVO_TRAILING


def test_desde_dict_sin_estado_arranca_como_posicion_recien_abierta():
    restaurado = PositionManager.desde_dict(
        {"symbol": "KO", "entry_price": 100.0, "total_qty": 10}
    )

    assert restaurado.is_tp1_hit is False
    assert restaurado.is_closed is False
    assert restaurado.remaining_qty == 10
    assert restaurado.current_stop_price == pytest.approx(97.0)


def test_desde_dict_sin_los_datos_minimos_levanta_error():
    with pytest.raises(ValueError):
        PositionManager.desde_dict({"symbol": "KO", "total_qty": 10})


def test_a_dict_incluye_todo_lo_necesario_para_reconstruir():
    esperadas = {
        "symbol",
        "entry_price",
        "total_qty",
        "remaining_qty",
        "is_tp1_hit",
        "is_closed",
        "max_price_since_tp1",
        "current_stop_price",
        "sl_initial_pct",
        "tp1_pct",
        "trailing_pullback",
        "min_guaranteed_pct",
        "tp2_pct",
        "entry_date",
        "max_dias",
    }

    assert set(manager().a_dict()) == esperadas


def test_el_estado_guardado_conserva_los_parametros_de_la_posicion():
    """Si config cambia a mitad de rueda, la posición vieja se restaura con SU config."""
    gestor = PositionManager("MELI", 100.0, 100, tp1_pct=0.06, tp2_pct=0.12)

    restaurado = PositionManager.desde_dict(gestor.a_dict())

    assert restaurado.tp1_pct == pytest.approx(0.06)
    assert restaurado.tp2_pct == pytest.approx(0.12)
    assert restaurado.on_tick(104.5, HORA_RUEDA) is None  # con 6% todavía no hay TP1
    assert restaurado.on_tick(106.0, HORA_RUEDA)["reason"] == pm.MOTIVO_TP1_PARCIAL


# ---------- Vencimiento por tiempo (Tarea 3.5) ----------
#
# La posición se compró el 2026-09-01. Con `SALIDA_SWING_MAX_DIAS = 10`, el
# día 11 ya está vencida.

COMPRA = date(2026, 9, 1)
DIA_9 = datetime(2026, 9, 10, 11, 30)   # 9 días corridos: todavía viva
DIA_10 = datetime(2026, 9, 11, 11, 30)  # 10 días corridos: vencida


def manager_con_fecha(**kwargs) -> PositionManager:
    return PositionManager("AAPL", ENTRADA, CANTIDAD, entry_date=COMPRA, **kwargs)


def test_sin_entry_date_la_posicion_nunca_vence():
    """Una posición sin fecha de compra no puede vencer: no inventamos la fecha."""
    gestor = manager()  # sin entry_date

    assert gestor.on_tick(101.0, datetime(2027, 1, 1, 11, 30)) is None
    assert gestor.is_closed is False


def test_antes_del_plazo_no_pasa_nada():
    gestor = manager_con_fecha()

    assert gestor.on_tick(101.0, DIA_9) is None
    assert gestor.is_closed is False


def test_cumplido_el_plazo_se_liquida_a_mercado():
    gestor = manager_con_fecha()

    orden = gestor.on_tick(101.0, DIA_10)

    assert orden["reason"] == pm.MOTIVO_VENCIMIENTO
    assert orden["action"] == pm.ACCION_VENTA
    assert orden["qty"] == CANTIDAD, "vence la posición entera, no la mitad"
    assert orden["note"] == pm.NOTA_VENCIMIENTO
    assert gestor.is_closed is True


def test_el_stop_loss_le_gana_al_vencimiento_en_el_mismo_tick():
    """Si el precio ya está en el SL, manda el SL: es la estrategia real."""
    gestor = manager_con_fecha()

    orden = gestor.on_tick(96.0, DIA_10)  # -4%, por debajo del SL de -3%

    assert orden["reason"] == pm.MOTIVO_STOP_INICIAL


def test_el_tp1_le_gana_al_vencimiento_en_el_mismo_tick():
    gestor = manager_con_fecha()

    orden = gestor.on_tick(104.5, DIA_10)  # +4,5%, dispara TP1

    assert orden["reason"] == pm.MOTIVO_TP1_PARCIAL


def test_una_posicion_que_ya_cobro_tp1_no_vence_por_tiempo():
    """Post-TP1 la gestiona el trailing: el vencimiento solo barre lo dormido."""
    gestor = manager_con_fecha()
    llevar_a_post_tp1(gestor)

    # Precio quieto justo arriba del stop, mucho después del plazo.
    assert gestor.on_tick(104.0, DIA_10) is None
    assert gestor.is_closed is False


def test_max_dias_en_cero_desactiva_la_regla():
    gestor = manager_con_fecha(max_dias=0)

    assert gestor.on_tick(101.0, datetime(2027, 1, 1, 11, 30)) is None


def test_el_plazo_se_puede_configurar_por_posicion():
    gestor = manager_con_fecha(max_dias=3)

    assert gestor.on_tick(101.0, datetime(2026, 9, 3, 11, 30)) is None   # 2 días
    assert gestor.on_tick(101.0, datetime(2026, 9, 4, 11, 30))["reason"] == pm.MOTIVO_VENCIMIENTO


def test_el_vencimiento_sobrevive_a_un_reinicio():
    """`entry_date` y `max_dias` viajan en el estado serializado."""
    gestor = manager_con_fecha(max_dias=5)

    restaurado = PositionManager.desde_dict(gestor.a_dict())

    assert restaurado.entry_date == COMPRA
    assert restaurado.max_dias == 5
    assert restaurado.on_tick(101.0, datetime(2026, 9, 6, 11, 30))["reason"] == pm.MOTIVO_VENCIMIENTO
