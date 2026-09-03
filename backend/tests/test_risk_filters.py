"""
Tests de `app/risk_filters.py`, offline salvo los marcados `network`.

El bloque grande es el de palabras críticas: es el que decide vetar una
operación por una noticia, y en una corrida real contra Yahoo se lo vio vetar
SPY y MSFT porque `"war"` matcheaba dentro de "hardware" y "software". Estos
tests fijan ese comportamiento para que no vuelva.
"""
import pytest

from app import config
from app import risk_filters as rf


# ---------- Palabras críticas: límites de palabra ----------


@pytest.mark.parametrize(
    "titular",
    [
        "Optics Stocks Slide as AI Hardware Trade Cools",       # "war" en hardware
        "Microsoft, Palantir Among Stocks As Software Bounces",  # "war" en software
        "Warner Bros posts quarterly results",                   # "war" en Warner
        "Steward Health reports earnings",                       # "steward"
        "Defaulting to the new pricing tier",                    # "default" + sufijo
    ],
)
def test_no_vetea_por_coincidencia_dentro_de_otra_palabra(titular):
    assert rf._palabra_critica(titular, rf.PALABRAS_CRITICAS_ACCIONES) is None


@pytest.mark.parametrize(
    "titular,esperada",
    [
        ("Israel-Hamas war escalates, oil spikes", "war"),
        ("Bank run at regional lender triggers panic", "bank run"),
        ("SEC probe into accounting practices widens", "sec probe"),
        ("Company files for bankruptcy protection", "bankruptcy"),
        ("Massive fraud uncovered at fintech", "fraud"),
        ("US sanction on chip exports hits sector", "sanction"),
        ("Argentina default fears return", "default"),
    ],
)
def test_detecta_la_palabra_critica_real(titular, esperada):
    assert rf._palabra_critica(titular, rf.PALABRAS_CRITICAS_ACCIONES) == esperada


@pytest.mark.parametrize(
    "titular,esperada",
    [
        ("US imposes new sanctions on Russian oil majors", "sanction"),
        ("Tesla falls after SEC probes disclosure practices", "sec probe"),
        ("Evergrande defaults on dollar bond payment", "default"),
        ("Regional bank runs spread across the sector", "bank run"),
        ("Two companies filed for bankruptcies this quarter", "bankruptcy"),
    ],
)
def test_detecta_la_palabra_critica_en_plural(titular, esperada):
    """
    El plural es la forma habitual en titulares reales.

    La primera versión del patrón exigía singular exacto y dejaba pasar estos
    cinco casos, que el matcheo por subcadena del manual sí vetaba: arreglar el
    falso positivo de "hardware" había abierto un falso negativo peor.
    """
    assert rf._palabra_critica(titular, rf.PALABRAS_CRITICAS_ACCIONES) == esperada


@pytest.mark.parametrize(
    "titular,esperada",
    [
        # El plural cae en la PRIMERA palabra de la frase, no en la última.
        ("Cesaciones de pagos en varias provincias", "cesacion de pagos"),
        ("Embargos sobre reservas del BCRA", "embargo"),
        ("Analistas ven reperfilamientos en la curva corta", "reperfilamiento"),
    ],
)
def test_palabras_de_deuda_en_plural(titular, esperada):
    assert rf._palabra_critica(titular, rf.PALABRAS_CRITICAS_BONOS) == esperada


def test_el_plural_no_reabre_los_falsos_positivos():
    """Tolerar plurales no debe volver a matchear dentro de otra palabra."""
    for titular in [
        "Optics Stocks Slide as AI Hardware Trade Cools",
        "Software makers beat estimates",
        "Warehouse REIT gains on strong demand",
        "Warner Bros posts quarterly results",
    ]:
        assert rf._palabra_critica(titular, rf.PALABRAS_CRITICAS_ACCIONES) is None, titular


@pytest.mark.parametrize(
    "titular,esperada",
    [
        ("El Gobierno descarta un reperfilamiento de la deuda", "reperfilamiento"),
        ("Analistas ven riesgo de cesacion de pagos en 2027", "cesacion de pagos"),
        ("Advierten por una cesación de pagos inminente", "cesacion de pagos"),
        ("Avanza el litigio Nueva York por los cupones PBI", "litigio nueva york"),
    ],
)
def test_palabras_criticas_de_deuda_con_y_sin_tildes(titular, esperada):
    """Los titulares en español vienen acentuados y la lista del manual no."""
    assert rf._palabra_critica(titular, rf.PALABRAS_CRITICAS_BONOS) == esperada


def test_titular_de_deuda_neutro_no_vetea():
    titular = "Bonos soberanos suben por mejores expectativas de mercado"
    assert rf._palabra_critica(titular, rf.PALABRAS_CRITICAS_BONOS) is None


def test_frase_tolera_espacios_multiples():
    assert rf._palabra_critica("A  bank   run  begins", rf.PALABRAS_CRITICAS_ACCIONES) == "bank run"


# ---------- Circuit breaker de VIX ----------


class _HistorialFalso:
    def __init__(self, cierres):
        import pandas as pd

        self._df = pd.DataFrame({"Close": cierres})

    def history(self, period="2d"):
        return self._df


def _mockear_vix(monkeypatch, cierres):
    monkeypatch.setattr(rf.yf, "Ticker", lambda t: _HistorialFalso(cierres))


def test_vix_normal_no_vetea(monkeypatch):
    _mockear_vix(monkeypatch, [14.51, 14.43])

    permitido, motivo = rf.check_vix_circuit_breaker()

    assert permitido is True
    assert "OK" in motivo


def test_vix_por_encima_del_nivel_de_panico_vetea(monkeypatch):
    _mockear_vix(monkeypatch, [26.0, config.VIX_NIVEL_PANICO + 3.4])

    permitido, motivo = rf.check_vix_circuit_breaker()

    assert permitido is False
    assert motivo.startswith("VETO")
    assert "pánico" in motivo


def test_suba_abrupta_del_vix_vetea_aunque_el_nivel_sea_bajo(monkeypatch):
    # +20% diario partiendo de un nivel tranquilo: dispara por variación, no por nivel.
    _mockear_vix(monkeypatch, [15.0, 18.0])

    permitido, motivo = rf.check_vix_circuit_breaker()

    assert permitido is False
    assert "volatilidad" in motivo.lower()


def test_error_leyendo_el_vix_vetea_fail_safe(monkeypatch):
    def explota(_):
        raise RuntimeError("yahoo caído")

    monkeypatch.setattr(rf.yf, "Ticker", explota)

    permitido, motivo = rf.check_vix_circuit_breaker()

    assert permitido is False, "sin saber si el mercado está en pánico no se abre posición"
    assert "Error" in motivo


def test_estado_vix_expone_los_datos_crudos(monkeypatch):
    _mockear_vix(monkeypatch, [14.51, 14.43])

    estado = rf.estado_vix()

    assert set(estado) >= {"vix_actual", "vix_previo", "cambio_pct", "veto", "motivo"}
    assert estado["vix_actual"] == 14.43
    assert estado["veto"] is False


# ---------- Degradación sin FinBERT ----------


def test_sin_finbert_el_veto_por_palabra_critica_sigue_funcionando(monkeypatch):
    """Aunque no haya modelo, un titular de cisne negro tiene que vetar igual."""
    monkeypatch.setattr(rf, "_cargar_finbert", lambda: None)
    monkeypatch.setattr(
        rf, "leer_titulares", lambda url, maximo: ["Company files for bankruptcy protection"]
    )

    permitido, score, motivo = rf.get_finbert_sentiment("XYZ")

    assert permitido is False
    assert score == -1.0
    assert "CISNE NEGRO" in motivo


def test_feed_caido_no_vetea_fail_open(monkeypatch):
    def explota(url, maximo):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(rf, "leer_titulares", explota)

    permitido, score, _ = rf.get_finbert_sentiment("AAPL")

    assert permitido is True, "un 429 de Yahoo no es riesgo del activo"
    assert score == 0.0


def test_sin_noticias_devuelve_neutro(monkeypatch):
    monkeypatch.setattr(rf, "leer_titulares", lambda url, maximo: [])

    permitido, score, motivo = rf.get_finbert_sentiment("AAPL")

    assert permitido is True
    assert score == 0.0
    assert "neutro" in motivo.lower() or "sin noticias" in motivo.lower()


# ---------- Contra internet real ----------


@pytest.mark.network
def test_vix_real_devuelve_un_valor_plausible():
    estado = rf.estado_vix()

    assert estado["vix_actual"] is not None
    assert 5.0 < estado["vix_actual"] < 90.0
