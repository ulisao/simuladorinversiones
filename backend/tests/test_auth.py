"""
Tests de la autenticación por API key.

Lo que importa acá no es que la clave correcta funcione — eso es lo fácil — sino
que **no haya forma de entrar sin ella**: que la protección alcance a todas las
rutas (incluidas las que se agreguen mañana), que falle cerrada si falta la
configuración, y que `/health` siga siendo sondeable sin credencial.
"""
import pytest
from fastapi.testclient import TestClient

from app import auth, config
from app.main import app

CLAVE = "clave-de-prueba-muy-larga-y-aleatoria"


@pytest.fixture
def cliente():
    return TestClient(app)


@pytest.fixture
def con_auth(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", CLAVE)
    monkeypatch.setattr(config, "API_AUTH_DESHABILITADA", False)


@pytest.fixture
def sin_clave(monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    monkeypatch.setattr(config, "API_AUTH_DESHABILITADA", False)


# ---------- Rutas públicas ----------


def test_health_no_pide_clave(cliente, con_auth):
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_dice_si_la_auth_esta_activa_sin_filtrar_la_clave(cliente, con_auth):
    respuesta = cliente.get("/health")
    assert respuesta.json()["auth"] == {"activa": True, "motivo": ""}
    assert CLAVE not in respuesta.text, "/health no puede devolver la clave"


def test_la_documentacion_queda_abierta(cliente, con_auth):
    assert cliente.get("/openapi.json").status_code == 200


# ---------- Rutas protegidas ----------


@pytest.mark.parametrize(
    "metodo,ruta",
    [
        ("get", "/dashboard"),
        ("get", "/trades"),
        ("get", "/broker-config"),
        ("get", "/sync/sheets"),
        ("delete", "/trades/1"),
    ],
)
def test_sin_header_da_401(cliente, con_auth, metodo, ruta):
    r = getattr(cliente, metodo)(ruta)
    assert r.status_code == 401, f"{metodo.upper()} {ruta} quedó sin proteger"


def test_con_clave_incorrecta_da_401(cliente, con_auth):
    r = cliente.get("/dashboard", headers={auth.NOMBRE_HEADER: "clave-equivocada"})
    assert r.status_code == 401


def test_con_clave_correcta_pasa(cliente, con_auth):
    r = cliente.get("/dashboard", headers={auth.NOMBRE_HEADER: CLAVE})
    assert r.status_code == 200


def test_el_401_no_revela_si_faltaba_o_estaba_mal(cliente, con_auth):
    sin = cliente.get("/dashboard").json()["detail"]
    mala = cliente.get(
        "/dashboard", headers={auth.NOMBRE_HEADER: "otra"}
    ).json()["detail"]
    assert sin == mala


def test_una_clave_con_prefijo_correcto_igual_falla(cliente, con_auth):
    """`compare_digest` no filtra por tiempo cuántos caracteres acertaste."""
    r = cliente.get("/dashboard", headers={auth.NOMBRE_HEADER: CLAVE[:-1]})
    assert r.status_code == 401


def test_la_proteccion_alcanza_a_toda_ruta_no_publica():
    """Ninguna ruta nueva puede quedar sin proteger por olvido.

    La dependencia se registra a nivel de app, no por endpoint: este test fija
    esa propiedad para que nadie la rompa moviéndola a los decoradores.
    """
    rutas = {
        r.path
        for r in app.routes
        if getattr(r, "methods", None) and r.path not in auth.RUTAS_PUBLICAS
    }
    assert rutas, "no se encontraron rutas para verificar"
    globales = {d.dependency for d in app.router.dependencies}
    assert auth.verificar_api_key in globales


# ---------- Falla cerrada ----------


def test_sin_api_key_configurada_responde_503_no_deja_pasar(cliente, sin_clave):
    r = cliente.get("/dashboard")
    assert r.status_code == 503
    assert "API_KEY" in r.json()["detail"]


def test_sin_api_key_health_sigue_respondiendo(cliente, sin_clave):
    r = cliente.get("/health")
    assert r.status_code == 200
    assert r.json()["auth"]["activa"] is True
    assert "falta API_KEY" in r.json()["auth"]["motivo"]


def test_se_puede_apagar_la_auth_pero_hay_que_pedirlo_explicitamente(
    cliente, monkeypatch
):
    monkeypatch.setattr(config, "API_KEY", "")
    monkeypatch.setattr(config, "API_AUTH_DESHABILITADA", True)
    assert cliente.get("/dashboard").status_code == 200
    assert cliente.get("/health").json()["auth"] == {
        "activa": False,
        "motivo": "API_AUTH_DESHABILITADA=true",
    }


# ---------- CORS ----------


def test_el_cors_ya_no_es_comodin():
    assert "*" not in config.CORS_ORIGINS
    assert any("localhost:3000" in o for o in config.CORS_ORIGINS)
