"""
Orquestación del escaneo de señales de renta fija (Tarea 9.4).

Es el equivalente de `signals.py` para bonos soberanos y provinciales. La
diferencia de fondo con el escaneo de CEDEARs no es el orden de los filtros sino
**de dónde sale el precio**: acá la cotización es el precio real en pesos (o en
dólares) de BYMA, traído de InvertirOnline vía `broker_iol.IOLClient`, y no el
subyacente en USD de Yahoo Finance que usa `market_data` (ver la advertencia de
la Tarea 2.1). Por eso este módulo no arrastra `ADVERTENCIA_PRECIO_REFERENCIA`.

## Orden de chequeos

Es la secuencia de `bot_bonds.ejecutar_ciclo` (sección 7 del manual de bonos),
**sin la parte de `comprar_bono_ci`**: acá no se manda ninguna orden.

```mermaid
flowchart TD
    IOL{{"IOL configurado<br/>y autenticado"}} -->|no| CORTE["veto_global<br/>candidatos = []"]
    IOL -->|sí| LOOP["por cada bono de<br/>config.UNIVERSO_BONOS"]
    LOOP --> CUP["1 · ventana de corte de cupón<br/>(calendario, sin red)"]
    CUP -->|veta| DESC[["descartados<br/>+ motivo + etapa"]]
    CUP --> NOT["2 · noticias de deuda<br/>risk_filters.estado_sentimiento_bonos"]
    NOT -->|veta| DESC
    NOT --> COT["3 · cotización real en CI<br/>IOLClient.get_cotizacion"]
    COT -->|error / sin precio| DESC
    COT --> SPR["4 · spread bid/ask<br/>no bloqueante si no hay puntas"]
    SPR -->|veta| DESC
    SPR --> FIF["5 · filtros institucionales<br/>fixed_income_filters"]
    FIF -->|veta| DESC
    FIF --> CTX["6 · contexto smart money<br/>informativo, nunca veta"]
    CTX --> CAND[["candidatos"]]
```

El paso 1 va **antes** de tocar la red a propósito: la ventana de corte de cupón
se resuelve con el calendario y `config.MESES_CORTE_CUPON`, así que un bono que
paga renta esta semana se descarta sin gastar una llamada a FinBERT ni a IOL.

> [!note] El veto de cupón está en los dos lados, y eso es deliberado
> `fixed_income_filters.evaluate_bond_filters` lo vuelve a evaluar en el paso 5
> (es su filtro 1) y sigue siendo la fuente de verdad. Acá se adelanta solo como
> atajo de red, con el mismo mensaje y los mismos parámetros de `config.py`: si
> alguna vez discrepan, manda el módulo de filtros.

## Por qué las puntas salen de la cotización y no de `get_puntas`

| Opción | Llamadas HTTP por bono | Consistencia | Elegido |
|---|---|---|---|
| `IOLClient.get_puntas(simbolo)` | 2 (vuelve a pedir la cotización entera) | El spread puede quedar de un snapshot distinto al del último precio | no |
| Leer `puntas` de la cotización ya traída | 1 | Precio y puntas del mismo instante | **sí** |

El parseo replica exactamente el de `IOLClient.get_puntas` (`precioCompra` /
`precioVenta` de la primera punta), y devuelve `None` en los mismos casos.

> [!warning] Fuera del horario de rueda `puntas` viene vacío
> Verificado contra la API real: `"puntas": []`. Por eso el chequeo de spread es
> **no bloqueante cuando no hay dato** — mismo criterio que
> `rsi_signal.chequear_liquidez`. Inventar un spread o vetar todo el universo
> serían las dos peores salidas: el escaneo informa `spread_disponible=False` y
> sigue. Cuando las puntas existen, el veto de `config.SPREAD_BID_ASK_MAX` sí
> bloquea.

## Reglas del repo que aplican acá

* Ningún parámetro de riesgo se hardcodea: todo sale de `config.py`.
* Los motivos de veto no se pierden nunca: todo lo descartado sale en
  `descartados`, con `motivo` y con la `etapa` en la que se cayó.
* Un bono roto no puede tumbar el escaneo del resto: cada iteración va envuelta
  en su propio `try/except`.
* Si IOL no está configurado o el login falla, la respuesta es controlada
  (`veto_global` con el motivo y `candidatos: []`), nunca una excepción.

Referencia de spec: `docs/specs-txt/Manual_Maestro_Bot_Bonos_Soberanos_Provinciales.txt`,
sección 7 (`bot_bonds.py`, método `ejecutar_ciclo`).
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from . import broker_iol
from . import config
from . import fixed_income_filters
from . import market_data
from . import risk_filters
from . import smart_money


# Etapa en la que se cayó un bono descartado. Sirve para auditar el escaneo sin
# tener que parsear el texto del motivo.
ETAPA_CUPON = "CUPON"
ETAPA_NOTICIAS = "NOTICIAS"
ETAPA_COTIZACION = "COTIZACION"
ETAPA_SPREAD = "SPREAD"
ETAPA_FILTROS = "FILTROS"
ETAPA_ERROR = "ERROR"

# Clasificación del bono dentro del universo (`config.BONOS_SOBERANOS` /
# `config.BONOS_PROVINCIALES`).
TIPO_SOBERANO = "SOBERANO"
TIPO_PROVINCIAL = "PROVINCIAL"
TIPO_DESCONOCIDO = "DESCONOCIDO"

# Ventana de histórico que se le pide a Yahoo para EMA20 + ATR(14).
# `fixed_income_filters` necesita al menos 30 ruedas; 60 días de calendario dan
# ~41. Si no alcanza, ese módulo entra solo en su modo degradado.
PERIODO_HISTORICO = market_data.PERIODO_DEFAULT

# Contracara positiva de `market_data.ADVERTENCIA_PRECIO_REFERENCIA`: acá el
# precio sí es operable.
NOTA_PRECIO_REAL = (
    "Precio real de BYMA provisto por InvertirOnline (Contado Inmediato), en la "
    "moneda que informa cada bono. A diferencia de las señales de CEDEARs, no es "
    "una referencia técnica del subyacente en USD."
)


# ---------- Helpers internos ----------


def _ahora() -> datetime:
    """Momento actual. Aislado para poder fijarlo en los tests."""
    return datetime.now()


def _a_float(valor: Any) -> Optional[float]:
    """Convierte a float, o `None` si no es numérico / es NaN."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    if numero != numero:  # NaN
        return None
    return numero


def _tipo_de_bono(simbolo: str) -> str:
    """SOBERANO / PROVINCIAL según las listas de `config.py`."""
    if simbolo in config.BONOS_SOBERANOS:
        return TIPO_SOBERANO
    if simbolo in config.BONOS_PROVINCIALES:
        return TIPO_PROVINCIAL
    return TIPO_DESCONOCIDO


def _ticker_yf(simbolo: str) -> str:
    """Símbolo con el sufijo de Yahoo para instrumentos locales ("AL30" -> "AL30.BA")."""
    return f"{simbolo}{config.SUFIJO_YF_BYMA}"


def _veto_corte_cupon(simbolo: str, momento: Any) -> Optional[str]:
    """
    Motivo del veto por ventana de corte de cupón, o `None` si el bono pasa.

    Misma regla (y mismo texto) que el filtro 1 de
    `fixed_income_filters.evaluate_bond_filters`, adelantada acá para no gastar
    llamadas de red en un bono que ya está descartado por calendario. Los bonos
    que no figuran en `config.MESES_CORTE_CUPON` no tienen calendario cargado y
    pasan siempre.
    """
    meses_corte = config.MESES_CORTE_CUPON.get(simbolo, [])
    if momento.month in meses_corte and (
        config.CUPON_DIA_DESDE <= momento.day <= config.CUPON_DIA_HASTA
    ):
        return (
            f"VETO CORTE CUPÓN: {simbolo} paga renta/amortización en el mes "
            f"{momento.month} y hoy es {momento.day:02d}/{momento.month:02d}, "
            f"dentro de la ventana de corte (días {config.CUPON_DIA_DESDE} "
            f"a {config.CUPON_DIA_HASTA})"
        )
    return None


def _mejores_puntas(cotizacion: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """
    Mejor punta compradora y vendedora de una cotización de IOL, o `None`.

    Replica el criterio de `IOLClient.get_puntas` sobre el payload que ya
    tenemos, sin volver a pedirlo. Devuelve `None` cuando el libro viene vacío
    (lo habitual fuera del horario de rueda) o cuando alguna punta es cero.
    """
    puntas = cotizacion.get("puntas") or []
    if not isinstance(puntas, (list, tuple)) or not puntas:
        return None

    mejor = puntas[0]
    if not isinstance(mejor, dict):
        return None

    bid = _a_float(mejor.get("precioCompra"))
    ask = _a_float(mejor.get("precioVenta"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None

    return {"bid": bid, "ask": ask}


def chequear_spread(
    cotizacion: Dict[str, Any], ultimo_precio: float
) -> Tuple[bool, Dict[str, Any]]:
    """
    Filtro de spread bid/ask contra `config.SPREAD_BID_ASK_MAX`, tolerante a la falta de dato.

    **No bloquea cuando IOL no devuelve puntas.** Fuera del horario de rueda el
    libro viene vacío (verificado contra la API real), y en ese caso el escaneo
    informa el hueco en vez de inventar un spread o vetar el universo entero —
    mismo criterio que `rsi_signal.chequear_liquidez`. Con puntas reales, el veto
    lo decide `fixed_income_filters.check_spread_bid_ask`, que es la única fuente
    de verdad del umbral.

    Args:
        cotizacion: payload crudo de `IOLClient.get_cotizacion`.
        ultimo_precio: último precio operado, denominador del spread.

    Returns:
        `(pasa, detalle)`. `detalle` trae siempre `spread`, `spread_pct` y
        `disponible`; `nota` cuando pasa y `motivo` cuando veta.
    """
    puntas = _mejores_puntas(cotizacion)
    if puntas is None:
        return True, {
            "spread": None,
            "spread_pct": None,
            "disponible": False,
            "bid": None,
            "ask": None,
            "nota": (
                "Spread no verificado: IOL no devolvió puntas para este bono (el "
                "libro de órdenes viene vacío fuera del horario de rueda). Chequeo "
                "no bloqueante."
            ),
        }

    pasa, detalle = fixed_income_filters.check_spread_bid_ask(
        puntas["bid"], puntas["ask"], ultimo_precio
    )

    salida: Dict[str, Any] = {
        "spread": detalle.get("spread"),
        "spread_pct": detalle.get("spread_pct"),
        "disponible": True,
        "bid": puntas["bid"],
        "ask": puntas["ask"],
    }
    if not pasa:
        salida["motivo"] = detalle.get("motivo", "VETO SPREAD: sin motivo informado")
        return False, salida

    salida["nota"] = detalle.get("detalle", "")
    return True, salida


def _historico(simbolo: str):
    """
    OHLCV del bono desde Yahoo, o `None` si no hay.

    Los bonos argentinos casi no tienen serie en Yahoo Finance: la falta de datos
    es el caso habitual, no el de borde. `evaluate_bond_filters` ya sabe degradar
    con `datos_limitados=True`, así que acá cualquier error se traga y devuelve
    `None`. Nunca corta el escaneo.
    """
    try:
        return market_data.get_history(_ticker_yf(simbolo), period=PERIODO_HISTORICO)
    except Exception:  # noqa: BLE001 — Yahoo sin datos, rate limit, red caída
        return None


def _contexto_smart_money(simbolo: str) -> Dict[str, Any]:
    """
    RVOL del bono como contexto informativo. **Nunca veta** (Tarea 5.2).

    Usa el umbral de renta fija (`config.RVOL_ACUMULACION_BONOS`) y omite la
    consulta a la SEC, que no aplica a deuda argentina.
    """
    try:
        return smart_money.contexto_smart_money(_ticker_yf(simbolo), es_bono=True)
    except Exception as exc:  # noqa: BLE001 — el contexto nunca puede romper el escaneo
        return {
            "rvol": None,
            "es_acumulacion": False,
            "insiders_detectados": False,
            "insiders_detalle": f"Contexto no disponible: {exc}",
        }


def _descartado(simbolo: str, etapa: str, motivo: str) -> Dict[str, Any]:
    return {"simbolo": simbolo, "etapa": etapa, "motivo": motivo}


def _respuesta(
    generado: str,
    universo: List[str],
    iol: Dict[str, Any],
    veto_global: Optional[str],
    candidatos: List[Dict[str, Any]],
    descartados: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "generado": generado,
        "universo": universo,
        "nota_precios": NOTA_PRECIO_REAL,
        "veto_global": veto_global,
        "iol": iol,
        "candidatos": candidatos,
        "descartados": descartados,
    }


def _preparar_cliente(cliente: Optional[Any]) -> Tuple[Optional[Any], Dict[str, Any]]:
    """
    Devuelve `(cliente_listo, estado_iol)`.

    Autentica una sola vez por escaneo, antes del bucle: si las credenciales no
    están o el login falla, es mejor un `veto_global` con el motivo que nueve
    bonos descartados con el mismo error repetido. `cliente_listo` es `None`
    cuando no se pudo dejar el cliente en condiciones de operar.
    """
    try:
        cli = cliente if cliente is not None else broker_iol.get_client()
    except Exception as exc:  # noqa: BLE001
        return None, {
            "configurado": False,
            "disponible": False,
            "motivo": f"VETO IOL: no se pudo construir el cliente de InvertirOnline ({exc})",
        }

    if not getattr(cli, "esta_configurado", False):
        return None, {
            "configurado": False,
            "disponible": False,
            "motivo": (
                "VETO IOL: faltan credenciales de InvertirOnline. Cargá "
                "IOL_USERNAME e IOL_PASSWORD en backend/.env (ver .env.example)."
            ),
        }

    try:
        cli.get_headers()
    except broker_iol.IOLError as exc:
        return None, {
            "configurado": True,
            "disponible": False,
            "motivo": f"VETO IOL: no se pudo autenticar contra InvertirOnline ({exc})",
        }
    except Exception as exc:  # noqa: BLE001 — red de seguridad, no debería pasar
        return None, {
            "configurado": True,
            "disponible": False,
            "motivo": f"VETO IOL: error inesperado autenticando contra InvertirOnline ({exc})",
        }

    return cli, {
        "configurado": True,
        "disponible": True,
        "motivo": "Sesión de InvertirOnline activa",
    }


# ---------- Escaneo ----------


def escanear_senales_bonos(
    bonos: Optional[List[str]] = None,
    cliente: Optional[Any] = None,
    ahora: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Recorre el universo de bonos y devuelve candidatos y descartados.

    Args:
        bonos: universo a escanear. Por defecto `config.UNIVERSO_BONOS`.
        cliente: `IOLClient` a usar. Por defecto el singleton de proceso
            (`broker_iol.get_client()`). Se inyecta en los tests.
        ahora: momento para el calendario de corte de cupón. Por defecto, el
            actual. Solo se leen `.month` y `.day`, así que sirve un `datetime`
            o un `pd.Timestamp`.

    Returns:
        dict con esta forma exacta:

        ```python
        {
          "generado": "2026-09-07T12:34:56",   # ISO-8601, segundos
          "universo": ["AL30", ...],
          "nota_precios": str,                  # NOTA_PRECIO_REAL
          "veto_global": None | str,            # IOL sin credenciales o login caído
          "iol": {"configurado": bool, "disponible": bool, "motivo": str},
          "candidatos": [ {...}, ... ],
          "descartados": [ {"simbolo": str, "etapa": str, "motivo": str}, ... ],
        }
        ```

        Cada candidato:

        ```python
        {
          "simbolo": "AL30",
          "tipo": "SOBERANO" | "PROVINCIAL" | "DESCONOCIDO",
          "precio_entrada": float,     # ultimoPrecio real de IOL
          "stop_loss": float,
          "take_profit": float,
          "pct_riesgo": float,         # puntos porcentuales (3.0 = 3,0%)
          "ratio_rb": float,
          "moneda": str | None,        # "peso_Argentino" / "dolar_Estadounidense"
          "fecha_hora": str | None,    # timestamp de la cotización de IOL
          "lote": float | None,
          "lamina_minima": float | None,
          "datos_limitados": bool,     # True si no hubo serie para EMA20 / ATR
          "ema20": float | None,
          "atr": float | None,
          "detalle": str,
          "spread": float | None,      # fracción (0.004 = 0,4%)
          "spread_pct": float | None,
          "spread_disponible": bool,   # False = no había puntas, no se pudo medir
          "spread_nota": str,
          "bid": float | None,
          "ask": float | None,
          "sentimiento_score": float | None,
          "sentimiento_motivo": str,
          "rvol": float | None,
          "es_acumulacion": bool,
        }
        ```

    Nunca levanta excepción: los problemas de IOL salen en `veto_global` y los de
    cada bono en `descartados`.
    """
    universo = list(bonos) if bonos is not None else list(config.UNIVERSO_BONOS)
    generado = datetime.now().isoformat(timespec="seconds")
    momento = ahora if ahora is not None else _ahora()

    # --- Global: sesión de IOL. Sin cotización real no hay señal de bonos. ---
    cli, estado_iol = _preparar_cliente(cliente)
    if cli is None:
        return _respuesta(
            generado, universo, estado_iol, estado_iol["motivo"], [], []
        )

    candidatos: List[Dict[str, Any]] = []
    descartados: List[Dict[str, Any]] = []

    for simbolo_crudo in universo:
        simbolo = (simbolo_crudo or "").strip().upper()
        if not simbolo:
            descartados.append(
                _descartado(
                    str(simbolo_crudo),
                    ETAPA_ERROR,
                    "VETO SÍMBOLO: entrada vacía en el universo de bonos",
                )
            )
            continue

        try:
            # --- 1. Ventana de corte de cupón (calendario, sin red) ---
            motivo_cupon = _veto_corte_cupon(simbolo, momento)
            if motivo_cupon:
                descartados.append(_descartado(simbolo, ETAPA_CUPON, motivo_cupon))
                continue

            # --- 2. Noticias de deuda soberana/provincial (Tarea 9.3) ---
            sentimiento = risk_filters.estado_sentimiento_bonos(simbolo)
            if sentimiento.get("veto"):
                descartados.append(
                    _descartado(
                        simbolo,
                        ETAPA_NOTICIAS,
                        sentimiento.get("motivo", "VETO NOTICIAS: sin motivo informado"),
                    )
                )
                continue

            # --- 3. Cotización real en Contado Inmediato (Tarea 8.1) ---
            try:
                cotizacion = cli.get_cotizacion(simbolo)
            except broker_iol.IOLError as exc:
                descartados.append(
                    _descartado(
                        simbolo,
                        ETAPA_COTIZACION,
                        f"VETO SIN COTIZACIÓN: IOL no devolvió precio de {simbolo} ({exc})",
                    )
                )
                continue

            if not isinstance(cotizacion, dict):
                descartados.append(
                    _descartado(
                        simbolo,
                        ETAPA_COTIZACION,
                        f"VETO SIN COTIZACIÓN: IOL devolvió una respuesta inesperada "
                        f"para {simbolo} ({type(cotizacion).__name__})",
                    )
                )
                continue

            precio = _a_float(cotizacion.get("ultimoPrecio"))
            if precio is None or precio <= 0:
                descartados.append(
                    _descartado(
                        simbolo,
                        ETAPA_COTIZACION,
                        f"VETO SIN COTIZACIÓN: {simbolo} sin último precio operado "
                        f"(se recibió {cotizacion.get('ultimoPrecio')!r}). Suele pasar "
                        "fuera del horario de rueda o si el bono no operó todavía.",
                    )
                )
                continue

            # --- 4. Spread bid/ask (no bloqueante si no hay puntas) ---
            spread_ok, spread_detalle = chequear_spread(cotizacion, precio)
            if not spread_ok:
                descartados.append(
                    _descartado(
                        simbolo,
                        ETAPA_SPREAD,
                        spread_detalle.get("motivo", "VETO SPREAD: sin motivo informado"),
                    )
                )
                continue

            # --- 5. Filtros institucionales de renta fija (Tarea 9.2) ---
            filtros_ok, detalle = fixed_income_filters.evaluate_bond_filters(
                simbolo, precio, _historico(simbolo), ahora=momento
            )
            if not filtros_ok:
                descartados.append(
                    _descartado(
                        simbolo,
                        ETAPA_FILTROS,
                        detalle.get("motivo", "VETO FILTROS: sin motivo informado"),
                    )
                )
                continue

            # --- 6. Contexto de smart money. Informativo, nunca veta. ---
            contexto = _contexto_smart_money(simbolo)

            score = _a_float(sentimiento.get("score"))
            candidatos.append(
                {
                    "simbolo": detalle.get("simbolo", simbolo),
                    "tipo": _tipo_de_bono(simbolo),
                    "precio_entrada": detalle.get("precio_entrada"),
                    "stop_loss": detalle.get("stop_loss"),
                    "take_profit": detalle.get("take_profit"),
                    "pct_riesgo": detalle.get("pct_riesgo"),
                    "ratio_rb": detalle.get("ratio_rb"),
                    "moneda": cotizacion.get("moneda"),
                    "fecha_hora": cotizacion.get("fechaHora"),
                    "lote": _a_float(cotizacion.get("lote")),
                    "lamina_minima": _a_float(cotizacion.get("laminaMinima")),
                    "datos_limitados": detalle.get("datos_limitados"),
                    "ema20": detalle.get("ema20"),
                    "atr": detalle.get("atr"),
                    "detalle": detalle.get("detalle"),
                    "spread": spread_detalle.get("spread"),
                    "spread_pct": spread_detalle.get("spread_pct"),
                    "spread_disponible": spread_detalle.get("disponible", False),
                    "spread_nota": spread_detalle.get("nota", ""),
                    "bid": spread_detalle.get("bid"),
                    "ask": spread_detalle.get("ask"),
                    "sentimiento_score": round(score, 4) if score is not None else None,
                    "sentimiento_motivo": sentimiento.get("motivo", ""),
                    "rvol": contexto.get("rvol"),
                    "es_acumulacion": contexto.get("es_acumulacion", False),
                }
            )
        except Exception as exc:  # noqa: BLE001 — un bono roto no tumba el escaneo
            descartados.append(
                _descartado(
                    simbolo,
                    ETAPA_ERROR,
                    f"Error inesperado evaluando {simbolo}: {exc}",
                )
            )

    return _respuesta(generado, universo, estado_iol, None, candidatos, descartados)
