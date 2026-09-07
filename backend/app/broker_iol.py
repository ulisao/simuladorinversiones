"""
Cliente de la API de InvertirOnline (Tarea 8.1).

Autenticación OAuth2 contra IOL y mantenimiento del token vigente. Es la única
puerta del sistema hacia el broker: todo lo que necesite hablar con IOL pasa por
acá.

> **Modo lectura.** Este módulo no envía órdenes. La ejecución real es la Fase 11
> y está detrás del kill switch `MODO_FANTASMA`, que hoy vale `True`.

## Ciclo de vida del token

```mermaid
stateDiagram-v2
    [*] --> SinToken
    SinToken --> Autenticado: login() con usuario y contraseña
    Autenticado --> Autenticado: get_headers() mientras no venza
    Autenticado --> Renovando: token por vencer
    Renovando --> Autenticado: refresh_token
    Renovando --> SinToken: el refresh falló → se reintenta con contraseña
    Autenticado --> SinToken: la API devolvió 401
```

## Diferencias deliberadas con el código del manual

| Manual (sección 7) | Acá | Por qué |
|---|---|---|
| `login()` dentro de `__init__` | Login perezoso, en el primer uso | Instanciar el cliente no puede pegarle a la red: rompería importar el módulo, los tests y el arranque del backend si IOL está caído |
| Ignora el `refresh_token` | Lo usa, y cae a la contraseña si falla | Mandar la contraseña en cada renovación es peor: el refresh existe justo para no hacerlo |
| Solo maneja el vencimiento por tiempo | Además reintenta **una vez** ante un `401` | Un token puede quedar invalidado del lado de IOL antes de vencer. Sin esto el bot "queda ciego" sin que nadie lo note — es el modo de falla más común |
| `print("Autenticación exitosa")` | `logger.info`, y **nunca** loguea token ni contraseña | Tarea 8.3 |

## Errores

Todo falla con `IOLError`, con un mensaje en español listo para mostrar. El
endpoint que llame lo traduce a HTTP, igual que hace `main.py` con
`MarketDataError`. Nunca se propaga una excepción cruda de `requests`.
"""
import logging
import threading
import time
from typing import Any, Dict, Optional

import requests

from . import config

logger = logging.getLogger(__name__)

TIMEOUT_SEG = 20

# Margen antes del vencimiento real del token. Si pedimos justo en el límite, la
# llamada puede salir con un token que expira en tránsito.
MARGEN_RENOVACION_SEG = 60

# Cuánto dura el token si IOL no lo informa. El valor real hoy son 900 s.
EXPIRACION_POR_DEFECTO_SEG = 900

RUTA_TOKEN = "/token"


class IOLError(Exception):
    """Error controlado hablando con IOL (login fallido, red caída, API con error)."""


class IOLClient:
    """Sesión autenticada contra la API de InvertirOnline.

    Se instancia sin tocar la red: la autenticación ocurre en el primer pedido
    que la necesite. Es seguro tenerlo como singleton de proceso — `get_headers`
    serializa las renovaciones con un lock, así dos pedidos concurrentes no
    disparan dos logins.

    Args:
        username: usuario de IOL. Default `config.IOL_USERNAME`.
        password: contraseña. Default `config.IOL_PASSWORD`.
        api_url: base de la API. Default `config.IOL_API_URL`.

    Raises:
        IOLError: en `login()` y en cualquier pedido, si IOL no responde o
            rechaza las credenciales.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        api_url: Optional[str] = None,
    ) -> None:
        self.username = config.IOL_USERNAME if username is None else username
        self.password = config.IOL_PASSWORD if password is None else password
        self.api_url = (config.IOL_API_URL if api_url is None else api_url).rstrip("/")

        self._token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expira_en: float = 0.0
        self._lock = threading.Lock()

    # ---------- Estado ----------

    @property
    def esta_configurado(self) -> bool:
        """True si hay usuario y contraseña cargados en el entorno."""
        return bool(self.username and self.password)

    @property
    def token_vigente(self) -> bool:
        return bool(self._token) and time.time() < self._token_expira_en

    # ---------- Autenticación ----------

    def login(self, usar_refresh: bool = True) -> None:
        """Obtiene un Bearer Token nuevo. Nunca deja el cliente a medio autenticar.

        Intenta primero con el `refresh_token` (si hay uno y `usar_refresh`), y
        cae a usuario/contraseña si el refresh no sirve.

        Raises:
            IOLError: credenciales ausentes, rechazadas, o IOL inalcanzable.
        """
        if not self.esta_configurado:
            raise IOLError(
                "Faltan credenciales de IOL: cargá IOL_USERNAME e IOL_PASSWORD en "
                "backend/.env (ver .env.example)."
            )

        if usar_refresh and self._refresh_token:
            try:
                self._pedir_token(
                    {"refresh_token": self._refresh_token, "grant_type": "refresh_token"}
                )
                logger.info("Token de IOL renovado con refresh_token.")
                return
            except IOLError as exc:
                # El refresh puede haber caducado o haber sido invalidado. No es
                # un error todavía: para eso está la contraseña.
                logger.info("El refresh_token de IOL no sirvió (%s), se reautentica.", exc)
                self._refresh_token = None

        self._pedir_token(
            {
                "username": self.username,
                "password": self.password,
                "grant_type": "password",
            }
        )
        logger.info("Autenticación exitosa en IOL (usuario %s).", self._usuario_ofuscado())

    def _pedir_token(self, payload: Dict[str, str]) -> None:
        """POST a /token. Guarda el token o levanta IOLError.

        `payload` lleva la contraseña: **nunca** se loguea ni se incluye en el
        mensaje de error.
        """
        url = f"{self.api_url}{RUTA_TOKEN}"
        try:
            respuesta = requests.post(url, data=payload, timeout=TIMEOUT_SEG)
        except Exception as exc:  # noqa: BLE001 — red caída, DNS, timeout
            raise IOLError(f"No se pudo contactar a IOL ({url}): {exc}") from exc

        if respuesta.status_code != 200:
            raise IOLError(
                f"IOL rechazó la autenticación (HTTP {respuesta.status_code}): "
                f"{_detalle_error(respuesta)}"
            )

        try:
            datos = respuesta.json()
        except Exception as exc:  # noqa: BLE001
            raise IOLError(f"IOL devolvió una respuesta de token ilegible: {exc}") from exc

        token = datos.get("access_token")
        if not token:
            raise IOLError("La respuesta de IOL no trae 'access_token'.")

        self._token = token
        self._refresh_token = datos.get("refresh_token") or self._refresh_token
        duracion = _entero(datos.get("expires_in"), EXPIRACION_POR_DEFECTO_SEG)
        self._token_expira_en = time.time() + duracion - MARGEN_RENOVACION_SEG

    def get_headers(self) -> Dict[str, str]:
        """Headers con el Bearer Token, renovándolo si hace falta.

        Raises:
            IOLError: si no se puede obtener un token.
        """
        with self._lock:
            if not self.token_vigente:
                self.login()
            return {"Authorization": f"Bearer {self._token}"}

    def invalidar_token(self) -> None:
        """Descarta el token vigente para forzar una reautenticación."""
        with self._lock:
            self._token = None
            self._token_expira_en = 0.0

    # ---------- Pedidos ----------

    def get(self, ruta: str, **kwargs: Any) -> Any:
        """GET autenticado contra la API, devolviendo el JSON ya parseado.

        Reintenta **una sola vez** ante un `401`: el token puede haber quedado
        invalidado del lado de IOL antes de vencer por tiempo, y sin este
        reintento el bot se queda ciego sin que nadie lo note.

        Args:
            ruta: camino relativo, por ejemplo `/api/v2/estadocuenta`.

        Raises:
            IOLError: red caída, 401 persistente, o cualquier HTTP de error.
        """
        return self._pedir("GET", ruta, **kwargs)

    def _pedir(self, metodo: str, ruta: str, reintentos: int = 1, **kwargs: Any) -> Any:
        url = f"{self.api_url}{ruta if ruta.startswith('/') else '/' + ruta}"

        try:
            respuesta = requests.request(
                metodo, url, headers=self.get_headers(), timeout=TIMEOUT_SEG, **kwargs
            )
        except IOLError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise IOLError(f"No se pudo contactar a IOL ({url}): {exc}") from exc

        if respuesta.status_code == 401 and reintentos > 0:
            logger.warning(
                "IOL devolvió 401 en %s con un token que parecía vigente: "
                "se reautentica y se reintenta una vez.",
                ruta,
            )
            self.invalidar_token()
            return self._pedir(metodo, ruta, reintentos=reintentos - 1, **kwargs)

        if respuesta.status_code == 401:
            # Explícito y ruidoso a propósito: un patrón de 401 repetidos es la
            # forma más común de que el bot quede ciego en silencio.
            raise IOLError(
                "IOL sigue devolviendo 401 después de reautenticar. Revisá que el "
                "usuario tenga la API habilitada y que la contraseña sea la vigente."
            )

        if respuesta.status_code >= 400:
            raise IOLError(
                f"IOL respondió HTTP {respuesta.status_code} en {ruta}: "
                f"{_detalle_error(respuesta)}"
            )

        try:
            return respuesta.json()
        except Exception as exc:  # noqa: BLE001
            raise IOLError(f"IOL devolvió una respuesta ilegible en {ruta}: {exc}") from exc

    # ---------- Lectura de cuenta y mercado ----------
    #
    # Rutas verificadas contra la API real el 2026-09-07. El plan (Tarea 11.1)
    # avisa que los manuales y el chat de Gemini no coinciden en algunas: estas
    # están confirmadas con una llamada de verdad, no copiadas de un doc.

    def get_estado_cuenta(self) -> Dict[str, Any]:
        """Estado de cuenta completo, tal cual lo devuelve IOL."""
        return self._pedir("GET", "/api/v2/estadocuenta")

    def get_saldo_disponible(self, moneda: str = "peso_Argentino") -> float:
        """Saldo líquido disponible para operar, en la moneda pedida.

        Suma el `disponible` de todas las cuentas de esa moneda: una cuenta
        comitente puede tener más de una (por ejemplo inversión y corriente).

        Raises:
            IOLError: si no se puede consultar la cuenta.
        """
        cuentas = self.get_estado_cuenta().get("cuentas") or []
        return round(
            sum(
                float(c.get("disponible") or 0.0)
                for c in cuentas
                if c.get("moneda") == moneda
            ),
            2,
        )

    def get_portafolio(self, pais: str = "argentina") -> list:
        """Tenencia actual, normalizada a lo que le importa al sistema.

        Aplana el `titulo` anidado que devuelve IOL para no arrastrar su forma
        exacta al resto del código.
        """
        activos = self._pedir("GET", f"/api/v2/portafolio/{pais}").get("activos") or []
        salida = []
        for a in activos:
            titulo = a.get("titulo") or {}
            salida.append(
                {
                    "simbolo": titulo.get("simbolo"),
                    "descripcion": titulo.get("descripcion"),
                    "tipo": titulo.get("tipo"),
                    "moneda": titulo.get("moneda"),
                    "cantidad": float(a.get("cantidad") or 0.0),
                    "precio_promedio_compra": float(a.get("ppc") or 0.0),
                    "ultimo_precio": float(a.get("ultimoPrecio") or 0.0),
                    "valorizado": float(a.get("valorizado") or 0.0),
                    "ganancia_pct": float(a.get("gananciaPorcentaje") or 0.0),
                    "ganancia_dinero": float(a.get("gananciaDinero") or 0.0),
                }
            )
        return salida

    def get_cotizacion(self, simbolo: str, mercado: str = "bCBA") -> Dict[str, Any]:
        """Cotización de un título en BYMA. **Precio real en pesos**, a diferencia
        de `market_data`, que devuelve el subyacente en USD (ver Tarea 2.1).

        Args:
            simbolo: ticker en BYMA ("AL30", "AAPL", "GD30D", ...).
            mercado: mercado de IOL. "bCBA" es BYMA.

        Raises:
            IOLError: símbolo inexistente, sin cotización o API caída.
        """
        return self._pedir("GET", f"/api/v2/{mercado}/Titulos/{simbolo.upper()}/Cotizacion")

    def get_puntas(self, simbolo: str, mercado: str = "bCBA") -> Optional[Dict[str, float]]:
        """Mejor punta compradora y vendedora, o None si el libro está vacío.

        > **Fuera del horario de rueda `puntas` viene como lista vacía.** Está
        > verificado contra la API. Por eso devuelve `None` en vez de `(0, 0)`:
        > un spread calculado sobre ceros sería peor que no tener el dato, y los
        > filtros de liquidez ya saben degradar cuando falta.
        """
        cotizacion = self.get_cotizacion(simbolo, mercado)
        puntas = cotizacion.get("puntas") or []
        if not puntas:
            return None

        mejor = puntas[0]
        bid = float(mejor.get("precioCompra") or 0.0)
        ask = float(mejor.get("precioVenta") or 0.0)
        if bid <= 0 or ask <= 0:
            return None

        return {
            "bid": bid,
            "ask": ask,
            "cantidad_compra": float(mejor.get("cantidadCompra") or 0.0),
            "cantidad_venta": float(mejor.get("cantidadVenta") or 0.0),
        }

    def get_valor_ccl(self, bono_pesos: str = "AL30", bono_dolares: str = "AL30D") -> Dict[str, Any]:
        """Dólar Contado con Liquidación implícito (Tarea 8.4).

        Se calcula con el mismo bono cotizando en las dos monedas: el cociente
        entre el precio en pesos y el precio en dólares es el tipo de cambio al
        que el mercado liquida.

        Raises:
            IOLError: si alguno de los dos no cotiza en este momento.
        """
        en_pesos = self.get_cotizacion(bono_pesos)
        en_dolares = self.get_cotizacion(bono_dolares)

        precio_pesos = float(en_pesos.get("ultimoPrecio") or 0.0)
        precio_dolares = float(en_dolares.get("ultimoPrecio") or 0.0)

        if precio_pesos <= 0 or precio_dolares <= 0:
            raise IOLError(
                f"No se puede calcular el CCL: {bono_pesos}={precio_pesos}, "
                f"{bono_dolares}={precio_dolares}. Suele pasar fuera del horario "
                "de rueda o si el bono no operó todavía."
            )

        return {
            "ccl": round(precio_pesos / precio_dolares, 2),
            "bono_pesos": bono_pesos,
            "precio_pesos": precio_pesos,
            "bono_dolares": bono_dolares,
            "precio_dolares": precio_dolares,
            "fecha_hora": en_pesos.get("fechaHora"),
        }

    # ---------- Utilidades ----------

    def _usuario_ofuscado(self) -> str:
        """Usuario con el grueso tapado, para que un log no lo filtre entero."""
        if not self.username:
            return "(sin usuario)"
        if "@" in self.username:
            nombre, dominio = self.username.split("@", 1)
            return f"{nombre[:2]}***@{dominio}"
        return f"{self.username[:2]}***"

    def __repr__(self) -> str:  # pragma: no cover — solo para logs
        estado = "autenticado" if self.token_vigente else "sin token"
        return f"IOLClient(usuario={self._usuario_ofuscado()}, {estado})"


def _detalle_error(respuesta: requests.Response) -> str:
    """Mensaje de error de IOL, recortado y sin volcar el cuerpo entero."""
    try:
        cuerpo = respuesta.json()
    except Exception:  # noqa: BLE001
        return (getattr(respuesta, "text", "") or "")[:300]
    if isinstance(cuerpo, dict):
        detalle = (
            cuerpo.get("error_description")
            or cuerpo.get("message")
            or cuerpo.get("error")
            or cuerpo
        )
        return str(detalle)[:300]
    return str(cuerpo)[:300]


def _entero(valor: Any, default: int) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return default


# ---------- Singleton de proceso ----------
#
# Un cliente por proceso: el token se comparte entre endpoints y jobs, así no se
# pide uno nuevo por cada request.

_cliente: Optional[IOLClient] = None
_cliente_lock = threading.Lock()


def get_client() -> IOLClient:
    """Cliente compartido del proceso. No toca la red hasta el primer pedido."""
    global _cliente
    with _cliente_lock:
        if _cliente is None:
            _cliente = IOLClient()
        return _cliente


def reiniciar_cliente() -> None:
    """Descarta el cliente compartido. Solo para los tests."""
    global _cliente
    with _cliente_lock:
        _cliente = None
