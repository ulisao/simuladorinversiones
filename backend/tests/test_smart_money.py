"""
Tests de `app.smart_money` (Tareas 5.1 y 5.2).

Los tests que no llevan marca corren sin internet: se monkeypatchea
`market_data.get_history` y `requests.get` con datos sintéticos, así el
comportamiento de los umbrales y de los caminos de error queda fijado sin
depender de que Yahoo o la SEC estén disponibles.

Los tests marcados con `network` sí le pegan a las APIs reales. Excluirlos con:

    ./venv/Scripts/python.exe -m pytest tests/test_smart_money.py -v -m "not network"
"""
import pandas as pd
import pytest

from app import config, market_data, smart_money


# ---------- Helpers ----------


def _df_volumen(volumenes):
    """DataFrame OHLCV mínimo: solo la columna que mira el RVOL."""
    return pd.DataFrame({"Volume": volumenes})


def _df_rvol(rvol_objetivo, ruedas=25, vol_base=1_000_000):
    """Histórico sintético cuyo RVOL da exactamente `rvol_objetivo`."""
    volumenes = [vol_base] * (ruedas - 1) + [vol_base * rvol_objetivo]
    return _df_volumen(volumenes)


class _RespuestaFalsa:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


def _atom_con_entradas(n):
    entradas = "".join(f"<entry><title>4 - Filing {i}</title></entry>" for i in range(n))
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entradas}</feed>'.encode()


# ---------- _calcular_rvol ----------


def test_rvol_compara_ultima_rueda_contra_las_20_previas():
    # 20 ruedas de 1.000.000 + una última de 3.000.000 -> RVOL 3.0
    df = _df_volumen([1_000_000] * 20 + [3_000_000])
    assert smart_money._calcular_rvol(df) == 3.0


def test_rvol_excluye_la_ultima_rueda_del_promedio():
    # Si la última entrara al promedio, el RVOL daría menos de 3.
    df = _df_volumen([1_000_000] * 24 + [3_000_000])
    assert smart_money._calcular_rvol(df) == 3.0


def test_rvol_none_si_faltan_ruedas():
    assert smart_money._calcular_rvol(_df_volumen([1_000] * 10)) is None


def test_rvol_none_si_no_hay_volumen_operado():
    assert smart_money._calcular_rvol(_df_volumen([0] * 25)) is None


def test_rvol_none_sin_columna_volume():
    assert smart_money._calcular_rvol(pd.DataFrame({"Close": [1.0] * 25})) is None


# ---------- Tarea 5.1: check_unusual_volume (acciones / CEDEARs) ----------


def test_volumen_inusual_detecta_acumulacion_sobre_el_umbral(monkeypatch):
    rvol_alto = config.RVOL_ACUMULACION + 0.5
    monkeypatch.setattr(market_data, "get_history", lambda *a, **k: _df_rvol(rvol_alto))
    es_acumulacion, rvol = smart_money.check_unusual_volume("FAKE")
    assert es_acumulacion is True
    assert rvol == pytest.approx(rvol_alto, abs=0.01)


def test_volumen_inusual_no_marca_acumulacion_bajo_el_umbral(monkeypatch):
    monkeypatch.setattr(market_data, "get_history", lambda *a, **k: _df_rvol(1.0))
    es_acumulacion, rvol = smart_money.check_unusual_volume("FAKE")
    assert es_acumulacion is False
    assert rvol == 1.0


def test_volumen_inusual_devuelve_neutro_si_yahoo_falla(monkeypatch):
    def _explota(*a, **k):
        raise market_data.MarketDataError("Yahoo caído")

    monkeypatch.setattr(market_data, "get_history", _explota)
    assert smart_money.check_unusual_volume("FAKE") == (False, 0.0)


def test_volumen_inusual_devuelve_neutro_sin_historico_suficiente(monkeypatch):
    monkeypatch.setattr(market_data, "get_history", lambda *a, **k: _df_volumen([1_000] * 5))
    assert smart_money.check_unusual_volume("FAKE") == (False, 0.0)


# ---------- Tarea 5.1: check_bond_unusual_volume (bonos) ----------


def test_bonos_usan_su_propio_umbral(monkeypatch):
    # Un RVOL entre el umbral de bonos y el de acciones: acumulación para bonos,
    # no para acciones. Fija que los dos umbrales de config están bien ruteados.
    intermedio = (config.RVOL_ACUMULACION_BONOS + config.RVOL_ACUMULACION) / 2
    monkeypatch.setattr(market_data, "get_history", lambda *a, **k: _df_rvol(intermedio))
    assert smart_money.check_bond_unusual_volume("AL30.BA")[0] is True
    assert smart_money.check_unusual_volume("AL30.BA")[0] is False


def test_bonos_no_bloquean_si_yahoo_no_tiene_datos(monkeypatch):
    """Criterio del manual de bonos: sin histórico en YF se omite el bloqueo."""
    def _explota(*a, **k):
        raise market_data.MarketDataError("Sin datos de mercado para 'AL30.BA'")

    monkeypatch.setattr(market_data, "get_history", _explota)
    assert smart_money.check_bond_unusual_volume("AL30.BA") == (True, 1.0)


def test_bonos_no_bloquean_con_historico_corto(monkeypatch):
    monkeypatch.setattr(market_data, "get_history", lambda *a, **k: _df_volumen([100] * 6))
    assert smart_money.check_bond_unusual_volume("GD30.BA") == (True, 1.0)


# ---------- Tarea 5.2: check_sec_form4_cluster ----------


def test_sec_detecta_cluster_de_form4(monkeypatch):
    n = config.INSIDERS_MIN_FILINGS + 1
    monkeypatch.setattr(
        smart_money.requests, "get", lambda *a, **k: _RespuestaFalsa(_atom_con_entradas(n))
    )
    tiene_insiders, detalle = smart_money.check_sec_form4_cluster("AAPL")
    assert tiene_insiders is True
    assert str(n) in detalle


def test_sec_bajo_el_minimo_no_es_cluster(monkeypatch):
    n = max(config.INSIDERS_MIN_FILINGS - 1, 1)
    monkeypatch.setattr(
        smart_money.requests, "get", lambda *a, **k: _RespuestaFalsa(_atom_con_entradas(n))
    )
    tiene_insiders, _ = smart_money.check_sec_form4_cluster("AAPL")
    assert tiene_insiders is (n >= config.INSIDERS_MIN_FILINGS)


def test_sec_sin_filings(monkeypatch):
    monkeypatch.setattr(
        smart_money.requests, "get", lambda *a, **k: _RespuestaFalsa(_atom_con_entradas(0))
    )
    tiene_insiders, detalle = smart_money.check_sec_form4_cluster("XYZ")
    assert tiene_insiders is False
    assert "Sin filings" in detalle


def test_sec_html_de_error_no_rompe(monkeypatch):
    """EDGAR devuelve HTML con status 200 cuando el ticker no mapea a un CIK."""
    html = b"<html><body>No matching Ticker Symbol.</body></html>"
    monkeypatch.setattr(smart_money.requests, "get", lambda *a, **k: _RespuestaFalsa(html))
    tiene_insiders, detalle = smart_money.check_sec_form4_cluster("NOEXISTE123")
    assert tiene_insiders is False
    assert "CIK" in detalle


def test_sec_status_no_200(monkeypatch):
    monkeypatch.setattr(
        smart_money.requests, "get", lambda *a, **k: _RespuestaFalsa(b"", status_code=403)
    )
    tiene_insiders, detalle = smart_money.check_sec_form4_cluster("AAPL")
    assert tiene_insiders is False
    assert "403" in detalle


def test_sec_error_de_red_no_propaga(monkeypatch):
    def _explota(*a, **k):
        raise OSError("conexión rechazada")

    monkeypatch.setattr(smart_money.requests, "get", _explota)
    tiene_insiders, detalle = smart_money.check_sec_form4_cluster("AAPL")
    assert tiene_insiders is False
    assert "Error SEC API" in detalle


def test_sec_ticker_vacio():
    assert smart_money.check_sec_form4_cluster("  ")[0] is False


def test_sec_manda_user_agent_propio(monkeypatch):
    """Sin User-Agent identificatorio la SEC responde 403."""
    capturado = {}

    def _fake_get(url, headers=None, timeout=None):
        capturado["url"] = url
        capturado["headers"] = headers
        capturado["timeout"] = timeout
        return _RespuestaFalsa(_atom_con_entradas(2))

    monkeypatch.setattr(smart_money.requests, "get", _fake_get)
    smart_money.check_sec_form4_cluster("aapl")

    assert capturado["headers"]["User-Agent"] == smart_money.SEC_USER_AGENT
    assert capturado["timeout"] == 10
    assert "CIK=AAPL" in capturado["url"] and "type=4" in capturado["url"]


# ---------- contexto_smart_money ----------


def test_contexto_devuelve_las_cuatro_claves(monkeypatch):
    monkeypatch.setattr(market_data, "get_history", lambda *a, **k: _df_rvol(2.5))
    monkeypatch.setattr(
        smart_money.requests, "get", lambda *a, **k: _RespuestaFalsa(_atom_con_entradas(5))
    )
    ctx = smart_money.contexto_smart_money("AAPL")
    assert set(ctx) == {"rvol", "es_acumulacion", "insiders_detectados", "insiders_detalle"}
    assert ctx["rvol"] == 2.5
    assert ctx["insiders_detectados"] is True


def test_contexto_es_neutro_y_no_rompe_si_todo_falla(monkeypatch):
    def _explota(*a, **k):
        raise OSError("sin red")

    monkeypatch.setattr(market_data, "get_history", _explota)
    monkeypatch.setattr(smart_money.requests, "get", _explota)
    ctx = smart_money.contexto_smart_money("AAPL")
    assert ctx["rvol"] == 0.0
    assert ctx["es_acumulacion"] is False
    assert ctx["insiders_detectados"] is False
    assert "Error SEC API" in ctx["insiders_detalle"]


def test_contexto_de_bono_omite_la_sec(monkeypatch):
    def _no_llamar(*a, **k):
        raise AssertionError("No hay que consultar la SEC para un bono argentino")

    monkeypatch.setattr(smart_money.requests, "get", _no_llamar)
    monkeypatch.setattr(market_data, "get_history", lambda *a, **k: _df_rvol(2.0))
    ctx = smart_money.contexto_smart_money("AL30.BA", es_bono=True)
    assert ctx["insiders_detectados"] is False
    assert "No aplica" in ctx["insiders_detalle"]


# ---------- Contra las APIs reales ----------


@pytest.mark.network
def test_rvol_real_de_aapl():
    es_acumulacion, rvol = smart_money.check_unusual_volume("AAPL")
    assert isinstance(rvol, float)
    assert 0.0 < rvol < 50.0
    assert es_acumulacion is (rvol >= config.RVOL_ACUMULACION)


@pytest.mark.network
def test_sec_form4_real_de_aapl():
    tiene_insiders, detalle = smart_money.check_sec_form4_cluster("AAPL")
    assert isinstance(detalle, str) and detalle
    assert isinstance(tiene_insiders, bool)


# ---------- Un bono sin datos no puede afirmar acumulación (hallazgo de la 9.4) ----------


def test_un_bono_sin_historico_no_marca_acumulacion(monkeypatch):
    """`check_bond_unusual_volume` devuelve True para decir "no bloquees".

    Ese flag no es una afirmación sobre el mercado: mapearlo a `es_acumulacion`
    marcaba acumulación en TODOS los bonos, que casi nunca tienen histórico en
    Yahoo. Sin datos se informa `False`, no `True`.
    """
    monkeypatch.setattr(
        smart_money, "check_bond_unusual_volume", lambda t: (True, 1.0)
    )

    contexto = smart_money.contexto_smart_money("AL30.BA", es_bono=True)

    assert contexto["rvol"] == 1.0
    assert contexto["es_acumulacion"] is False


def test_un_bono_con_volumen_alto_si_marca_acumulacion(monkeypatch):
    alto = config.RVOL_ACUMULACION_BONOS + 0.5
    monkeypatch.setattr(
        smart_money, "check_bond_unusual_volume", lambda t: (True, alto)
    )

    assert smart_money.contexto_smart_money("AL30.BA", es_bono=True)["es_acumulacion"] is True
