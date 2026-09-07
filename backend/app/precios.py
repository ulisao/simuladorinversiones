"""
Precio **operativo**: el precio real en pesos al que se compra y se vende en BYMA.

Existe porque en el proyecto conviven dos precios distintos para el mismo activo,
y mezclarlos rompe cuentas de plata:

| Fuente | Qué devuelve | Para qué sirve |
|---|---|---|
| `market_data.get_last_price` (yfinance) | El **subyacente en USD** (AAPL = US$ 319,97) | Patrón técnico: ATR, EMAs, RSI, fuerza relativa |
| `precios.precio_operativo` (IOL) | El **CEDEAR/bono en ARS** (AAPL = $ 25.400) | Tamaño de posición, resultado neto, stop-loss |

> [!warning] Por qué esto no es un detalle
> `CAPITAL_TOTAL` está en pesos. Dividir $100.000 por el precio en dólares del
> subyacente da una cantidad de papeles ~80 veces más grande que la real. Y una
> posición abierta a $25.400 comparada contra un precio de US$ 319 se ve como una
> pérdida del 98,7%: el gestor de salidas dispararía el stop en el primer tick.

## Regla

**Todo lo que sea plata usa este módulo. Todo lo que sea patrón técnico usa
`market_data`.** Los bonos ya venían así (`bond_signals` lee de IOL); las
acciones y CEDEARs se alinearon acá.

Igual que el resto de los módulos que hablan con internet, no propaga la
excepción cruda: levanta `PrecioError`, que los llamadores tratan como "este
activo no se puede operar en este ciclo".
"""
import logging
from typing import Any, Optional

from . import broker_iol

logger = logging.getLogger(__name__)


class PrecioError(Exception):
    """No se pudo obtener un precio operativo confiable en pesos."""


def _a_float(valor: Any) -> Optional[float]:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero


def precio_operativo(simbolo: str, cliente: Optional[Any] = None) -> float:
    """Último precio operado en BYMA, en pesos.

    Args:
        simbolo: ticker de BYMA ("AL30", "AAPL", "GD30").
        cliente: `IOLClient` a usar. Se inyecta en los tests; por default sale de
            `broker_iol.get_client()`.

    Raises:
        PrecioError: IOL no configurado, símbolo inexistente, API caída o
            cotización en cero (pasa fuera del horario de rueda).
    """
    cli = cliente if cliente is not None else broker_iol.get_client()

    # `esta_configurado` es una property de IOLClient, no un método.
    if not cli.esta_configurado:
        raise PrecioError(
            "IOL no configurado (faltan IOL_USERNAME / IOL_PASSWORD): sin eso no hay "
            "precio en pesos y no se puede calcular ni el tamaño ni el resultado."
        )

    try:
        cotizacion = cli.get_cotizacion(simbolo)
    except broker_iol.IOLError as exc:
        raise PrecioError(f"{simbolo}: IOL no devolvió cotización ({exc})") from exc
    except Exception as exc:  # noqa: BLE001 — red caída, timeout, respuesta rara
        raise PrecioError(f"{simbolo}: error inesperado pidiendo cotización ({exc})") from exc

    precio = _a_float(cotizacion.get("ultimoPrecio"))
    if precio is None or precio <= 0:
        # Suele pasar fuera de rueda o con un papel que no operó en el día.
        raise PrecioError(
            f"{simbolo}: IOL devolvió un último precio no operable "
            f"({cotizacion.get('ultimoPrecio')!r}). Suele pasar fuera del horario de rueda."
        )

    return precio
