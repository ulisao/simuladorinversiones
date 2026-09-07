"""
Tests del orquestador de señales (`app/signals.py`) y del endpoint `GET /senales`.

El caso central es el criterio de aceptación de la Tarea 4.3: si el circuit
breaker de VIX vetea, `/senales` devuelve lista vacía con el motivo global y
**no evalúa ningún ticker**. Todo con mocks: ningún test de este archivo le pega
a internet.
"""
import pytest
from fastapi.testclient import TestClient

from app import signals
from app.main import app


VIX_NORMAL = {
    "vix_actual": 14.43,
    "vix_previo": 14.51,
    "cambio_pct": -0.0055,
    "veto": False,
    "motivo": "VIX OK (14.43, -0.6% diario)",
}

VIX_PANICO = {
    "vix_actual": 28.40,
    "vix_previo": 22.10,
    "cambio_pct": 0.285,
    "veto": True,
    "motivo": "VETO: VIX en nivel de pánico (28.40 > 25.0)",
}


@pytest.fixture
def client():
    return TestClient(app)


REGIMEN_SANO = {
    "tipo": "CEDEAR",
    "ticker": "SPY",
    "precio": 761.78,
    "sma200": 708.29,
    "cambio_diario_pct": -0.0069,
    "aplica": True,
    "disponible": True,
    "motivo": "Mercado saludable y apto para compras",
    "ruedas": 252,
}

REGIMEN_BAJISTA = {
    **REGIMEN_SANO,
    "precio": 590.0,
    "sma200": 600.0,
    "motivo": "VETO MERCADO: índice por debajo de su SMA200 (590.00 < 600.00)",
}


def _sin_red(monkeypatch, vix_estado, vix_check, *, espia=None, regimen=None):
    """Reemplaza todas las dependencias externas de `signals` por mocks."""
    monkeypatch.setattr(signals.risk_filters, "estado_vix", lambda: vix_estado)
    monkeypatch.setattr(signals.risk_filters, "check_vix_circuit_breaker", lambda: vix_check)

    # Sin esto el escaneo le pega a Yahoo de verdad para traer el benchmark.
    estado_regimen = regimen if regimen is not None else REGIMEN_SANO
    sano = not str(estado_regimen.get("motivo", "")).startswith("VETO")
    monkeypatch.setattr(
        signals.entry_validator,
        "chequear_regimen_mercado",
        lambda tipo, validador=None: (sano, estado_regimen),
    )

    def sentimiento(ticker):
        if espia is not None:
            espia.append(("sentimiento", ticker))
        return True, 0.25, f"Sentimiento OK (+0.25) en {ticker}"

    def contexto(ticker):
        if espia is not None:
            espia.append(("smart_money", ticker))
        return {
            "rvol": 1.1,
            "es_acumulacion": False,
            "insiders_detectados": False,
            "insiders_detalle": "Sin filings",
        }

    def filtros(ticker):
        if espia is not None:
            espia.append(("filtros", ticker))
        if ticker == "KO":
            return False, {"motivo": "VETO TÉCNICO: estructura no alcista"}
        return True, {
            "ticker": ticker,
            "precio_entrada": 100.0,
            "stop_loss": 97.0,
            "take_profit": 106.0,
            "pct_riesgo": 3.0,
        }

    def rsi(ticker, bid=None, ask=None):
        """Por defecto la fuente RSI no dispara: los tests viejos miden los 7 filtros."""
        if espia is not None:
            espia.append(("rsi", ticker))
        return False, {
            "ticker": ticker,
            "rsi": 50.15,
            "motivo": f"SIN SEÑAL RSI: {ticker} en 50.15, no está sobrevendido (umbral 30).",
        }

    monkeypatch.setattr(signals.risk_filters, "get_finbert_sentiment", sentimiento)
    monkeypatch.setattr(signals.smart_money, "contexto_smart_money", contexto)
    monkeypatch.setattr(signals.technical_filters, "evaluate_7_filters", filtros)
    monkeypatch.setattr(signals.rsi_signal, "evaluar_rsi", rsi)


# ---------- Tarea 4.3: el veto de VIX corta el escaneo ----------


def test_vix_en_panico_devuelve_lista_vacia_con_motivo(monkeypatch):
    _sin_red(monkeypatch, VIX_PANICO, (False, VIX_PANICO["motivo"]))

    resultado = signals.escanear_senales(["AAPL", "NVDA"])

    assert resultado["candidatos"] == []
    assert resultado["veto_global"] == VIX_PANICO["motivo"]
    assert "VETO" in resultado["veto_global"]


def test_vix_en_panico_no_evalua_ningun_ticker(monkeypatch):
    """El corte tiene que ser ANTES de gastar llamadas por ticker."""
    espia: list = []
    _sin_red(monkeypatch, VIX_PANICO, (False, VIX_PANICO["motivo"]), espia=espia)

    signals.escanear_senales(["AAPL", "NVDA", "KO"])

    assert espia == [], f"se evaluaron tickers pese al veto de VIX: {espia}"


def test_endpoint_senales_respeta_el_veto_de_vix(monkeypatch, client):
    """Criterio de aceptación literal de la Tarea 4.3, vía HTTP."""
    _sin_red(monkeypatch, VIX_PANICO, (False, VIX_PANICO["motivo"]))

    res = client.get("/senales")

    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["candidatos"] == []
    assert cuerpo["veto_global"] == VIX_PANICO["motivo"]
    assert cuerpo["vix"]["veto"] is True


# ---------- Operación normal ----------


def test_con_vix_normal_el_escaneo_funciona(monkeypatch):
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))

    resultado = signals.escanear_senales(["AAPL", "NVDA", "KO"])

    assert resultado["veto_global"] is None
    assert [c["ticker"] for c in resultado["candidatos"]] == ["AAPL", "NVDA"]
    assert [d["ticker"] for d in resultado["descartados"]] == ["KO"]


def test_los_descartados_conservan_su_motivo(monkeypatch):
    """Requisito explícito de la Tarea 3.3: los motivos no se pierden."""
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))

    resultado = signals.escanear_senales(["KO"])

    # Con dos fuentes de señal (Tarea 3.7) el descarte trae las dos razones: la
    # regla del repo es que ningún motivo de veto se pierda.
    motivo = resultado["descartados"][0]["motivo"]
    assert "VETO TÉCNICO: estructura no alcista" in motivo
    assert "SIN SEÑAL RSI" in motivo


def test_el_veto_por_noticias_descarta_sin_evaluar_los_7_filtros(monkeypatch):
    """Orden del manual: noticias ANTES que los filtros técnicos."""
    espia: list = []
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]), espia=espia)
    monkeypatch.setattr(
        signals.risk_filters,
        "get_finbert_sentiment",
        lambda t: (False, -1.0, "VETO CISNE NEGRO: palabra crítica en el titular"),
    )

    resultado = signals.escanear_senales(["NVDA"])

    assert resultado["candidatos"] == []
    assert resultado["descartados"][0]["motivo"].startswith("VETO CISNE NEGRO")
    assert ("filtros", "NVDA") not in espia
    assert ("rsi", "NVDA") not in espia, "el veto de noticias corta las DOS fuentes"


def test_smart_money_no_vetea_nunca(monkeypatch):
    """Tarea 5.2: RVOL e insiders son contexto, no un filtro obligatorio."""
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))
    monkeypatch.setattr(
        signals.smart_money,
        "contexto_smart_money",
        lambda t: {
            "rvol": 0.2,
            "es_acumulacion": False,
            "insiders_detectados": False,
            "insiders_detalle": "Sin filings Form 4",
        },
    )

    resultado = signals.escanear_senales(["NVDA"])

    assert len(resultado["candidatos"]) == 1
    assert resultado["candidatos"][0]["rvol"] == 0.2
    assert resultado["candidatos"][0]["es_acumulacion"] is False


def test_los_campos_de_contexto_viajan_en_la_respuesta(monkeypatch, client):
    """Tarea 5.2: `/senales` incluye rvol e insiders_detectados por candidato."""
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))
    monkeypatch.setattr(signals.config, "TICKERS_BYMA", ["NVDA"])

    cuerpo = client.get("/senales").json()

    candidato = cuerpo["candidatos"][0]
    for campo in ("rvol", "es_acumulacion", "insiders_detectados", "insiders_detalle", "sentimiento_score"):
        assert campo in candidato, f"falta {campo} en la respuesta de /senales"


def test_un_ticker_roto_no_tumba_el_escaneo(monkeypatch):
    """Red de seguridad: una excepción inesperada se degrada a descarte."""
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))

    def explota(ticker):
        if ticker == "NVDA":
            raise RuntimeError("yahoo devolvió basura")
        return True, 0.1, "OK"

    monkeypatch.setattr(signals.risk_filters, "get_finbert_sentiment", explota)

    resultado = signals.escanear_senales(["NVDA", "AAPL"])

    assert [c["ticker"] for c in resultado["candidatos"]] == ["AAPL"]
    assert "yahoo devolvió basura" in resultado["descartados"][0]["motivo"]


# ---------- Tarea 4.5: régimen de mercado y anti-chase ----------


def test_mercado_bajista_corta_el_escaneo_sin_evaluar_tickers(monkeypatch):
    """El checklist pide descartar la watchlist en bloque para ahorrar llamadas."""
    espia: list = []
    _sin_red(
        monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]),
        espia=espia, regimen=REGIMEN_BAJISTA,
    )

    resultado = signals.escanear_senales(["AAPL", "NVDA", "KO"])

    assert resultado["candidatos"] == []
    assert resultado["veto_global"] == REGIMEN_BAJISTA["motivo"]
    assert espia == [], f"se evaluaron tickers pese al veto de mercado: {espia}"


def test_el_vix_se_chequea_antes_que_el_regimen_de_mercado(monkeypatch):
    """Si el VIX vetea, ni siquiera se consulta el benchmark."""
    consultas: list = []
    _sin_red(monkeypatch, VIX_PANICO, (False, VIX_PANICO["motivo"]))

    def espiar_regimen(tipo, validador=None):
        consultas.append(tipo)
        return True, REGIMEN_SANO

    monkeypatch.setattr(signals.entry_validator, "chequear_regimen_mercado", espiar_regimen)

    resultado = signals.escanear_senales(["NVDA"])

    assert resultado["veto_global"] == VIX_PANICO["motivo"]
    assert consultas == [], "no hay que gastar una llamada al benchmark si el VIX ya cortó"


def test_el_vix_se_lee_una_sola_vez_por_escaneo(monkeypatch):
    """Dos lecturas podían discrepar y mostrar veto global con el VIX en verde."""
    lecturas: list = []
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))

    def contar():
        lecturas.append(1)
        return VIX_NORMAL

    monkeypatch.setattr(signals.risk_filters, "estado_vix", contar)

    signals.escanear_senales(["NVDA"])

    assert len(lecturas) == 1, f"se leyó el VIX {len(lecturas)} veces"


def test_descarta_el_candidato_que_se_escapo_del_breakout(monkeypatch):
    """Anti-chase: el precio trepó más de 1,0% sobre el nivel de ruptura."""
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))
    monkeypatch.setattr(
        signals.technical_filters,
        "evaluate_7_filters",
        lambda t: (True, {
            "ticker": t, "precio_entrada": 102.0, "stop_loss": 99.0,
            "take_profit": 108.0, "pct_riesgo": 3.0, "breakout_level": 100.0,
        }),
    )

    resultado = signals.escanear_senales(["NVDA"])

    assert resultado["candidatos"] == []
    assert "SEÑAL" in resultado["descartados"][0]["motivo"].upper()


def test_acepta_el_candidato_que_sigue_en_rango(monkeypatch):
    """+0,5% sobre la ruptura: dentro de la tolerancia del 1,0%."""
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))
    monkeypatch.setattr(
        signals.technical_filters,
        "evaluate_7_filters",
        lambda t: (True, {
            "ticker": t, "precio_entrada": 100.5, "stop_loss": 97.5,
            "take_profit": 106.5, "pct_riesgo": 3.0, "breakout_level": 100.0,
        }),
    )

    resultado = signals.escanear_senales(["NVDA"])

    assert [c["ticker"] for c in resultado["candidatos"]] == ["NVDA"]
    assert resultado["candidatos"][0]["breakout_level"] == 100.0


def test_el_regimen_viaja_en_la_respuesta(monkeypatch, client):
    _sin_red(monkeypatch, VIX_NORMAL, (True, VIX_NORMAL["motivo"]))
    monkeypatch.setattr(signals.config, "TICKERS_BYMA", ["NVDA"])

    cuerpo = client.get("/senales").json()

    assert cuerpo["regimen_mercado"]["ticker"] == "SPY"
    assert cuerpo["regimen_mercado"]["sma200"] == 708.29
