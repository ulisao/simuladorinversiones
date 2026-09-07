"""
Tests del cliente de InvertirOnline (Tareas 8.1, 8.2 y 8.4).

**Ningún test de acá le pega a IOL**: `requests` está siempre mockeado. Lo que
importa verificar:

* que instanciar el cliente **no toque la red** (si lo hiciera, importar el
  módulo o arrancar el backend con IOL caído se rompería),
* que un `401` con token aparentemente vigente se reintente **una sola vez**,
* que **nunca** se filtre la contraseña ni el token en logs ni en mensajes de
  error — es el punto central de la Tarea 8.3.
"""
import logging

import pytest

from app import broker_iol
from app.broker_iol import IOLClient, IOLError


USUARIO = "persona@ejemplo.com"
CLAVE = "contraseña-secreta-123"


class RespuestaFalsa:
    def __init__(self, status_code=200, cuerpo=None, texto=""):
        self.status_code = status_code
        self._cuerpo = cuerpo
        self.text = texto

    def json(self):
        if self._cuerpo is None:
            raise ValueError("sin JSON")
        return self._cuerpo


TOKEN_OK = {"access_token": "tok-abc", "refresh_token": "ref-xyz", "expires_in": 900}


def _cliente(**kwargs):
    kwargs.setdefault("username", USUARIO)
    kwargs.setdefault("password", CLAVE)
    kwargs.setdefault("api_url", "https://api.ejemplo.test")
    return IOLClient(**kwargs)


@pytest.fixture
def sin_red(monkeypatch):
    """Prohíbe cualquier llamada real; los tests inyectan lo que necesitan."""

    def prohibido(*a, **k):  # pragma: no cover
        raise AssertionError("este test no puede tocar la red")

    monkeypatch.setattr(broker_iol.requests, "post", prohibido)
    monkeypatch.setattr(broker_iol.requests, "request", prohibido)
    return monkeypatch


# ---------- Construcción perezosa ----------


def test_instanciar_no_toca_la_red(sin_red):
    """El manual loguea en `__init__`; acá no, a propósito."""
    cliente = _cliente()

    assert cliente.token_vigente is False
    assert cliente.esta_configurado is True


def test_sin_credenciales_el_login_falla_con_mensaje_util(sin_red):
    cliente = _cliente(username="", password="")

    with pytest.raises(IOLError) as exc:
        cliente.login()

    assert "IOL_USERNAME" in str(exc.value)


# ---------- Login ----------


def test_login_exitoso_guarda_token_y_refresh(monkeypatch):
    monkeypatch.setattr(
        broker_iol.requests, "post", lambda *a, **k: RespuestaFalsa(200, TOKEN_OK)
    )
    cliente = _cliente()

    cliente.login()

    assert cliente.token_vigente is True
    assert cliente.get_headers()["Authorization"] == "Bearer tok-abc"


def test_el_login_manda_grant_type_password(monkeypatch):
    enviados = {}

    def post(url, data=None, timeout=None):
        enviados.update({"url": url, "data": data})
        return RespuestaFalsa(200, TOKEN_OK)

    monkeypatch.setattr(broker_iol.requests, "post", post)
    _cliente().login()

    assert enviados["url"].endswith("/token")
    assert enviados["data"]["grant_type"] == "password"


def test_credenciales_rechazadas_dan_error_claro(monkeypatch):
    monkeypatch.setattr(
        broker_iol.requests,
        "post",
        lambda *a, **k: RespuestaFalsa(400, {"error_description": "invalid_grant"}),
    )

    with pytest.raises(IOLError) as exc:
        _cliente().login()

    assert "400" in str(exc.value)
    assert "invalid_grant" in str(exc.value)


def test_una_red_caida_no_propaga_la_excepcion_cruda(monkeypatch):
    def revienta(*a, **k):
        raise ConnectionError("sin internet")

    monkeypatch.setattr(broker_iol.requests, "post", revienta)

    with pytest.raises(IOLError) as exc:
        _cliente().login()

    assert "sin internet" in str(exc.value)


def test_una_respuesta_sin_access_token_es_error(monkeypatch):
    monkeypatch.setattr(
        broker_iol.requests, "post", lambda *a, **k: RespuestaFalsa(200, {"ok": True})
    )

    with pytest.raises(IOLError, match="access_token"):
        _cliente().login()


# ---------- Renovación ----------


def test_el_token_se_renueva_con_refresh_token(monkeypatch):
    llamadas = []

    def post(url, data=None, timeout=None):
        llamadas.append(data["grant_type"])
        return RespuestaFalsa(200, TOKEN_OK)

    monkeypatch.setattr(broker_iol.requests, "post", post)
    cliente = _cliente()
    cliente.login()          # password
    cliente.login()          # ya hay refresh_token

    assert llamadas == ["password", "refresh_token"]


def test_si_el_refresh_falla_se_reautentica_con_la_contrasena(monkeypatch):
    llamadas = []

    def post(url, data=None, timeout=None):
        llamadas.append(data["grant_type"])
        if data["grant_type"] == "refresh_token":
            return RespuestaFalsa(400, {"error": "invalid_grant"})
        return RespuestaFalsa(200, TOKEN_OK)

    monkeypatch.setattr(broker_iol.requests, "post", post)
    cliente = _cliente()
    cliente.login()
    cliente.login()

    assert llamadas == ["password", "refresh_token", "password"]
    assert cliente.token_vigente is True


def test_un_token_vencido_se_renueva_solo(monkeypatch):
    posts = []

    def post(url, data=None, timeout=None):
        posts.append(1)
        return RespuestaFalsa(200, TOKEN_OK)

    monkeypatch.setattr(broker_iol.requests, "post", post)
    cliente = _cliente()
    cliente.get_headers()
    cliente._token_expira_en = 0.0  # simula el vencimiento

    cliente.get_headers()

    assert len(posts) == 2


# ---------- Reintento ante 401 ----------


def test_un_401_se_reintenta_una_vez_reautenticando(monkeypatch):
    monkeypatch.setattr(
        broker_iol.requests, "post", lambda *a, **k: RespuestaFalsa(200, TOKEN_OK)
    )
    respuestas = [RespuestaFalsa(401, texto="expired"), RespuestaFalsa(200, {"ok": 1})]

    def request(metodo, url, **kwargs):
        return respuestas.pop(0)

    monkeypatch.setattr(broker_iol.requests, "request", request)

    assert _cliente().get("/api/v2/loquesea") == {"ok": 1}
    assert respuestas == [], "se consumieron las dos: hubo reintento"


def test_un_401_persistente_falla_ruidosamente(monkeypatch):
    """Un patrón de 401 repetidos es cómo el bot queda ciego sin que nadie lo note."""
    monkeypatch.setattr(
        broker_iol.requests, "post", lambda *a, **k: RespuestaFalsa(200, TOKEN_OK)
    )
    intentos = []

    def request(metodo, url, **kwargs):
        intentos.append(1)
        return RespuestaFalsa(401, texto="nope")

    monkeypatch.setattr(broker_iol.requests, "request", request)

    with pytest.raises(IOLError) as exc:
        _cliente().get("/api/v2/loquesea")

    assert len(intentos) == 2, "un solo reintento, no un bucle"
    assert "API habilitada" in str(exc.value)


def test_otros_errores_http_no_se_reintentan(monkeypatch):
    monkeypatch.setattr(
        broker_iol.requests, "post", lambda *a, **k: RespuestaFalsa(200, TOKEN_OK)
    )
    intentos = []

    def request(metodo, url, **kwargs):
        intentos.append(1)
        return RespuestaFalsa(500, {"message": "boom"})

    monkeypatch.setattr(broker_iol.requests, "request", request)

    with pytest.raises(IOLError, match="500"):
        _cliente().get("/api/v2/loquesea")

    assert len(intentos) == 1


# ---------- Que no se filtre nada (Tarea 8.3) ----------


def test_el_usuario_sale_ofuscado_en_los_logs(monkeypatch, caplog):
    monkeypatch.setattr(
        broker_iol.requests, "post", lambda *a, **k: RespuestaFalsa(200, TOKEN_OK)
    )

    with caplog.at_level(logging.INFO):
        _cliente().login()

    registrado = caplog.text
    assert USUARIO not in registrado, "el usuario completo no puede quedar en el log"
    assert "pe***@ejemplo.com" in registrado


def test_ningun_log_ni_error_contiene_la_contrasena(monkeypatch, caplog):
    monkeypatch.setattr(
        broker_iol.requests,
        "post",
        lambda *a, **k: RespuestaFalsa(400, {"error_description": "invalid_grant"}),
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(IOLError) as exc:
            _cliente().login()

    assert CLAVE not in str(exc.value)
    assert CLAVE not in caplog.text


def test_el_repr_no_filtra_el_token(monkeypatch):
    monkeypatch.setattr(
        broker_iol.requests, "post", lambda *a, **k: RespuestaFalsa(200, TOKEN_OK)
    )
    cliente = _cliente()
    cliente.login()

    texto = repr(cliente)

    assert "tok-abc" not in texto
    assert CLAVE not in texto
    assert USUARIO not in texto


# ---------- Lectura de cuenta (Tarea 8.2) ----------


ESTADO_CUENTA = {
    "cuentas": [
        {"moneda": "peso_Argentino", "disponible": 539.36, "titulosValorizados": 3072855.47,
         "total": 3073394.83},
        {"moneda": "dolar_Estadounidense", "disponible": 1000.0, "titulosValorizados": 0.0,
         "total": 1000.0},
    ]
}

PORTAFOLIO = {
    "pais": "argentina",
    "activos": [
        {
            "cantidad": 82.0, "ultimoPrecio": 83000.0, "ppc": 80732.439,
            "gananciaPorcentaje": 2.8, "gananciaDinero": 1859.4, "valorizado": 68060.0,
            "titulo": {"simbolo": "AL29", "descripcion": "Bono Rep Arg", "tipo": "TitulosPublicos",
                       "moneda": "peso_Argentino"},
        }
    ],
}


@pytest.fixture
def autenticado(monkeypatch):
    monkeypatch.setattr(
        broker_iol.requests, "post", lambda *a, **k: RespuestaFalsa(200, TOKEN_OK)
    )
    return monkeypatch


def _responder(monkeypatch, por_ruta):
    def request(metodo, url, **kwargs):
        for fragmento, cuerpo in por_ruta.items():
            if fragmento in url:
                return RespuestaFalsa(200, cuerpo)
        return RespuestaFalsa(404, texto=f"sin mock para {url}")

    monkeypatch.setattr(broker_iol.requests, "request", request)


def test_el_saldo_suma_solo_las_cuentas_en_pesos(autenticado):
    _responder(autenticado, {"estadocuenta": ESTADO_CUENTA})

    assert _cliente().get_saldo_disponible() == 539.36


def test_el_saldo_en_dolares_se_pide_aparte(autenticado):
    _responder(autenticado, {"estadocuenta": ESTADO_CUENTA})

    assert _cliente().get_saldo_disponible("dolar_Estadounidense") == 1000.0


def test_el_saldo_suma_varias_cuentas_de_la_misma_moneda(autenticado):
    estado = {"cuentas": [
        {"moneda": "peso_Argentino", "disponible": 100.0},
        {"moneda": "peso_Argentino", "disponible": 250.5},
    ]}
    _responder(autenticado, {"estadocuenta": estado})

    assert _cliente().get_saldo_disponible() == 350.5


def test_el_portafolio_se_aplana(autenticado):
    """El `titulo` anidado de IOL no tiene por qué llegar al resto del código."""
    _responder(autenticado, {"portafolio": PORTAFOLIO})

    posiciones = _cliente().get_portafolio()

    assert len(posiciones) == 1
    assert posiciones[0]["simbolo"] == "AL29"
    assert posiciones[0]["precio_promedio_compra"] == pytest.approx(80732.439)
    assert "titulo" not in posiciones[0]


def test_un_portafolio_vacio_devuelve_lista_vacia(autenticado):
    _responder(autenticado, {"portafolio": {"pais": "argentina", "activos": []}})

    assert _cliente().get_portafolio() == []


# ---------- Cotizaciones y CCL (Tarea 8.4) ----------


COTIZACION_AL30 = {"ultimoPrecio": 85300.0, "moneda": "peso_Argentino", "puntas": [],
                   "fechaHora": "2026-09-04T17:00:06.943"}
COTIZACION_AL30D = {"ultimoPrecio": 55.92, "moneda": "dolar_Estadounidense", "puntas": []}


def test_el_ccl_es_el_cociente_entre_las_dos_puntas_del_mismo_bono(autenticado):
    _responder(autenticado, {"AL30D": COTIZACION_AL30D, "AL30": COTIZACION_AL30})

    ccl = _cliente().get_valor_ccl()

    assert ccl["ccl"] == pytest.approx(85300.0 / 55.92, abs=0.01)
    assert ccl["bono_pesos"] == "AL30"
    assert ccl["bono_dolares"] == "AL30D"


def test_sin_cotizacion_el_ccl_falla_con_un_motivo_entendible(autenticado):
    _responder(autenticado, {"AL30D": {"ultimoPrecio": 0.0}, "AL30": COTIZACION_AL30})

    with pytest.raises(IOLError) as exc:
        _cliente().get_valor_ccl()

    assert "horario de rueda" in str(exc.value)


def test_sin_puntas_devuelve_none_y_no_ceros(autenticado):
    """Verificado contra la API real: fuera de rueda `puntas` viene vacío."""
    _responder(autenticado, {"AL30": COTIZACION_AL30})

    assert _cliente().get_puntas("AL30") is None


def test_con_puntas_devuelve_bid_y_ask(autenticado):
    cotizacion = dict(COTIZACION_AL30)
    cotizacion["puntas"] = [
        {"precioCompra": 85000.0, "precioVenta": 85400.0,
         "cantidadCompra": 100.0, "cantidadVenta": 50.0}
    ]
    _responder(autenticado, {"AL30": cotizacion})

    puntas = _cliente().get_puntas("AL30")

    assert puntas["bid"] == 85000.0
    assert puntas["ask"] == 85400.0


def test_puntas_en_cero_se_tratan_como_ausentes(autenticado):
    cotizacion = dict(COTIZACION_AL30)
    cotizacion["puntas"] = [{"precioCompra": 0.0, "precioVenta": 0.0}]
    _responder(autenticado, {"AL30": cotizacion})

    assert _cliente().get_puntas("AL30") is None


# ---------- Singleton ----------


def test_get_client_devuelve_siempre_el_mismo(sin_red):
    broker_iol.reiniciar_cliente()
    try:
        assert broker_iol.get_client() is broker_iol.get_client()
    finally:
        broker_iol.reiniciar_cliente()


# ---------- Endpoints HTTP (Tareas 8.2 y 8.4) ----------


from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


class ClienteFalso:
    """Doble de `IOLClient` que devuelve lo inyectado, o levanta IOLError."""

    def __init__(self, estado=None, portafolio=None, ccl=None, error=None):
        self._estado = estado
        self._portafolio = portafolio
        self._ccl = ccl
        self._error = error

    def _o_falla(self, valor):
        if self._error:
            raise IOLError(self._error)
        return valor

    def get_estado_cuenta(self):
        return self._o_falla(self._estado)

    def get_portafolio(self, pais="argentina"):
        return self._o_falla(self._portafolio)

    def get_valor_ccl(self, bono_pesos="AL30", bono_dolares="AL30D"):
        return self._o_falla(self._ccl)


@pytest.fixture
def client():
    return TestClient(app)


def _inyectar(monkeypatch, cliente):
    monkeypatch.setattr(broker_iol, "get_client", lambda: cliente)


def test_endpoint_saldo_devuelve_los_totales_en_pesos(client, monkeypatch):
    _inyectar(
        monkeypatch,
        ClienteFalso(
            estado=ESTADO_CUENTA,
            portafolio=[{"simbolo": "AL29", "descripcion": "Bono", "tipo": "TitulosPublicos",
                         "moneda": "peso_Argentino", "cantidad": 82.0,
                         "precio_promedio_compra": 80732.44, "ultimo_precio": 83000.0,
                         "valorizado": 68060.0, "ganancia_pct": 2.8, "ganancia_dinero": 1859.4}],
        ),
    )

    r = client.get("/iol/saldo")

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["disponible"] == 539.36, "solo las cuentas en pesos"
    assert cuerpo["total"] == 3073394.83
    assert cuerpo["posiciones"][0]["simbolo"] == "AL29"


def test_si_iol_falla_el_endpoint_de_saldo_devuelve_503(client, monkeypatch):
    """503 y no 500: el problema es el servicio de arriba, no nuestro backend."""
    _inyectar(monkeypatch, ClienteFalso(error="IOL no responde"))

    r = client.get("/iol/saldo")

    assert r.status_code == 503
    assert "IOL no responde" in r.json()["detail"]


def test_endpoint_ccl(client, monkeypatch):
    _inyectar(
        monkeypatch,
        ClienteFalso(ccl={"ccl": 1525.39, "bono_pesos": "AL30", "precio_pesos": 85300.0,
                          "bono_dolares": "AL30D", "precio_dolares": 55.92,
                          "fecha_hora": "2026-09-04T17:00:06.943"}),
    )

    r = client.get("/mercado/ccl")

    assert r.status_code == 200
    assert r.json()["ccl"] == 1525.39


def test_si_no_hay_cotizacion_el_ccl_devuelve_503(client, monkeypatch):
    _inyectar(monkeypatch, ClienteFalso(error="fuera del horario de rueda"))

    r = client.get("/mercado/ccl")

    assert r.status_code == 503
