"""
Tests de `app/config.py`.

Son pocos y muy chicos a propósito: acá solo se fijan los valores que, si
cambian por accidente, tienen consecuencias caras. El resto de los parámetros se
prueba en el módulo que los usa.
"""
import importlib

from app import config


# ---------- Kill switch ----------


def test_el_kill_switch_arranca_en_modo_fantasma():
    """`MODO_FANTASMA=true` es el default seguro: nunca sale una orden real.

    Si alguien invierte este default, ninguna otra prueba lo detectaría hasta
    que hubiera plata real en juego.
    """
    assert config.MODO_FANTASMA is True


def test_la_variable_vieja_ya_no_existe():
    """`EJECUCION_REAL_HABILITADA` se unificó en `MODO_FANTASMA` (Tarea 11.2).

    Dos variables para lo mismo, con la lógica invertida entre sí, es la forma
    más fácil de habilitar la ejecución real sin querer.
    """
    assert not hasattr(config, "EJECUCION_REAL_HABILITADA")


def test_la_variable_vieja_en_el_entorno_avisa_y_no_habilita_nada(monkeypatch):
    """Ignorarla en silencio sería peligroso: se avisa, pero no se le hace caso."""
    monkeypatch.setenv("EJECUCION_REAL_HABILITADA", "true")

    import warnings

    with warnings.catch_warnings(record=True) as avisos:
        warnings.simplefilter("always")
        recargado = importlib.reload(config)

    assert recargado.MODO_FANTASMA is True, "la variable vieja no puede habilitar nada"
    assert any("EJECUCION_REAL_HABILITADA" in str(a.message) for a in avisos)

    # Dejar el módulo como estaba para no contaminar el resto de la suite.
    monkeypatch.delenv("EJECUCION_REAL_HABILITADA")
    importlib.reload(config)


# ---------- Parámetros agregados por el plan actualizado ----------


def test_el_vencimiento_por_tiempo_esta_configurado():
    """Tarea 3.5: el `SWING_MAX_DIAS` del plan."""
    assert config.SALIDA_SWING_MAX_DIAS > 0


def test_los_parametros_del_rsi_son_coherentes():
    """Tarea 3.7."""
    assert config.RSI_PERIODO > 0
    assert 0 < config.RSI_SOBREVENTA < 50, "la sobreventa vive por debajo del neutro (50)"
    assert 0 < config.LIQUIDEZ_SPREAD_MAX < 1
