"""
Autenticación de la API por clave en header.

Hasta ahora la API no tenía ninguna: cualquiera que llegara al puerto podía leer
`/iol/saldo` — saldo y tenencia reales de la cuenta comitente — y crear o borrar
operaciones. Por eso el backend estaba encerrado en `127.0.0.1` en el VPS. Esto
es la defensa que faltaba para que ese encierro no sea lo único que protege.

## Cómo se usa

Todas las rutas piden el header `X-API-Key`, salvo las públicas:

```bash
curl -H "X-API-Key: $API_KEY" http://127.0.0.1:8123/dashboard
```

## Falla cerrada

```mermaid
flowchart TD
    R[Request] --> P{¿ruta pública?}
    P -- sí --> OK[Pasa]
    P -- no --> D{¿API_AUTH_DESHABILITADA?}
    D -- sí --> WARN[Pasa<br/>con warning en el log]
    D -- no --> K{¿hay API_KEY configurada?}
    K -- no --> E503[503<br/>la API no está configurada]
    K -- sí --> H{¿header correcto?}
    H -- no --> E401[401]
    H -- sí --> OK
```

> [!warning] Sin `API_KEY` la API no atiende, no queda abierta
> Si faltara la clave y el default fuera "dejar pasar", un `.env` mal copiado
> dejaría la API abierta sin que nadie se entere. Correr sin auth es una decisión
> que hay que tomar a mano: `API_AUTH_DESHABILITADA=true`.

La comparación usa `secrets.compare_digest`: comparar con `==` filtra por tiempo
de respuesta cuántos caracteres del prefijo son correctos.
"""
import logging
import secrets

from fastapi import HTTPException, Request, status

from . import config

logger = logging.getLogger(__name__)

NOMBRE_HEADER = "X-API-Key"

# Rutas que nunca piden clave.
#
# `/health` queda afuera para que un monitor externo o `systemd` puedan sondear
# el servicio sin repartirle la credencial. No revela nada: devuelve `{"ok": true}`.
# La documentación interactiva se deja abierta porque la API vive en loopback y
# el esquema no expone datos, solo formas.
RUTAS_PUBLICAS = frozenset(
    {"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
)


def auth_activa() -> bool:
    """True si se va a exigir la clave en cada request."""
    return not config.API_AUTH_DESHABILITADA


def estado() -> dict:
    """Resumen para `/health` y para el log de arranque. Nunca incluye la clave."""
    if config.API_AUTH_DESHABILITADA:
        return {"activa": False, "motivo": "API_AUTH_DESHABILITADA=true"}
    if not config.API_KEY:
        return {"activa": True, "motivo": "falta API_KEY: la API responde 503"}
    return {"activa": True, "motivo": ""}


def advertir_al_arrancar() -> None:
    """Deja en el log, una vez, en qué modo quedó la API."""
    if config.API_AUTH_DESHABILITADA:
        logger.warning(
            "API SIN AUTENTICACIÓN (API_AUTH_DESHABILITADA=true). Aceptable solo si "
            "el backend escucha en 127.0.0.1. NO exponer así a internet."
        )
    elif not config.API_KEY:
        logger.error(
            "Falta API_KEY en el entorno: la API va a responder 503 a todo salvo "
            "/health. Generá una con: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    else:
        logger.info("Autenticación por %s activa.", NOMBRE_HEADER)


async def verificar_api_key(request: Request) -> None:
    """Dependencia global. Deja pasar o corta con 401/503.

    Se registra en `FastAPI(dependencies=[...])`, así protege **toda** ruta
    existente y futura sin que haya que acordarse de decorarla — que es
    exactamente el error que uno comete cuando agrega un endpoint nuevo.
    """
    if request.url.path in RUTAS_PUBLICAS:
        return

    # CORS manda un OPTIONS sin headers propios antes del request real. Si se le
    # respondiera 401, el navegador nunca llegaría a mandar el request con la clave.
    if request.method == "OPTIONS":
        return

    if config.API_AUTH_DESHABILITADA:
        return

    if not config.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "La API no tiene API_KEY configurada y por eso no atiende pedidos. "
                "Cargá API_KEY en backend/.env (ver .env.example), o poné "
                "API_AUTH_DESHABILITADA=true si de verdad querés correr sin auth."
            ),
        )

    recibida = request.headers.get(NOMBRE_HEADER, "")
    if not recibida or not secrets.compare_digest(recibida, config.API_KEY):
        # A propósito no se dice si faltaba o si estaba mal: es la misma respuesta.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Falta o no coincide el header {NOMBRE_HEADER}.",
            headers={"WWW-Authenticate": NOMBRE_HEADER},
        )
