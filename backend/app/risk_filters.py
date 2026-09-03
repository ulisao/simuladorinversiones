"""
Circuit breaker de VIX y filtros de sentimiento de noticias (FinBERT local).

Cubre tres filtros de riesgo del plan (`tareasdesarrollo.md`):

* Tarea 4.1 — `estado_vix()` / `check_vix_circuit_breaker()`: veta operar cuando
  el VIX está en nivel de pánico o pegó un salto intradiario.
* Tarea 4.2 — `get_finbert_sentiment(ticker)`: sentimiento de las noticias de un
  ticker (RSS de Yahoo Finance) con FinBERT corriendo 100% local.
* Tarea 9.3 — `check_bonds_news_sentiment(simbolo_bono)`: lo mismo para deuda
  soberana/provincial argentina, con feed de Google News en español y palabras
  críticas propias de deuda.

Referencias de spec:
  - `docs/specs-txt/Manual_Maestro_Bot_Inversion_IA_Completo.txt`, sección 4
    (`macro_news.py`).
  - `docs/specs-txt/Manual_Maestro_Bot_Bonos_Soberanos_Provinciales.txt`,
    sección 4 (`macro_bonds.py`).

Diferencias respecto del código de los manuales (deliberadas):

1. **Umbrales desde `config.py`.** Los manuales hardcodean 25.0, +10%, -0.35 y
   -0.30. Acá salen de `config.VIX_NIVEL_PANICO`, `config.VIX_SUBA_DIARIA_MAX`,
   `config.SENTIMIENTO_MIN_ACCIONES` y `config.SENTIMIENTO_MIN_BONOS`.
2. **FinBERT se carga perezosamente y se cachea.** Los manuales cargan el modelo
   a nivel de módulo: eso haría que `import app.risk_filters` (que `main.py` hace
   al arrancar la API) baje ~400 MB y coma ~500 MB de RAM antes de servir el
   primer request. Acá la carga ocurre en la primera llamada que realmente
   necesita puntuar un titular, cacheada con `functools.lru_cache(maxsize=1)`.
   `torch` y `transformers` se importan *dentro* de esa función.
3. **Degradación segura sin `transformers`/`torch`.** Si las librerías pesadas no
   están instaladas (o el modelo no se puede bajar), el módulo igual se importa y
   las funciones de noticias siguen aplicando el veto por palabras críticas —que
   no necesita modelo—; el score se informa como 0.0 y el motivo dice que FinBERT
   no está disponible. Nunca se levanta una excepción hacia el endpoint.
4. **Acentos.** Los titulares en español vienen acentuados ("reestructuración",
   "cesación de pagos") y la lista de palabras críticas del manual está sin
   acentos. Antes de comparar se normaliza el titular (minúsculas + sin tildes),
   si no la mitad de las palabras críticas nunca matchearían.

Criterio ante error (regla de CLAUDE.md: estos módulos nunca rompen el proceso):

* **VIX -> fail-safe, veta.** Si no se puede leer `^VIX` se devuelve
  `(False, "Error leyendo VIX: ...")`. Es el criterio del manual: sin saber si el
  mercado está en pánico, no se abre posición.
* **Noticias -> fail-open, no veta.** Si el RSS no responde, viene vacío o el
  modelo no está disponible, se devuelve `(True, 0.0, "...")`. Vetar todo el
  universo porque Yahoo devolvió un 429 dejaría al bot ciego y sin operar por un
  problema de infraestructura ajeno al riesgo del activo; además el veto real de
  este filtro (palabras críticas) igual se sigue evaluando cuando hay titulares.
"""
from __future__ import annotations

import functools
import logging
import re
import unicodedata
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

import feedparser
import yfinance as yf

from . import config

logger = logging.getLogger(__name__)


# ---------- Constantes de los manuales (los umbrales van en config.py) ----------

TICKER_VIX = "^VIX"

# Palabras "cisne negro" para acciones/CEDEARs (manual de acciones, sección 4).
PALABRAS_CRITICAS_ACCIONES = [
    "war",
    "sanction",
    "bank run",
    "fraud",
    "default",
    "bankruptcy",
    "sec probe",
]

# Palabras de riesgo crítico soberano y provincial (manual de bonos, sección 4).
PALABRAS_CRITICAS_BONOS = [
    "default",
    "reestructuracion forzosa",
    "reperfilamiento",
    "embargo",
    "fmi suspende",
    "fallo griesa",
    "embargo reservas",
    "crisis de deuda",
    "cesacion de pagos",
    "litigio nueva york",
]

# Cuántos titulares evalúa cada filtro (los manuales usan 5 y 6).
MAX_TITULARES_ACCIONES = 5
MAX_TITULARES_BONOS = 6

MODELO_FINBERT = "ProsusAI/finbert"

# Yahoo y Google devuelven 403 a clientes sin User-Agent de navegador.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT_FEED_SEGUNDOS = 15


def url_feed_acciones(ticker: str) -> str:
    """URL del RSS de titulares de Yahoo Finance para un ticker."""
    return f"https://finance.yahoo.com/rss/headline?s={ticker}"


def url_feed_bonos(simbolo_bono: str) -> str:
    """URL del RSS de Google News (español AR) para un bono argentino."""
    return (
        f"https://news.google.com/rss/search?q={simbolo_bono}+deuda+argentina+bonos"
        "&hl=es-419&gl=AR&ceid=AR:es-419"
    )


# ---------- Circuit breaker de VIX (Tarea 4.1) ----------


def estado_vix() -> Dict[str, Any]:
    """
    Estado crudo del VIX, listo para mostrar en el dashboard.

    Devuelve un dict con:
        vix_actual (float | None): último cierre de `^VIX`.
        vix_previo (float | None): cierre de la rueda anterior.
        cambio_pct (float | None): variación diaria en tanto por uno (0.10 = +10%).
        veto (bool): True si hay que bloquear la apertura de posiciones.
        motivo (str): mensaje en español explicando el estado.

    Nunca lanza excepción. Ante un **error** de red o de parseo devuelve
    `veto=True` (fail-safe, criterio del manual).

    Excepción a esa regla: si Yahoo responde bien pero **sin ruedas**, se devuelve
    `veto=False` con motivo "Datos VIX insuficientes". Es literal del manual
    (`if len(vix) < 2: return True, "Datos VIX insuficientes"`) y se respeta a
    propósito, pero conviene tenerlo presente: en un rate limit que devuelva un
    DataFrame vacío en vez de un error, el escaneo sigue sin saber nada del
    pánico de mercado. Si se prefiere cerrar ese hueco, hay que cambiar acá el
    `veto` a True y actualizar `docs/parametros-riesgo.md`.
    """
    try:
        historial = yf.Ticker(TICKER_VIX).history(period="2d")

        if historial is None or len(historial) == 0:
            return {
                "vix_actual": None,
                "vix_previo": None,
                "cambio_pct": None,
                "veto": False,
                "motivo": "Datos VIX insuficientes",
            }

        vix_actual = float(historial["Close"].iloc[-1])

        # Con una sola rueda no se puede calcular la variación diaria. El manual
        # deja pasar la operación en ese caso (no es señal de pánico, es falta de
        # datos), pero igual chequeamos el nivel absoluto, que sí se conoce.
        if len(historial) < 2:
            veto_nivel = vix_actual > config.VIX_NIVEL_PANICO
            return {
                "vix_actual": round(vix_actual, 2),
                "vix_previo": None,
                "cambio_pct": None,
                "veto": veto_nivel,
                "motivo": (
                    f"VETO: VIX en nivel de pánico "
                    f"({vix_actual:.2f} > {config.VIX_NIVEL_PANICO:.1f})"
                    if veto_nivel
                    else f"Datos VIX insuficientes (solo 1 rueda, VIX {vix_actual:.2f})"
                ),
            }

        vix_previo = float(historial["Close"].iloc[-2])
        cambio_pct = (vix_actual - vix_previo) / vix_previo if vix_previo else 0.0

        estado: Dict[str, Any] = {
            "vix_actual": round(vix_actual, 2),
            "vix_previo": round(vix_previo, 2),
            "cambio_pct": round(cambio_pct, 4),
            "veto": False,
            "motivo": "",
        }

        if vix_actual > config.VIX_NIVEL_PANICO:
            estado["veto"] = True
            estado["motivo"] = (
                f"VETO: VIX en nivel de pánico "
                f"({vix_actual:.2f} > {config.VIX_NIVEL_PANICO:.1f})"
            )
        elif cambio_pct > config.VIX_SUBA_DIARIA_MAX:
            estado["veto"] = True
            estado["motivo"] = (
                f"VETO: Subida abrupta de volatilidad VIX "
                f"(+{cambio_pct * 100:.1f}% > +{config.VIX_SUBA_DIARIA_MAX * 100:.0f}%)"
            )
        else:
            estado["motivo"] = f"VIX OK ({vix_actual:.2f}, {cambio_pct * 100:+.1f}% diario)"

        return estado

    except Exception as e:  # noqa: BLE001 — cualquier fallo leyendo el VIX es veto
        logger.warning("Error leyendo el VIX: %s", e)
        return {
            "vix_actual": None,
            "vix_previo": None,
            "cambio_pct": None,
            "veto": True,
            "motivo": f"Error leyendo VIX: {e}",
        }


def check_vix_circuit_breaker() -> Tuple[bool, str]:
    """
    Circuit breaker de mercado: ¿se puede abrir posición hoy?

    Veta si el VIX supera `config.VIX_NIVEL_PANICO` o si subió más de
    `config.VIX_SUBA_DIARIA_MAX` respecto de la rueda anterior.

    Returns:
        (permitido, mensaje) — `permitido=False` significa no operar. Ante error
        leyendo el VIX devuelve `(False, "Error leyendo VIX: ...")` (fail-safe).
    """
    estado = estado_vix()
    return (not estado["veto"]), estado["motivo"]


# ---------- Carga perezosa y cacheada de FinBERT ----------


@functools.lru_cache(maxsize=1)
def _cargar_finbert() -> Optional[Dict[str, Any]]:
    """
    Carga FinBERT una sola vez por proceso y devuelve todo lo necesario para inferir.

    `lru_cache(maxsize=1)` hace de singleton: la primera llamada baja/carga el
    modelo (~400 MB la primera vez, después queda en la cache de HuggingFace) y
    las siguientes reutilizan el objeto ya cargado.

    `torch` y `transformers` se importan acá adentro a propósito: así importar
    este módulo (cosa que `main.py` hace al arrancar) no dispara la carga, y el
    módulo sigue siendo importable aunque esas librerías no estén instaladas.

    Returns:
        dict con `tokenizer`, `modelo`, `torch`, `idx_pos`, `idx_neg`, o `None`
        si las librerías no están disponibles o el modelo no se pudo cargar.
    """
    try:
        import torch  # import local a propósito (ver docstring)
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except Exception as e:  # noqa: BLE001
        logger.warning("FinBERT no disponible (falta transformers/torch): %s", e)
        return None

    try:
        tokenizer = AutoTokenizer.from_pretrained(MODELO_FINBERT)
        modelo = AutoModelForSequenceClassification.from_pretrained(MODELO_FINBERT)
        modelo.eval()
    except Exception as e:  # noqa: BLE001 — sin red / sin cache local / sin RAM
        logger.warning("No se pudo cargar el modelo %s: %s", MODELO_FINBERT, e)
        return None

    # El manual asume el orden [positive, negative, neutral]. En vez de confiar en
    # el índice, se leen las etiquetas del propio modelo: si algún día cambia el
    # orden, el score sigue siendo P(positivo) - P(negativo).
    etiquetas = {int(i): str(nombre).lower() for i, nombre in modelo.config.id2label.items()}
    idx_pos = next((i for i, n in etiquetas.items() if n.startswith("pos")), 0)
    idx_neg = next((i for i, n in etiquetas.items() if n.startswith("neg")), 1)

    logger.info("FinBERT cargado (%s), etiquetas=%s", MODELO_FINBERT, etiquetas)
    return {
        "tokenizer": tokenizer,
        "modelo": modelo,
        "torch": torch,
        "idx_pos": idx_pos,
        "idx_neg": idx_neg,
    }


def finbert_disponible() -> bool:
    """True si FinBERT se puede usar (fuerza la carga perezosa si hace falta)."""
    return _cargar_finbert() is not None


def limpiar_cache_modelo() -> None:
    """Libera el modelo cacheado. Pensado para tests; en producción no hace falta."""
    _cargar_finbert.cache_clear()


def puntuar_titular(titulo: str) -> Optional[float]:
    """
    Score FinBERT de un titular: P(positivo) - P(negativo), en el rango [-1, 1].

    Devuelve `None` si FinBERT no está disponible o si la inferencia falla.
    """
    finbert = _cargar_finbert()
    if finbert is None:
        return None

    torch = finbert["torch"]
    try:
        with torch.no_grad():
            inputs = finbert["tokenizer"](
                titulo, return_tensors="pt", padding=True, truncation=True
            )
            outputs = finbert["modelo"](**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)[0]
        return float(probs[finbert["idx_pos"]].item() - probs[finbert["idx_neg"]].item())
    except Exception as e:  # noqa: BLE001
        logger.warning("Error puntuando titular con FinBERT: %s", e)
        return None


# ---------- Lectura de feeds RSS ----------


def _normalizar(texto: str) -> str:
    """Pasa a minúsculas y saca tildes, para comparar contra las palabras críticas."""
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return sin_tildes.lower()


@functools.lru_cache(maxsize=256)
def _patron_palabra(palabra: str) -> "re.Pattern[str]":
    """
    Compila una palabra crítica como patrón con límites de palabra.

    El manual original compara con `if palabra in titulo`, o sea subcadena. Eso
    genera falsos positivos graves: `"war"` matchea dentro de "hardware" y
    "software", y en una corrida real llegó a vetar SPY y MSFT por titulares
    inofensivos sobre software. Un veto es una decisión de no operar: no puede
    dispararse por una coincidencia de letras en el medio de otra palabra.

    Las frases de varias palabras (`"bank run"`, `"sec probe"`,
    `"reestructuracion forzosa"`) siguen funcionando: se tolera cualquier
    cantidad de espacios entre los términos.

    **Se tolera el plural en cada término**, porque es la forma habitual en los
    titulares reales y la primera versión de este patrón —solo singular exacto—
    dejaba pasar vetos que el manual sí disparaba: "US imposes new
    *sanctions*", "Tesla falls after *SEC probes*", "Regional *bank runs*
    spread", "*Cesaciones de pagos* en provincias". El plural va por término y
    no solo al final justamente por ese último caso, donde la marca de plural
    cae en la primera palabra de la frase.
    """
    def _con_plural(termino: str) -> str:
        # bankruptcy -> bankruptcies ; sanction -> sanctions ; embargo -> embargos
        if termino.endswith("y") and len(termino) > 1:
            return re.escape(termino[:-1]) + "(?:y|ies)"
        return re.escape(termino) + "(?:e?s)?"

    terminos = _normalizar(palabra).split()
    cuerpo = r"\s+".join(_con_plural(t) for t in terminos)
    return re.compile(rf"(?<!\w){cuerpo}(?!\w)")


def _palabra_critica(titulo: str, palabras: Sequence[str]) -> Optional[str]:
    """Devuelve la primera palabra crítica presente en el titular, o None."""
    normalizado = _normalizar(titulo)
    for palabra in palabras:
        if _patron_palabra(palabra).search(normalizado):
            return palabra
    return None


def leer_titulares(url: str, maximo: int) -> List[str]:
    """
    Descarga un feed RSS y devuelve hasta `maximo` titulares.

    Usa `urllib` (stdlib) para poder fijar timeout y User-Agent —`feedparser.parse(url)`
    a secas no permite ninguna de las dos cosas y Yahoo/Google responden 403 sin UA
    de navegador— y le pasa los bytes crudos a feedparser.

    Lanza excepción si el feed no se puede leer; los llamadores la capturan.
    """
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(pedido, timeout=TIMEOUT_FEED_SEGUNDOS) as respuesta:
        crudo = respuesta.read()

    feed = feedparser.parse(crudo)
    titulares: List[str] = []
    for entrada in feed.entries[:maximo]:
        titulo = (getattr(entrada, "title", "") or "").strip()
        if titulo:
            titulares.append(titulo)
    return titulares


def _evaluar_feed(
    identificador: str,
    url: str,
    palabras_criticas: Sequence[str],
    maximo_titulares: int,
    umbral: float,
    etiqueta_ok: str,
) -> Dict[str, Any]:
    """
    Motor común de los filtros 4.2 y 9.3: baja el feed, busca palabras críticas y promedia scores.

    Devuelve el dict de detalle que usan `estado_sentimiento_acciones` y
    `estado_sentimiento_bonos` (ver esas funciones para las claves).
    """
    detalle: Dict[str, Any] = {
        "simbolo": identificador,
        "veto": False,
        "score": 0.0,
        "motivo": "",
        "titulares": [],
        "url_feed": url,
        "modelo_disponible": True,
    }

    # Error de red/parseo leyendo noticias => NO se veta (fail-open). Ver docstring
    # del módulo: un 429 de Yahoo no es información de riesgo sobre el activo, y
    # vetar por eso dejaría al bot sin operar por un problema de infraestructura.
    try:
        titulares = leer_titulares(url, maximo_titulares)
    except Exception as e:  # noqa: BLE001
        logger.warning("Error leyendo el feed de %s (%s): %s", identificador, url, e)
        detalle["motivo"] = f"Sin noticias: error leyendo el feed ({e})"
        return detalle

    if not titulares:
        detalle["motivo"] = "Sin noticias recientes (Neutro)"
        return detalle

    logger.info("Titulares evaluados para %s: %s", identificador, titulares)

    # Paso 1: veto cisne negro. No necesita modelo, así que corre aunque FinBERT
    # no esté disponible.
    for titulo in titulares:
        palabra = _palabra_critica(titulo, palabras_criticas)
        if palabra:
            detalle["veto"] = True
            detalle["score"] = -1.0
            detalle["motivo"] = (
                f"VETO CISNE NEGRO: Palabra crítica '{palabra}' detectada en '{titulo}'"
            )
            detalle["titulares"] = [{"titulo": t, "score": None} for t in titulares]
            return detalle

    # Paso 2: promedio de scores FinBERT.
    scores: List[float] = []
    for titulo in titulares:
        score = puntuar_titular(titulo)
        detalle["titulares"].append(
            {"titulo": titulo, "score": None if score is None else round(score, 4)}
        )
        if score is not None:
            scores.append(score)

    if not scores:
        # Sin modelo (o falló la inferencia): ya se aplicaron las palabras críticas,
        # el resto se informa como neutro y no veta.
        detalle["modelo_disponible"] = False
        detalle["motivo"] = (
            f"Sin scoring: FinBERT no disponible ({len(titulares)} titulares revisados "
            "solo por palabras críticas)"
        )
        return detalle

    promedio = sum(scores) / len(scores)
    detalle["score"] = round(promedio, 4)

    if promedio < umbral:
        detalle["veto"] = True
        detalle["motivo"] = (
            f"VETO SENTIMIENTO: FinBERT Score negativo ({promedio:.2f} < {umbral:.2f})"
        )
    else:
        detalle["motivo"] = f"{etiqueta_ok} ({promedio:+.2f})"

    return detalle


# ---------- Sentimiento de noticias de acciones/CEDEARs (Tarea 4.2) ----------


def estado_sentimiento_acciones(ticker: str) -> Dict[str, Any]:
    """
    Detalle del sentimiento de noticias de un ticker, con los titulares usados.

    Devuelve un dict con:
        simbolo (str), veto (bool), score (float en [-1, 1]), motivo (str),
        titulares (list[dict] con `titulo` y `score`), url_feed (str),
        modelo_disponible (bool).

    Pensado para el dashboard y para el logging; el veto en sí se consulta con
    `get_finbert_sentiment`. Nunca lanza excepción.
    """
    return _evaluar_feed(
        identificador=ticker,
        url=url_feed_acciones(ticker),
        palabras_criticas=PALABRAS_CRITICAS_ACCIONES,
        maximo_titulares=MAX_TITULARES_ACCIONES,
        umbral=config.SENTIMIENTO_MIN_ACCIONES,
        etiqueta_ok="Sentimiento OK",
    )


def get_finbert_sentiment(ticker: str) -> Tuple[bool, float, str]:
    """
    Filtro de noticias de un ticker con FinBERT local (Tarea 4.2).

    Baja el RSS de titulares de Yahoo Finance, veta si alguno de los últimos
    `MAX_TITULARES_ACCIONES` contiene una palabra crítica
    (`PALABRAS_CRITICAS_ACCIONES`) y, si no, promedia el score
    P(positivo) - P(negativo) de esos titulares y veta si queda por debajo de
    `config.SENTIMIENTO_MIN_ACCIONES`.

    Args:
        ticker: símbolo de Yahoo Finance, por ejemplo "AAPL".

    Returns:
        (permitido, score, mensaje). `score` va de -1 a 1 (0.0 si no hubo
        noticias o si FinBERT no está disponible). Sin noticias devuelve
        `(True, 0.0, "Sin noticias recientes (Neutro)")`. Ante error de red no
        veta (fail-open); ver docstring del módulo.
    """
    detalle = estado_sentimiento_acciones(ticker)
    return (not detalle["veto"]), float(detalle["score"]), detalle["motivo"]


# ---------- Sentimiento de noticias de deuda soberana (Tarea 9.3) ----------


def estado_sentimiento_bonos(simbolo_bono: str) -> Dict[str, Any]:
    """
    Detalle del sentimiento de noticias de deuda de un bono, con los titulares usados.

    Mismas claves que `estado_sentimiento_acciones`. Nunca lanza excepción.
    """
    return _evaluar_feed(
        identificador=simbolo_bono,
        url=url_feed_bonos(simbolo_bono),
        palabras_criticas=PALABRAS_CRITICAS_BONOS,
        maximo_titulares=MAX_TITULARES_BONOS,
        umbral=config.SENTIMIENTO_MIN_BONOS,
        etiqueta_ok="Sentimiento Deuda Favorable",
    )


def check_bonds_news_sentiment(simbolo_bono: str) -> Tuple[bool, float, str]:
    """
    Filtro de noticias de deuda soberana/provincial (Tarea 9.3).

    Usa el feed de Google News en español (`url_feed_bonos`), veta si alguno de
    los últimos `MAX_TITULARES_BONOS` titulares contiene una palabra crítica de
    deuda (`PALABRAS_CRITICAS_BONOS`: default, reperfilamiento, fallo griesa,
    cesación de pagos, etc.) y, si no, promedia el score FinBERT y veta si queda
    por debajo de `config.SENTIMIENTO_MIN_BONOS`.

    Reusa el mismo modelo cacheado que `get_finbert_sentiment`: FinBERT se carga
    una sola vez por proceso.

    Args:
        simbolo_bono: símbolo del bono, por ejemplo "AL30" o "GD30".

    Returns:
        (permitido, score, mensaje), con el mismo criterio que
        `get_finbert_sentiment`.
    """
    detalle = estado_sentimiento_bonos(simbolo_bono)
    return (not detalle["veto"]), float(detalle["score"]), detalle["motivo"]
