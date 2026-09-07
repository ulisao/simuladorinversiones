"""
Ingesta de filings 13F desde SEC EDGAR (Tarea 5.3).

Baja el último 13F-HR de cada fondo de `config.FONDOS_13F`, lo compara contra el
filing anterior del mismo fondo y devuelve qué se movió: qué posiciones son
nuevas, cuáles aumentaron, cuáles se redujeron y cuáles se cerraron del todo.
Es el insumo crudo del tracker de consenso (Tarea 5.4).

Este módulo **no calcula ninguna señal**: solo entrega datos.

## De dónde sale cada cosa

```mermaid
flowchart LR
    A["data.sec.gov/submissions/CIK<cik>.json"] -->|últimos dos 13F-HR| B[accession numbers]
    B --> C["sec.gov/Archives/.../index.json"]
    C -->|el .xml que no es primary_doc| D[information table]
    D --> E["agregar por CUSIP"]
    E --> F["mapear CUSIP → ticker"]
    F --> G["comparar trimestre vs anterior"]
    G --> H[movimientos_13f]
```

## Detalles que no son obvios

* **Una misma CUSIP aparece varias veces en un filing**, una por manager con
  discreción sobre esa tenencia. Hay que **sumar** value y shares, no quedarse
  con la primera fila: sin agregar, Berkshire parece tener tres posiciones
  chicas de Ally en vez de una grande.
* **El precio promedio es un proxy.** `value / shares` es el valor de mercado al
  **cierre del trimestre**, no el precio al que el fondo compró. Es lo mejor que
  publica un 13F y es lo que usa el filtro anti-persecución de la Tarea 5.4.
* **Los 13F salen con hasta 45 días de rezago legal** y son trimestrales. Esta
  fuente es lenta por naturaleza: no esperar señales frecuentes.
* **`value` no siempre viene en la misma unidad.** Desde 2023-01-03 la SEC pide
  dólares, pero en la práctica hay fondos que lo siguen presentando en **miles**
  (verificado: en el trimestre 2026-06-30, Baupost declara una cartera de
  "$5.415.853" y un precio implícito de $0,24 para AMZN). Como el peso en cartera
  es un cociente dentro del mismo filing, ese error no se nota ahí — pero el
  precio promedio queda 1000× abajo, y es justo lo que alimenta el filtro
  anti-persecución de la Tarea 5.4. Por eso cada filing se normaliza solo, ver
  `factor_de_escala`.

Como todo módulo que habla con internet, ninguna función de acá propaga una
excepción: los errores se acumulan en la clave `errores` del resultado.
"""
import json
import logging
import os
import statistics
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import requests

from . import config

logger = logging.getLogger(__name__)

URL_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
URL_ARCHIVO = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}"

NS = "{http://www.sec.gov/edgar/document/thirteenf/informationtable}"

TIMEOUT_SEG = 30

# SEC pide no superar 10 pedidos por segundo. Con 5 fondos × 3 pedidos estamos
# lejos del límite, pero la pausa evita que un cambio futuro nos haga bloquear.
PAUSA_ENTRE_PEDIDOS_SEG = 0.15

FORMULARIO = "13F-HR"

# Tipos de movimiento entre un trimestre y el anterior.
NUEVA = "NUEVA"
AUMENTO = "AUMENTO"
REDUCCION = "REDUCCION"
CIERRE = "CIERRE"
SIN_CAMBIO = "SIN_CAMBIO"

MOVIMIENTOS_DE_COMPRA = (NUEVA, AUMENTO)
MOVIMIENTOS_DE_VENTA = (REDUCCION, CIERRE)


def _headers() -> Dict[str, str]:
    """SEC rechaza los pedidos sin un User-Agent que identifique a quien consulta."""
    return {"User-Agent": config.SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def _get(url: str) -> requests.Response:
    time.sleep(PAUSA_ENTRE_PEDIDOS_SEG)
    respuesta = requests.get(url, headers=_headers(), timeout=TIMEOUT_SEG)
    respuesta.raise_for_status()
    return respuesta


# ---------- Descarga ----------


def ultimos_filings(cik: str, cantidad: int = 2) -> List[Dict[str, str]]:
    """Los `cantidad` 13F-HR más recientes de un fondo, del más nuevo al más viejo.

    Devuelve dicts con `accession` (sin guiones, como los quiere la URL de
    Archives), `reporte` (fin del trimestre) y `presentado`.
    """
    datos = _get(URL_SUBMISSIONS.format(cik=str(cik).zfill(10))).json()
    recientes = datos.get("filings", {}).get("recent", {})
    formularios = recientes.get("form", [])

    filings = []
    for i, formulario in enumerate(formularios):
        if formulario != FORMULARIO:
            continue
        filings.append(
            {
                "accession": recientes["accessionNumber"][i].replace("-", ""),
                "reporte": recientes["reportDate"][i],
                "presentado": recientes["filingDate"][i],
            }
        )
        if len(filings) >= cantidad:
            break
    return filings


def _url_information_table(cik: str, accession: str) -> Optional[str]:
    """Encuentra el XML de la information table dentro del filing.

    El nombre del archivo cambia filing a filing (`56757.xml`, `form13fInfoTable.xml`,
    ...), así que se lista el directorio y se descarta `primary_doc.xml`, que es
    la carátula.
    """
    base = URL_ARCHIVO.format(cik=str(int(cik)), acc=accession)
    items = _get(f"{base}/index.json").json()["directory"]["item"]

    candidatos = [
        it["name"]
        for it in items
        if it["name"].lower().endswith(".xml") and "primary_doc" not in it["name"].lower()
    ]
    if not candidatos:
        return None
    return f"{base}/{candidatos[0]}"


def parsear_information_table(xml: str) -> Dict[str, Dict[str, Any]]:
    """Agrega las tenencias de un filing por CUSIP.

    Una misma CUSIP aparece una vez por manager con discreción: se suman `value`
    y `shares` para tener la posición real del fondo.
    """
    raiz = ET.fromstring(xml)
    posiciones: Dict[str, Dict[str, Any]] = {}

    for fila in raiz.findall(f"{NS}infoTable"):
        cusip = (fila.findtext(f"{NS}cusip") or "").strip().upper()
        if not cusip:
            continue

        try:
            valor = float(fila.findtext(f"{NS}value") or 0)
            acciones = float(fila.findtext(f"{NS}shrsOrPrnAmt/{NS}sshPrnamt") or 0)
        except (TypeError, ValueError):
            continue

        actual = posiciones.setdefault(
            cusip,
            {"cusip": cusip, "nombre": (fila.findtext(f"{NS}nameOfIssuer") or "").strip(),
             "valor": 0.0, "acciones": 0.0,
             # SH = acciones, PRN = valor nominal (deuda). Solo las SH sirven para
             # deducir un precio por acción.
             "tipo": (fila.findtext(f"{NS}shrsOrPrnAmt/{NS}sshPrnamtType") or "SH").strip().upper()},
        )
        actual["valor"] += valor
        actual["acciones"] += acciones

    return _normalizar_escala(posiciones)


# Precio implícito por debajo del cual se asume que el filing declara `value` en
# miles. Una acción listada en EE.UU. no cotiza a menos de un dólar salvo casos
# marginales, y acá se mira la MEDIANA de toda la cartera, no una posición.
PRECIO_MINIMO_PLAUSIBLE = 1.0
FACTOR_MILES = 1000.0


def factor_de_escala(posiciones: Dict[str, Dict[str, Any]]) -> float:
    """1.0 si el filing declara dólares, 1000.0 si declara miles.

    Se decide con la mediana del precio implícito (`valor / acciones`) de las
    posiciones en acciones. La mediana, y no una posición suelta, para que una
    tenencia rara no arrastre la decisión de todo el filing.
    """
    precios = [
        p["valor"] / p["acciones"]
        for p in posiciones.values()
        if p["acciones"] > 0 and p.get("tipo", "SH") == "SH"
    ]
    if not precios:
        return 1.0
    return FACTOR_MILES if statistics.median(precios) < PRECIO_MINIMO_PLAUSIBLE else 1.0


def _normalizar_escala(posiciones: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Deja todos los `valor` en dólares, venga el filing como venga."""
    factor = factor_de_escala(posiciones)
    if factor != 1.0:
        logger.info("Filing declarado en miles: se multiplican los valores por %g", factor)
        for p in posiciones.values():
            p["valor"] *= factor
    return posiciones


# ---------- Cache en disco ----------


def _ruta_cache(cik: str, reporte: str) -> str:
    return os.path.join(config.DIR_DATOS_13F, str(cik), f"{reporte}.json")


def _leer_cache(cik: str, reporte: str) -> Optional[Dict[str, Dict[str, Any]]]:
    ruta = _ruta_cache(cik, reporte)
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001 — un cache roto se rebaja a "no hay cache"
        logger.warning("Cache 13F ilegible (%s): %s", ruta, exc)
        return None


def _guardar_cache(cik: str, reporte: str, posiciones: Dict[str, Dict[str, Any]]) -> None:
    ruta = _ruta_cache(cik, reporte)
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(posiciones, f, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001 — sin cache el sistema sigue andando
        logger.warning("No se pudo guardar el cache 13F (%s): %s", ruta, exc)


def cartera_de(cik: str, filing: Dict[str, str], usar_cache: bool = True) -> Dict[str, Dict[str, Any]]:
    """Tenencias de un filing, desde el cache o bajándolo de EDGAR."""
    if usar_cache:
        guardada = _leer_cache(cik, filing["reporte"])
        if guardada is not None:
            return guardada

    url = _url_information_table(cik, filing["accession"])
    if url is None:
        raise ValueError(f"El filing {filing['accession']} no trae information table.")

    posiciones = parsear_information_table(_get(url).text)
    _guardar_cache(cik, filing["reporte"], posiciones)
    return posiciones


# ---------- Comparación entre trimestres ----------


def comparar(
    actual: Dict[str, Dict[str, Any]], previa: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Movimientos de un trimestre contra el anterior, solo del universo mapeado.

    Las CUSIP que no están en `config.CUSIP_A_TICKER` se ignoran: el sistema no
    puede operar un papel que no tiene CEDEAR habilitado, y devolver CUSIPs
    sueltos sería justamente lo que la Tarea 5.3 pide evitar.
    """
    total_actual = sum(p["valor"] for p in actual.values()) or 0.0
    movimientos: List[Dict[str, Any]] = []

    for cusip in set(actual) | set(previa):
        ticker = config.CUSIP_A_TICKER.get(cusip)
        if ticker is None:
            continue

        hoy = actual.get(cusip)
        antes = previa.get(cusip)
        acciones_hoy = hoy["acciones"] if hoy else 0.0
        acciones_antes = antes["acciones"] if antes else 0.0

        if acciones_hoy > 0 and acciones_antes == 0:
            tipo = NUEVA
        elif acciones_hoy == 0 and acciones_antes > 0:
            tipo = CIERRE
        elif acciones_hoy > acciones_antes:
            tipo = AUMENTO
        elif acciones_hoy < acciones_antes:
            tipo = REDUCCION
        else:
            tipo = SIN_CAMBIO

        valor = hoy["valor"] if hoy else 0.0
        movimientos.append(
            {
                "ticker": ticker,
                "cusip": cusip,
                "nombre": (hoy or antes)["nombre"],
                "tipo": tipo,
                "valor": round(valor, 2),
                "peso_cartera": round(valor / total_actual, 6) if total_actual else 0.0,
                "acciones": acciones_hoy,
                "acciones_previas": acciones_antes,
                # Proxy del precio de entrada del fondo: valor de mercado al
                # cierre del trimestre. Es lo mejor que publica un 13F.
                "precio_promedio": round(valor / acciones_hoy, 4) if acciones_hoy else None,
            }
        )

    return sorted(movimientos, key=lambda m: -m["peso_cartera"])


# ---------- Punto de entrada ----------


def descargar_movimientos(
    ciks: Optional[Dict[str, str]] = None, usar_cache: bool = True
) -> Dict[str, Any]:
    """Movimientos 13F de todos los fondos seguidos. Nunca lanza.

    Returns:
        ```
        {
          "fondos": [ {"cik", "nombre", "reporte", "reporte_previo", "posiciones"} ],
          "movimientos": [ {"fondo", "cik", "ticker", "tipo", "peso_cartera", ...} ],
          "errores": [ "..." ],
        }
        ```
    """
    fondos = ciks if ciks is not None else config.FONDOS_13F
    resumen: Dict[str, Any] = {"fondos": [], "movimientos": [], "errores": []}

    for cik, nombre in fondos.items():
        try:
            filings = ultimos_filings(cik)
        except Exception as exc:  # noqa: BLE001
            resumen["errores"].append(f"{nombre} ({cik}): no se pudo listar filings — {exc}")
            continue

        if len(filings) < 2:
            resumen["errores"].append(
                f"{nombre} ({cik}): hacen falta dos 13F-HR para comparar, hay {len(filings)}."
            )
            continue

        try:
            actual = cartera_de(cik, filings[0], usar_cache)
            previa = cartera_de(cik, filings[1], usar_cache)
        except Exception as exc:  # noqa: BLE001
            resumen["errores"].append(f"{nombre} ({cik}): no se pudo bajar el filing — {exc}")
            continue

        movimientos = comparar(actual, previa)
        for m in movimientos:
            m["fondo"] = nombre
            m["cik"] = cik
        resumen["movimientos"].extend(movimientos)

        resumen["fondos"].append(
            {
                "cik": cik,
                "nombre": nombre,
                "reporte": filings[0]["reporte"],
                "reporte_previo": filings[1]["reporte"],
                "presentado": filings[0]["presentado"],
                "posiciones": len(actual),
                "posiciones_mapeadas": len(movimientos),
            }
        )
        logger.info(
            "%s: %d posiciones (%d del universo) — %s vs %s",
            nombre, len(actual), len(movimientos),
            filings[0]["reporte"], filings[1]["reporte"],
        )

    return resumen
