"""
Tests de `app/entry_validator.py` (Tarea 4.4).

Todo offline salvo el marcado con `@pytest.mark.network`: los tres números que
miran los filtros (precio del índice, SMA200 y variación de la rueda) se inyectan
a mano, así los escenarios de aceptación no dependen de cómo esté el mercado hoy.

    ./venv/Scripts/python.exe -m pytest tests/test_entry_validator.py -v
    ./venv/Scripts/python.exe -m pytest tests/test_entry_validator.py -v -m "not network"
"""
import numpy as np
import pandas as pd
import pytest

from app import config
from app import entry_validator as ev
from app.entry_validator import EntryValidator
from app.market_data import MarketDataError, limpiar_cache


# ---------- Datos base de los escenarios ----------
# Un índice sano: cotiza 620 contra una SMA200 de 600 y la rueda cierra +0,30%.
MERCADO_SANO = {"market_price": 620.0, "market_sma200": 600.0, "market_change_pct": 0.003}

# Señal vigente: rompió 100.00 y está en 100.50 (+0,50%, dentro del 1,0%).
BREAKOUT = 100.0
PRECIO_VIGENTE = 100.5


@pytest.fixture
def validador() -> EntryValidator:
    return EntryValidator()


@pytest.fixture(autouse=True)
def _cache_limpia():
    """La cache de `market_data` es global: se limpia entre tests."""
    limpiar_cache()
    yield
    limpiar_cache()


def historico_falso(cierres: list[float]) -> pd.DataFrame:
    """DataFrame OHLCV mínimo con los cierres dados, con la forma que devuelve yfinance."""
    idx = pd.date_range("2025-01-01", periods=len(cierres), freq="B")
    close = np.array(cierres, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(len(cierres), 1_000_000.0),
        },
        index=idx,
    )


# ---------- Config: los parámetros existen y valen lo que dice la spec ----------


def test_config_trae_los_parametros_de_entrada():
    assert config.ENTRADA_MAX_CHASE_PCT == 0.010
    assert config.ENTRADA_MERCADO_CAIDA_MAX == -0.010
    assert config.SMA_BENCHMARK_PERIODO == 200
    assert config.BENCHMARK_POR_TIPO == {"CEDEAR": "SPY", "ACCION": "^MERV", "BONO": None}


def test_validador_toma_los_defaults_de_config(validador):
    assert validador.max_chase_pct == config.ENTRADA_MAX_CHASE_PCT
    assert validador.market_min_change == config.ENTRADA_MERCADO_CAIDA_MAX


def test_validador_acepta_umbrales_propios():
    v = EntryValidator(max_chase_pct=0.02, market_min_change=-0.03)

    assert v.max_chase_pct == 0.02
    assert v.market_min_change == -0.03


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_chase_pct": -0.01},      # tolerancia negativa no tiene sentido
        {"market_min_change": 0.01},   # la caída tolerada tiene que ser <= 0
        {"max_chase_pct": float("nan")},
    ],
)
def test_validador_rechaza_umbrales_invalidos(kwargs):
    with pytest.raises(ValueError):
        EntryValidator(**kwargs)


# ---------- Tabla de escenarios de aceptación (Tarea 4.4) ----------
# (nombre, precio_actual, breakout, mercado, aprobado_esperado, texto_esperado)

ESCENARIOS = [
    (
        "Mercado sano + señal vigente",
        PRECIO_VIGENTE,
        BREAKOUT,
        MERCADO_SANO,
        True,
        "COMPRA APROBADA",
    ),
    (
        "Índice por debajo de la SMA200",
        PRECIO_VIGENTE,
        BREAKOUT,
        {"market_price": 590.0, "market_sma200": 600.0, "market_change_pct": 0.003},
        False,
        "VETO MERCADO: índice por debajo de su SMA200",
    ),
    (
        "Índice cae más de 1% en el día",
        PRECIO_VIGENTE,
        BREAKOUT,
        {"market_price": 620.0, "market_sma200": 600.0, "market_change_pct": -0.015},
        False,
        "VETO MERCADO: día de venta masiva",
    ),
    (
        "Precio extendido más de 1% del breakout",
        101.8,
        BREAKOUT,
        MERCADO_SANO,
        False,
        "VETO SEÑAL: señal vencida",
    ),
    (
        "Precio todavía por debajo del breakout",
        99.4,
        BREAKOUT,
        MERCADO_SANO,
        False,
        "VETO SEÑAL: el precio actual todavía no superó",
    ),
]


@pytest.mark.parametrize(
    "nombre,precio,breakout,mercado,aprobado,texto",
    ESCENARIOS,
    ids=[e[0] for e in ESCENARIOS],
)
def test_can_open_position_escenarios(validador, nombre, precio, breakout, mercado, aprobado, texto):
    ok, motivo = validador.can_open_position(
        current_price=precio,
        breakout_level=breakout,
        market_price=mercado["market_price"],
        market_sma200=mercado["market_sma200"],
        market_change_pct=mercado["market_change_pct"],
    )

    assert ok is aprobado, f"{nombre}: {motivo}"
    assert texto in motivo, f"{nombre}: {motivo}"
    if not aprobado:
        assert motivo.startswith("COMPRA RECHAZADA: ")


def test_tabla_de_escenarios_se_imprime(validador, capsys):
    """Deja la tabla del criterio de aceptación en la salida de pytest (-s)."""
    filas = []
    for nombre, precio, breakout, mercado, _, _ in ESCENARIOS:
        ok, motivo = validador.can_open_position(
            precio, breakout, mercado["market_price"], mercado["market_sma200"],
            mercado["market_change_pct"],
        )
        filas.append((nombre, "APROBADO" if ok else "RECHAZADO", motivo))

    with capsys.disabled():
        print("\n| Escenario | Resultado | Motivo |")
        print("|---|---|---|")
        for nombre, resultado, motivo in filas:
            print(f"| {nombre} | {resultado} | {motivo} |")

    assert len(filas) == len(ESCENARIOS)


# ---------- Filtro 1: is_market_healthy ----------


def test_mercado_sano(validador):
    ok, motivo = validador.is_market_healthy(620.0, 600.0, 0.003)

    assert ok is True
    assert "saludable" in motivo


def test_mercado_bajo_sma200_veta(validador):
    ok, motivo = validador.is_market_healthy(590.0, 600.0, 0.005)

    assert ok is False
    assert motivo.startswith("VETO MERCADO:")
    assert "SMA200" in motivo


def test_mercado_en_dia_de_panico_veta(validador):
    ok, motivo = validador.is_market_healthy(620.0, 600.0, -0.015)

    assert ok is False
    assert "venta masiva" in motivo
    assert "-1.50%" in motivo


def test_mercado_justo_en_la_sma200_pasa(validador):
    """El corte es estricto (`<`): estar exactamente sobre la SMA200 no veta."""
    ok, _ = validador.is_market_healthy(600.0, 600.0, 0.0)

    assert ok is True


def test_mercado_con_caida_exacta_del_limite_pasa(validador):
    """-1,0% clavado es el borde tolerado (la regla es `>= -1.0%`)."""
    ok, _ = validador.is_market_healthy(620.0, 600.0, config.ENTRADA_MERCADO_CAIDA_MAX)

    assert ok is True


@pytest.mark.parametrize(
    "precio,sma,cambio",
    [
        (None, 600.0, 0.003),
        (620.0, None, 0.003),
        (620.0, 600.0, None),
        (float("nan"), 600.0, 0.003),
        (620.0, float("nan"), 0.003),
    ],
)
def test_mercado_con_datos_faltantes_veta(validador, precio, sma, cambio):
    """Fail-safe: sin el dato del índice no se autoriza la compra (criterio VIX)."""
    ok, motivo = validador.is_market_healthy(precio, sma, cambio)

    assert ok is False
    assert "faltan datos" in motivo


def test_mercado_con_sma200_invalida_veta(validador):
    ok, motivo = validador.is_market_healthy(620.0, 0.0, 0.003)

    assert ok is False
    assert "inválida" in motivo


# ---------- Filtro 2: is_signal_valid ----------


def test_senal_en_rango_optimo(validador):
    ok, motivo = validador.is_signal_valid(100.5, 100.0)

    assert ok is True
    assert "+0.50%" in motivo


def test_senal_justo_en_el_breakout_pasa(validador):
    ok, motivo = validador.is_signal_valid(100.0, 100.0)

    assert ok is True
    assert "+0.00%" in motivo


def test_senal_en_el_limite_exacto_de_chase_pasa(validador):
    """+1,0% clavado todavía entra, sin que lo arruine el redondeo de floats."""
    breakout = 100.0
    limite = breakout * (1 + config.ENTRADA_MAX_CHASE_PCT)

    assert validador.is_signal_valid(limite, breakout)[0] is True
    assert validador.is_signal_valid(101.0, breakout)[0] is True   # el mismo borde, literal
    assert validador.is_signal_valid(101.01, breakout)[0] is False  # un pelo más ya veta


def test_senal_extendida_veta(validador):
    ok, motivo = validador.is_signal_valid(101.8, 100.0)

    assert ok is False
    assert motivo.startswith("VETO SEÑAL:")
    assert "1.80%" in motivo
    assert "1.0%" in motivo


def test_senal_por_debajo_del_breakout_veta(validador):
    ok, motivo = validador.is_signal_valid(99.4, 100.0)

    assert ok is False
    assert "no superó el nivel de ruptura" in motivo


def test_senal_con_breakout_invalido_veta(validador):
    ok, motivo = validador.is_signal_valid(100.0, 0.0)

    assert ok is False
    assert "nivel de ruptura inválido" in motivo


def test_senal_con_datos_faltantes_veta(validador):
    ok, motivo = validador.is_signal_valid(None, 100.0)

    assert ok is False
    assert "faltan datos" in motivo


def test_tolerancia_propia_cambia_el_veredicto():
    """El mismo precio pasa con 2% de tolerancia y se veta con 1%."""
    con_default = EntryValidator().is_signal_valid(101.5, 100.0)[0]
    con_2_pct = EntryValidator(max_chase_pct=0.02).is_signal_valid(101.5, 100.0)[0]

    assert con_default is False
    assert con_2_pct is True


# ---------- Orden de los filtros (checklist de la spec, sección 5) ----------


def test_el_filtro_de_mercado_corta_antes_que_el_de_senal(validador):
    """Con mercado adverso Y precio extendido, el motivo tiene que ser el de mercado."""
    ok, motivo = validador.can_open_position(
        current_price=101.8,      # también rompería el anti-chase
        breakout_level=100.0,
        market_price=590.0,       # pero el mercado corta primero
        market_sma200=600.0,
        market_change_pct=-0.02,
    )

    assert ok is False
    assert "VETO MERCADO" in motivo
    assert "VETO SEÑAL" not in motivo


# ---------- datos_benchmark: mapeo tipo -> índice ----------


@pytest.mark.parametrize(
    "tipo,esperado",
    [("CEDEAR", "SPY"), ("cedear", "SPY"), (" ACCION ", "^MERV"), ("BONO", None)],
)
def test_ticker_benchmark_por_tipo(tipo, esperado):
    assert ev.ticker_benchmark(tipo) == esperado


def test_ticker_desconocido_cae_en_el_benchmark_por_defecto():
    assert ev.ticker_benchmark("FCI") == config.TICKER_BENCHMARK


def test_datos_benchmark_calcula_sma200_y_cambio_diario(monkeypatch):
    """Serie de 250 ruedas: 249 cierres en 100 y el último en 110."""
    cierres = [100.0] * 249 + [110.0]
    monkeypatch.setattr(ev, "get_history", lambda ticker, period: historico_falso(cierres))

    datos = ev.datos_benchmark("CEDEAR")

    assert datos["ticker"] == "SPY"
    assert datos["disponible"] is True
    assert datos["aplica"] is True
    assert datos["precio"] == pytest.approx(110.0)
    # SMA200 = (199 * 100 + 110) / 200
    assert datos["sma200"] == pytest.approx((199 * 100.0 + 110.0) / 200)
    assert datos["cambio_diario_pct"] == pytest.approx(0.10)
    assert datos["ruedas"] == 250
    assert set(datos) >= {"ticker", "precio", "sma200", "cambio_diario_pct"}


def test_datos_benchmark_pide_un_ano_de_historico(monkeypatch):
    """La ventana de 60d de los 7 filtros no alcanza para una SMA de 200 ruedas."""
    pedidos = {}

    def fake_history(ticker, period):
        pedidos["ticker"] = ticker
        pedidos["period"] = period
        return historico_falso([100.0] * 250)

    monkeypatch.setattr(ev, "get_history", fake_history)

    ev.datos_benchmark("ACCION")

    assert pedidos["ticker"] == "^MERV"
    assert pedidos["period"] == ev.PERIODO_HISTORICO_BENCHMARK == "1y"


def test_datos_benchmark_con_historico_corto_no_esta_disponible(monkeypatch):
    monkeypatch.setattr(ev, "get_history", lambda ticker, period: historico_falso([100.0] * 60))

    datos = ev.datos_benchmark("CEDEAR")

    assert datos["disponible"] is False
    assert "Ruedas insuficientes" in datos["motivo"]
    assert datos["precio"] is None


def test_datos_benchmark_con_red_caida_no_rompe(monkeypatch):
    def explota(ticker, period):
        raise MarketDataError("simulación: Yahoo no responde")

    monkeypatch.setattr(ev, "get_history", explota)

    datos = ev.datos_benchmark("CEDEAR")

    assert datos["disponible"] is False
    assert "Yahoo no responde" in datos["motivo"]


def test_datos_benchmark_de_bono_no_aplica(monkeypatch):
    def no_deberia_llamarse(ticker, period):  # pragma: no cover
        raise AssertionError("un BONO no tiene que pedir histórico de benchmark")

    monkeypatch.setattr(ev, "get_history", no_deberia_llamarse)

    datos = ev.datos_benchmark("BONO")

    assert datos["ticker"] is None
    assert datos["aplica"] is False
    assert datos["disponible"] is False
    assert "no aplica" in datos["motivo"]


# ---------- chequear_regimen_mercado: la compuerta lista para el escaneo ----------


def test_chequear_regimen_con_mercado_sano_habilita(monkeypatch):
    cierres = [100.0] * 249 + [120.0]  # último cierre bien por encima de la SMA200
    monkeypatch.setattr(ev, "get_history", lambda ticker, period: historico_falso(cierres))

    ok, detalle = ev.chequear_regimen_mercado("CEDEAR")

    assert ok is True
    assert "saludable" in detalle["motivo"]


def test_chequear_regimen_con_indice_bajo_sma200_veta(monkeypatch):
    cierres = [100.0] * 249 + [80.0]
    monkeypatch.setattr(ev, "get_history", lambda ticker, period: historico_falso(cierres))

    ok, detalle = ev.chequear_regimen_mercado("CEDEAR")

    assert ok is False
    assert "VETO MERCADO" in detalle["motivo"]


def test_chequear_regimen_sin_datos_veta_fail_safe(monkeypatch):
    """Decisión documentada: sin datos del benchmark se veta, como con el VIX."""
    def explota(ticker, period):
        raise MarketDataError("simulación: sin red")

    monkeypatch.setattr(ev, "get_history", explota)

    ok, detalle = ev.chequear_regimen_mercado("CEDEAR")

    assert ok is False
    assert detalle["motivo"].startswith("VETO MERCADO:")
    assert "sin red" in detalle["motivo"]


def test_chequear_regimen_de_bono_deja_pasar(monkeypatch):
    monkeypatch.setattr(ev, "get_history", lambda ticker, period: historico_falso([100.0] * 250))

    ok, detalle = ev.chequear_regimen_mercado("BONO")

    assert ok is True
    assert detalle["aplica"] is False


def test_chequear_regimen_reutiliza_el_validador_pasado(monkeypatch):
    """Con una tolerancia de caída del 5%, una rueda de -3% ya no veta."""
    cierres = [100.0] * 249 + [120.0 * 0.97]
    cierres[-2] = 120.0
    monkeypatch.setattr(ev, "get_history", lambda ticker, period: historico_falso(cierres))

    ok_default, _ = ev.chequear_regimen_mercado("CEDEAR")
    ok_permisivo, _ = ev.chequear_regimen_mercado(
        "CEDEAR", validador=EntryValidator(market_min_change=-0.05)
    )

    assert ok_default is False
    assert ok_permisivo is True


# ---------- Test con red ----------


@pytest.mark.network
def test_datos_benchmark_spy_real(capsys):
    """Corre `datos_benchmark("CEDEAR")` contra SPY real y muestra los números."""
    datos = ev.datos_benchmark("CEDEAR")

    if not datos["disponible"]:
        pytest.skip(f"Sin acceso a Yahoo Finance: {datos['motivo']}")

    with capsys.disabled():
        print(
            f"\n[network] {datos['ticker']}: precio={datos['precio']:.2f} "
            f"SMA{config.SMA_BENCHMARK_PERIODO}={datos['sma200']:.2f} "
            f"cambio_diario={datos['cambio_diario_pct'] * 100:+.2f}% "
            f"({datos['ruedas']} ruedas)"
        )

    assert datos["ticker"] == "SPY"
    assert datos["precio"] > 0
    assert datos["sma200"] > 0
    assert datos["ruedas"] >= config.SMA_BENCHMARK_PERIODO
    assert -0.5 < datos["cambio_diario_pct"] < 0.5  # una rueda no se mueve 50%

    ok, motivo = EntryValidator().is_market_healthy(
        datos["precio"], datos["sma200"], datos["cambio_diario_pct"]
    )
    with capsys.disabled():
        print(f"[network] is_market_healthy -> {ok}: {motivo}")

    assert isinstance(ok, bool)
