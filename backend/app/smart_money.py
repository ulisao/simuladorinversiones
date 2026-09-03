"""
Smart money: volumen anómalo (RVOL) y compras de directores (SEC Form 4).

Este módulo aporta **contexto informativo, nunca veta una señal**. Ni un RVOL
bajo ni la ausencia de filings de insiders invalidan una operación: los vetos
salen de `technical_filters` / `fixed_income_filters` / `risk_filters`. Acá solo
se responde "¿hay huellas de dinero institucional detrás de este papel?".

Regla del repo (CLAUDE.md): los módulos que hablan con internet nunca rompen el
proceso. Toda excepción de red, de parseo o de Yahoo se captura y se devuelve un
resultado neutro controlado; nunca se propaga hacia el endpoint.

Umbrales: todos salen de `config.py` (`RVOL_ACUMULACION`,
`RVOL_ACUMULACION_BONOS`, `INSIDERS_MIN_FILINGS`). Nada hardcodeado acá.

Referencias de spec:
- `Manual_Maestro_Bot_Inversion_IA_Completo`, sección 5 (`insider_smartmoney.py`:
  `check_unusual_volume`, `check_sec_form4_cluster`).
- `Manual_Maestro_Bot_Bonos_Soberanos_Provinciales`, sección 5
  (`smart_money_bonds.py`: `check_bond_unusual_volume`).
"""
import xml.etree.ElementTree as ET
from typing import Optional, Tuple

import pandas as pd
import requests

from . import config
from . import market_data


# ---------- Constantes del módulo (no son parámetros de riesgo) ----------

# Ventana que se le pide a Yahoo: 30 ruedas alcanzan para la última vela más las
# 20 previas del promedio, con margen para feriados.
PERIODO_VOLUMEN = "30d"

# Cantidad de ruedas previas que forman el promedio de comparación.
RUEDAS_PROMEDIO = 20

# Mínimo de ruedas para que el RVOL signifique algo (criterio del manual).
MIN_RUEDAS = 20

# SEC EDGAR exige un User-Agent identificatorio; sin él responde 403.
SEC_USER_AGENT = "SimuladorInversionesIA research@simulador.local"
SEC_FORM4_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={ticker}&type=4&output=atom"
)
SEC_TIMEOUT_SEG = 10
ATOM_NS = "{http://www.w3.org/2005/Atom}"


# ---------- Helper interno ----------


def _calcular_rvol(df: pd.DataFrame) -> Optional[float]:
    """
    Calcula el volumen relativo a partir de un DataFrame OHLCV.

    RVOL = volumen de la última rueda / promedio de las `RUEDAS_PROMEDIO`
    ruedas *previas* (la última queda excluida del promedio: si no, se
    compararía contra sí misma y el indicador se diluye).

    Returns:
        El RVOL redondeado a 2 decimales, o `None` si no hay histórico
        suficiente, falta la columna `Volume` o el promedio da 0 (papel sin
        operar, típico de bonos ilíquidos). El llamador decide qué significa
        ese `None` según el instrumento.
    """
    if df is None or "Volume" not in df.columns:
        return None

    volumenes = df["Volume"].dropna()
    if len(volumenes) < MIN_RUEDAS:
        return None

    vol_actual = float(volumenes.iloc[-1])
    vol_medio = float(volumenes.iloc[-(RUEDAS_PROMEDIO + 1):-1].mean())
    if vol_medio <= 0:
        return None

    return round(vol_actual / vol_medio, 2)


# ---------- Tarea 5.1 — RVOL ----------


def check_unusual_volume(ticker: str) -> Tuple[bool, float]:
    """
    Detecta acumulación institucional oculta en una acción / CEDEAR vía RVOL.

    RVOL = volumen de la última rueda / promedio de las 20 ruedas previas.
    Un RVOL >= `config.RVOL_ACUMULACION` indica entrada de manos fuertes.

    Es **contexto, no un filtro**: un `False` no debe vetar ninguna señal.

    Args:
        ticker: símbolo de Yahoo Finance (ej. "AAPL"). Para instrumentos
            locales hay que sumarle `config.SUFIJO_YF_BYMA`.

    Returns:
        `(es_acumulacion, rvol)`.
        - `es_acumulacion`: True si `rvol >= config.RVOL_ACUMULACION`.
        - `rvol`: volumen relativo redondeado a 2 decimales.
        Ante error de red, ticker inexistente o histórico insuficiente
        devuelve `(False, 0.0)` — el criterio conservador del manual para
        acciones: sin datos no se afirma que haya acumulación.
    """
    try:
        df = market_data.get_history(ticker, period=PERIODO_VOLUMEN)
    except Exception:
        # Red caída, ticker inválido, rate limit de Yahoo: sin dato de volumen.
        return False, 0.0

    rvol = _calcular_rvol(df)
    if rvol is None:
        return False, 0.0

    return rvol >= config.RVOL_ACUMULACION, rvol


def check_bond_unusual_volume(ticker_yf: str) -> Tuple[bool, float]:
    """
    Detecta volumen anómalo en un bono argentino (soberano o provincial).

    Mismo cálculo que `check_unusual_volume`, con dos diferencias que pide el
    manual de bonos:

    1. El umbral es `config.RVOL_ACUMULACION_BONOS` (más bajo: el mercado local
       de renta fija mueve mucho menos volumen que un CEDEAR líquido).
    2. **Sin histórico suficiente NO se bloquea.** Los bonos argentinos tienen
       datos pobres en Yahoo Finance —series cortadas, volumen en 0, tickers
       que ni figuran—, así que la falta de datos devuelve `(True, 1.0)`:
       "neutro, seguí adelante". Bloquear por un dato que Yahoo casi nunca tiene
       equivaldría a apagar el escaneo de bonos.

    Args:
        ticker_yf: símbolo **ya con sufijo de Yahoo** (ej. "AL30.BA").

    Returns:
        `(es_acumulacion, rvol)`, con el RVOL redondeado a 2 decimales.
        Ante error o histórico insuficiente devuelve `(True, 1.0)`.
    """
    try:
        df = market_data.get_history(ticker_yf, period=PERIODO_VOLUMEN)
    except Exception:
        return True, 1.0

    rvol = _calcular_rvol(df)
    if rvol is None:
        return True, 1.0

    return rvol >= config.RVOL_ACUMULACION_BONOS, rvol


# ---------- Tarea 5.2 — SEC Form 4 (compras de directores) ----------


def check_sec_form4_cluster(ticker: str) -> Tuple[bool, str]:
    """
    Cuenta filings recientes del Form 4 (operaciones de insiders) en SEC EDGAR.

    Consulta el feed Atom de EDGAR y cuenta las entradas `<entry>`. Si hay al
    menos `config.INSIDERS_MIN_FILINGS`, se interpreta como un *cluster* de
    movimientos de directores, señal clásica de smart money.

    Es **contexto, no un filtro**: un `False` no debe vetar ninguna señal.

    Limitaciones conocidas (honestidad sobre lo que el dato es y lo que no):
    - EDGAR acepta el **ticker** en el parámetro `CIK=` para la mayoría de las
      empresas de EE.UU., pero no para todas. Si no lo resuelve devuelve HTML
      de error con status 200 en lugar de Atom: ese caso se detecta cuando
      `ET.fromstring` falla y se responde neutro con el motivo.
    - El feed no filtra por fecha ni por código de transacción: cuenta los Form 4
      **más recientes** publicados, sin distinguir compra en mercado abierto
      (código P) de venta o de ejercicio de opciones. Para eso habría que abrir
      cada filing, lo que está fuera del alcance de la tarea 5.2.
    - EDGAR pagina de a 40 entradas por defecto, así que el conteo satura en 40.
      Para un emisor grande (AAPL, NVDA, TSLA) el resultado es prácticamente
      siempre True: leerlo como "hay actividad de insiders registrada", no como
      "hay un cluster de compras esta semana".
    - Solo aplica a emisores registrados en la SEC: para un CEDEAR el subyacente
      sí figura; para un bono argentino, no.

    Args:
        ticker: símbolo del emisor en EE.UU. (ej. "AAPL").

    Returns:
        `(tiene_insiders, detalle)`.
        - `tiene_insiders`: True si las entradas del feed son
          `>= config.INSIDERS_MIN_FILINGS`.
        - `detalle`: mensaje en español, apto para mostrar en la UI.
        Ante error de red, HTTP != 200 o respuesta no parseable devuelve
        `(False, motivo)` sin levantar excepción.
    """
    if not isinstance(ticker, str) or not ticker.strip():
        return False, "Ticker vacío o inválido para la consulta a SEC EDGAR."

    simbolo = ticker.strip().upper()
    url = SEC_FORM4_URL.format(ticker=simbolo)
    headers = {"User-Agent": SEC_USER_AGENT}

    try:
        res = requests.get(url, headers=headers, timeout=SEC_TIMEOUT_SEG)
    except Exception as e:
        return False, f"Error SEC API para {simbolo}: {e}"

    if res.status_code != 200:
        return False, f"Sin respuesta SEC para {simbolo} (HTTP {res.status_code})"

    try:
        root = ET.fromstring(res.content)
    except ET.ParseError:
        # Caso real y frecuente: EDGAR no mapeó el ticker a un CIK y devolvió
        # una página HTML de error con status 200.
        return False, (
            f"SEC EDGAR no devolvió Atom para {simbolo}: probablemente el ticker "
            "no mapea a un CIK (respuesta HTML de error)."
        )
    except Exception as e:
        return False, f"Error leyendo la respuesta de SEC para {simbolo}: {e}"

    if root.tag != f"{ATOM_NS}feed":
        # Variante de lo anterior: la página de error sí era XML bien formada
        # (XHTML). Sin este chequeo se leería como un feed con cero entradas,
        # o sea "sin insiders", que es una conclusión distinta de "no hay dato".
        return False, (
            f"SEC EDGAR no devolvió un feed Atom para {simbolo} (raíz '{root.tag}'): "
            "probablemente el ticker no mapea a un CIK."
        )

    entradas_form4 = len(root.findall(f"{ATOM_NS}entry"))
    tiene_insiders = entradas_form4 >= config.INSIDERS_MIN_FILINGS

    if entradas_form4 == 0:
        return False, f"Sin filings Form 4 recientes para {simbolo}"

    return tiene_insiders, f"Insiders detectados: {entradas_form4} filings Form 4 en {simbolo}"


# ---------- Conveniencia para la integración con /senales ----------


def contexto_smart_money(ticker: str, es_bono: bool = False) -> dict:
    """
    Arma el paquete de contexto de smart money de un ticker, en una sola llamada.

    Pensado para que `/senales` (Tarea 5.2, integración a cargo de otra persona)
    sume estos campos a cada resultado. **Es contexto informativo: nunca vetea
    una señal.** Quien integre debe adjuntarlo a la respuesta, no usarlo para
    descartar candidatos.

    Tolerante a fallos por diseño: si Yahoo o la SEC no responden, devuelve
    valores neutros y lo deja dicho en `insiders_detalle`; nunca levanta.

    Args:
        ticker: para acciones/CEDEARs, el símbolo de Yahoo (ej. "AAPL"); para
            bonos, el símbolo **con sufijo** (ej. "AL30.BA").
        es_bono: si es True usa `check_bond_unusual_volume` (umbral de bonos,
            sin bloqueo por falta de datos) y omite la consulta a la SEC, que
            no aplica a deuda argentina.

    Returns:
        dict con:
        - `rvol` (float): volumen relativo, 2 decimales. 0.0 si no se pudo
          calcular en acciones; 1.0 (neutro) en bonos sin datos.
        - `es_acumulacion` (bool): RVOL por encima del umbral que corresponda.
        - `insiders_detectados` (bool): cluster de Form 4 en SEC EDGAR.
        - `insiders_detalle` (str): explicación en español del resultado
          anterior, incluido el motivo cuando la consulta falló.
    """
    if es_bono:
        es_acumulacion, rvol = check_bond_unusual_volume(ticker)
        insiders_detectados = False
        insiders_detalle = "No aplica: la SEC solo publica Form 4 de emisores de EE.UU."
    else:
        es_acumulacion, rvol = check_unusual_volume(ticker)
        insiders_detectados, insiders_detalle = check_sec_form4_cluster(ticker)

    return {
        "rvol": rvol,
        "es_acumulacion": es_acumulacion,
        "insiders_detectados": insiders_detectados,
        "insiders_detalle": insiders_detalle,
    }
