"""
Tests del módulo de notificaciones (Tarea 7.1) y de la alerta de cierre (7.2).

Ningún test de este archivo le pega a Telegram: `requests.post` está siempre
mockeado. Lo que se verifica es el contrato del módulo — **nunca lanza** — y que
el cierre de una operación dispara el aviso con los números correctos.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import notifications
from app.database import Base, engine
from app.main import app


class RespuestaFalsa:
    """Mínimo de `requests.Response` que usa `send_telegram`."""

    def __init__(self, status_code=200, cuerpo=None, texto=""):
        self.status_code = status_code
        self._cuerpo = cuerpo
        self.text = texto

    def json(self):
        if self._cuerpo is None:
            raise ValueError("sin JSON")
        return self._cuerpo


@pytest.fixture
def telegram_configurado(monkeypatch):
    monkeypatch.setattr(notifications.config, "TELEGRAM_BOT_TOKEN", "123:TOKEN-FALSO")
    monkeypatch.setattr(notifications.config, "TELEGRAM_CHAT_ID", "-1001")


@pytest.fixture
def envios(monkeypatch, telegram_configurado):
    """Captura los payloads enviados y devuelve 200 siempre."""
    capturados = []

    def post_falso(url, json=None, timeout=None):
        capturados.append({"url": url, "payload": json, "timeout": timeout})
        return RespuestaFalsa(200, {"ok": True})

    monkeypatch.setattr(notifications.requests, "post", post_falso)
    return capturados


# ---------- Contrato de send_telegram ----------


def test_sin_credenciales_no_envia_ni_lanza(monkeypatch):
    monkeypatch.setattr(notifications.config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(notifications.config, "TELEGRAM_CHAT_ID", "")

    def no_deberia_llamarse(*args, **kwargs):  # pragma: no cover
        raise AssertionError("no se puede intentar el POST sin credenciales")

    monkeypatch.setattr(notifications.requests, "post", no_deberia_llamarse)

    resultado = notifications.send_telegram("hola")

    assert resultado["enviado"] is False
    assert "TELEGRAM_BOT_TOKEN" in resultado["motivo"]


def test_envio_exitoso(envios):
    resultado = notifications.send_telegram("hola")

    assert resultado == {"enviado": True, "motivo": ""}
    assert len(envios) == 1
    assert envios[0]["payload"]["chat_id"] == "-1001"
    assert envios[0]["payload"]["text"] == "hola"
    assert "parse_mode" not in envios[0]["payload"], "el default es texto plano"


def test_el_token_viaja_en_la_url_y_no_en_el_cuerpo(envios):
    notifications.send_telegram("hola")
    assert "123:TOKEN-FALSO" in envios[0]["url"]


def test_un_error_de_red_no_se_propaga(monkeypatch, telegram_configurado):
    def revienta(*args, **kwargs):
        raise ConnectionError("sin internet")

    monkeypatch.setattr(notifications.requests, "post", revienta)

    resultado = notifications.send_telegram("hola")

    assert resultado["enviado"] is False
    assert "sin internet" in resultado["motivo"]


# ---------- Tarea 8.3: el token nunca sale en un motivo ni en un log ----------
#
# `requests` mete la URL entera en el texto de sus excepciones de red, y la URL
# de Telegram lleva el token adentro. El `motivo` sale por `logger` y por la
# respuesta de `POST /notificaciones/test`, así que sin redactar el token se
# publicaría en los dos lados.


def test_un_error_de_red_no_filtra_el_token(monkeypatch, telegram_configurado, caplog):
    def revienta(*args, **kwargs):
        raise ConnectionError(
            "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries "
            "exceeded with url: /bot123:TOKEN-FALSO/sendMessage"
        )

    monkeypatch.setattr(notifications.requests, "post", revienta)

    with caplog.at_level("WARNING"):
        resultado = notifications.send_telegram("hola")

    assert resultado["enviado"] is False
    assert "123:TOKEN-FALSO" not in resultado["motivo"]
    assert notifications.MARCA_REDACTADO in resultado["motivo"]
    assert "123:TOKEN-FALSO" not in caplog.text


def test_un_cuerpo_de_error_que_repite_la_url_no_filtra_el_token(
    monkeypatch, telegram_configurado
):
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda *a, **k: RespuestaFalsa(
            502, texto="Bad Gateway al llamar /bot123:TOKEN-FALSO/sendMessage"
        ),
    )

    resultado = notifications.send_telegram("hola")

    assert resultado["enviado"] is False
    assert "123:TOKEN-FALSO" not in resultado["motivo"]


def test_el_chat_id_tambien_se_redacta(monkeypatch, telegram_configurado):
    def revienta(*args, **kwargs):
        raise ConnectionError("falló mandando al chat -1001")

    monkeypatch.setattr(notifications.requests, "post", revienta)

    assert "-1001" not in notifications.send_telegram("hola")["motivo"]


def test_redactar_sin_credenciales_no_rompe(monkeypatch):
    monkeypatch.setattr(notifications.config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(notifications.config, "TELEGRAM_CHAT_ID", "")

    assert notifications._redactar("texto cualquiera") == "texto cualquiera"


def test_un_error_http_devuelve_la_descripcion_de_telegram(monkeypatch, telegram_configurado):
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda *a, **k: RespuestaFalsa(403, {"ok": False, "description": "bot was blocked"}),
    )

    resultado = notifications.send_telegram("hola")

    assert resultado["enviado"] is False
    assert "403" in resultado["motivo"]
    assert "bot was blocked" in resultado["motivo"]


def test_un_400_de_formato_se_reintenta_en_texto_plano(monkeypatch, telegram_configurado):
    llamadas = []

    def post_falso(url, json=None, timeout=None):
        llamadas.append(json)
        if "parse_mode" in json:
            return RespuestaFalsa(400, {"ok": False, "description": "can't parse entities"})
        return RespuestaFalsa(200, {"ok": True})

    monkeypatch.setattr(notifications.requests, "post", post_falso)

    resultado = notifications.send_telegram("<b>roto", parse_mode="HTML")

    assert resultado["enviado"] is True, "el aviso tiene que llegar aunque falle el formato"
    assert len(llamadas) == 2
    assert "parse_mode" not in llamadas[1]


def test_el_reintento_no_es_infinito(monkeypatch, telegram_configurado):
    llamadas = []

    def siempre_400(url, json=None, timeout=None):
        llamadas.append(json)
        return RespuestaFalsa(400, {"ok": False, "description": "chat not found"})

    monkeypatch.setattr(notifications.requests, "post", siempre_400)

    resultado = notifications.send_telegram("hola", parse_mode="HTML")

    assert resultado["enviado"] is False
    assert len(llamadas) == 2, "un solo reintento, no un bucle"


def test_un_mensaje_larguisimo_se_recorta_al_limite_de_telegram(envios):
    notifications.send_telegram("x" * 9000)

    texto = envios[0]["payload"]["text"]
    assert len(texto) == notifications.LARGO_MAXIMO
    assert texto.endswith(notifications.MARCA_RECORTE)


# ---------- Armadores de mensaje ----------


def test_esc_escapa_el_html_de_los_valores_dinamicos():
    assert notifications.esc("<b>AL30</b>") == "&lt;b&gt;AL30&lt;/b&gt;"


class TradeFalso:
    ticker = "NVDA"
    tipo = "CEDEAR"
    cantidad = 10.0
    precio_entrada = 100.0
    precio_salida = 110.0
    resultado_neto = 87.4
    # Fracción, no porcentaje: es lo que devuelve `calculations.compute_trade`.
    rendimiento_neto_pct = 0.0874
    comision_compra = 6.4
    comision_venta = 7.0
    senal = "TP1_PARTIAL_50PCT (+4.50%)"


def test_el_mensaje_de_cierre_trae_ticker_resultado_y_porcentaje():
    msg = notifications.mensaje_cierre_operacion(TradeFalso())

    assert "NVDA" in msg
    assert "$87.40" in msg
    assert "+8.74%" in msg, "la fracción 0.0874 se imprime como 8.74%"
    assert "$13.40" in msg, "comisiones = compra + venta"


def test_el_mensaje_de_cierre_marca_la_perdida():
    perdedora = TradeFalso()
    perdedora.resultado_neto = -50.0
    perdedora.rendimiento_neto_pct = -0.05

    msg = notifications.mensaje_cierre_operacion(perdedora)

    assert "🔴" in msg
    assert "-50.00" in msg
    assert "-5.00%" in msg


def test_el_mensaje_de_senal_no_promete_ejecucion():
    msg = notifications.mensaje_senal(
        {
            "ticker": "MELI",
            "precio_entrada": 1966.25,
            "stop_loss": 1907.26,
            "take_profit": 2084.22,
            "pct_riesgo": 3.0,
            "sentimiento_score": 0.42,
            "rvol": 2.3,
            "es_acumulacion": True,
        }
    )

    assert "MELI" in msg
    assert "no se ejecutó nada" in msg
    assert "acumulación" in msg


# ---------- Endpoint de prueba (Tarea 7.1) ----------


@pytest.fixture
def client():
    return TestClient(app)


def test_el_endpoint_de_prueba_manda_el_mensaje_fijo(client, envios):
    respuesta = client.post("/notificaciones/test")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"enviado": True, "motivo": ""}
    assert envios[0]["payload"]["text"] == notifications.MENSAJE_DE_PRUEBA
    assert envios[0]["payload"]["parse_mode"] == "HTML"


def test_el_endpoint_de_prueba_no_falla_sin_credenciales(client, monkeypatch):
    monkeypatch.setattr(notifications.config, "TELEGRAM_BOT_TOKEN", "")

    respuesta = client.post("/notificaciones/test")

    assert respuesta.status_code == 200, "el motivo viaja en el cuerpo, no como error HTTP"
    assert respuesta.json()["enviado"] is False


# ---------- Alerta al cerrar una operación (Tarea 7.2) ----------


@pytest.fixture
def client_con_db():
    """TestClient sobre la base real del proyecto, limpiando lo que crea el test."""
    Base.metadata.create_all(bind=engine)
    creados = []
    with TestClient(app) as c:
        yield c, creados
        for trade_id in creados:
            c.delete(f"/trades/{trade_id}")


def test_cerrar_una_operacion_dispara_la_alerta(client_con_db, envios):
    client, creados = client_con_db

    alta = client.post(
        "/trades",
        json={
            "ticker": "TESTTG",
            "tipo": "CEDEAR",
            "fecha_compra": str(date(2026, 9, 1)),
            "cantidad": 10,
            "precio_entrada": 100.0,
            "senal": "Señal de prueba",
        },
    )
    assert alta.status_code == 201
    trade_id = alta.json()["id"]
    creados.append(trade_id)

    cierre = client.post(
        f"/trades/{trade_id}/cerrar",
        json={"fecha_venta": str(date(2026, 9, 4)), "precio_salida": 110.0},
    )
    assert cierre.status_code == 200

    assert len(envios) == 1, "un cierre = un aviso"
    texto = envios[0]["payload"]["text"]
    cuerpo = cierre.json()
    assert "TESTTG" in texto
    assert f"{cuerpo['resultado_neto']:,.2f}" in texto
    assert f"{cuerpo['rendimiento_neto_pct'] * 100:+.2f}%" in texto


def test_si_telegram_falla_el_cierre_igual_responde_200(client_con_db, monkeypatch, telegram_configurado):
    client, creados = client_con_db
    monkeypatch.setattr(
        notifications.requests,
        "post",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("sin red")),
    )

    alta = client.post(
        "/trades",
        json={
            "ticker": "TESTTG2",
            "tipo": "CEDEAR",
            "fecha_compra": str(date(2026, 9, 1)),
            "cantidad": 5,
            "precio_entrada": 50.0,
        },
    )
    trade_id = alta.json()["id"]
    creados.append(trade_id)

    cierre = client.post(
        f"/trades/{trade_id}/cerrar",
        json={"fecha_venta": str(date(2026, 9, 4)), "precio_salida": 45.0},
    )

    assert cierre.status_code == 200
    assert cierre.json()["precio_salida"] == 45.0
