"""
Parámetros cuantitativos y universos de instrumentos.

Reemplaza a los `config.py` / `config_bonds.py` de ejemplo de los manuales.
Los valores están documentados y justificados en `docs/parametros-riesgo.md`:
si acá cambia un número, ese documento tiene que reflejarlo.

Regla: ningún otro módulo hardcodea capital, stop-loss, ratio R/B ni umbrales de
veto. Todo se importa de acá.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _env_float(clave: str, default: float) -> float:
    try:
        return float(os.getenv(clave, default))
    except (TypeError, ValueError):
        return default


def _env_bool(clave: str, default: bool = False) -> bool:
    valor = os.getenv(clave)
    if valor is None:
        return default
    return valor.strip().lower() in {"1", "true", "yes", "si", "sí"}


# ---------- Credenciales (nunca hardcodear valores reales acá) ----------

IOL_USERNAME = os.getenv("IOL_USERNAME", "")
IOL_PASSWORD = os.getenv("IOL_PASSWORD", "")
IOL_API_URL = os.getenv("IOL_API_URL", "https://api.invertironline.com")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "")


# ---------- Capital y tamaño de posición ----------

CAPITAL_TOTAL = _env_float("CAPITAL_TOTAL", 100_000.0)      # ARS
MAX_POSICIONES = int(_env_float("MAX_POSICIONES", 2))
MONTO_POR_POSICION = _env_float("MONTO_POR_POSICION", 50_000.0)


# ---------- Gestión de riesgo por operación ----------

STOP_LOSS_MAX_PCT = 0.030          # 3,0% de pérdida máxima estricta
STOP_LOSS_TOLERANCIA_PCT = 0.035   # por encima de esto, el stop por ATR se recorta
ATR_MULTIPLICADOR = 1.5            # stop = precio - 1.5 * ATR(14)
ATR_PERIODO = 14
TAKE_PROFIT_RATIO = 2.0            # R/B mínimo 1:2


# ---------- Umbrales de veto por riesgo de mercado ----------

VIX_NIVEL_PANICO = 25.0
VIX_SUBA_DIARIA_MAX = 0.10         # +10% intradiario dispara el circuit breaker
SENTIMIENTO_MIN_ACCIONES = -0.35   # score FinBERT promedio mínimo (acciones/CEDEARs)
SENTIMIENTO_MIN_BONOS = -0.30      # score FinBERT promedio mínimo (bonos)
EARNINGS_DIAS_VETO = 7             # no abrir posición a menos de 7 días de un balance


# ---------- Smart money (contexto, nunca veta una señal) ----------

RVOL_ACUMULACION = 2.0
RVOL_ACUMULACION_BONOS = 1.8
INSIDERS_MIN_FILINGS = 2


# ---------- Renta fija ----------

SPREAD_BID_ASK_MAX = 0.006         # 0,6% de spread bid/ask máximo en CI


# ---------- Kill switch de ejecución real ----------

EJECUCION_REAL_HABILITADA = _env_bool("EJECUCION_REAL_HABILITADA", False)


# ---------- Universo de CEDEARs líquidos en BYMA ----------
# Manual_Maestro_Bot_Inversion_IA_Completo.docx, sección 3.

TICKERS_BYMA = [
    "AAPL",
    "NVDA",
    "MELI",
    "SPY",
    "QQQ",
    "KO",
    "MSFT",
    "AMZN",
    "GOOGL",
    "TSLA",
]

# Benchmark contra el que se mide el régimen de mercado y la fuerza relativa.
TICKER_BENCHMARK = "SPY"


# ---------- Universo de bonos soberanos y provinciales ----------
# Manual_Maestro_Bot_Bonos_Soberanos_Provinciales.docx, sección 3.

BONOS_SOBERANOS = ["AL30", "GD30", "AL35", "GD35", "AE38"]
BONOS_PROVINCIALES = ["BA37D", "CO26", "NDT25", "PMM29"]
UNIVERSO_BONOS = BONOS_SOBERANOS + BONOS_PROVINCIALES

# Meses de pago de renta/amortización. Se veta la compra dentro de la ventana
# de corte (días 1 a 12 de esos meses).
# Manual_Maestro_Bot_Bonos_Soberanos_Provinciales.docx, sección 6.
MESES_CORTE_CUPON = {
    "AL30": [1, 7],
    "GD30": [1, 7],
    "AL35": [1, 7],
    "GD35": [1, 7],
    "AE38": [1, 7],
}
CUPON_DIA_DESDE = 1
CUPON_DIA_HASTA = 12


# ---------- Sufijos de Yahoo Finance para instrumentos locales ----------
# Los bonos argentinos cotizan en Yahoo con sufijo .BA (ej. "AL30.BA").

SUFIJO_YF_BYMA = ".BA"


# ---------- Gestión de salidas (PositionManager) ----------
# Salida escalonada que reemplaza al take-profit fijo R/B 1:2 sobre la posición
# ya abierta. Spec: `Pasar_ulises_31_de_agosto.docx`, secciones 1 y 2.
# Los consume `app/position_manager.py` como defaults del constructor.

from datetime import time as _time  # noqa: E402  (import local de esta sección)

SALIDA_SL_INICIAL_PCT = 0.030        # SL0: -3,0% sobre el 100% de la posición
SALIDA_TP1_PCT = 0.045               # TP1: +4,5%, vende el 50% y cancela el SL0
SALIDA_TRAILING_PULLBACK = 0.012     # retroceso máximo tolerado desde el pico: 1,2%
SALIDA_PISO_GARANTIZADO_PCT = 0.035  # piso infranqueable post-TP1: +3,5%
SALIDA_TP2_PCT = 0.080               # TP2 techo: +8,0%, cierra el remanente

# Cierre preventivo 10 minutos antes de la campana de BYMA (17:00 hs): si queda
# posición con TP1 cobrado, se liquida a mercado. Cero riesgo overnight.
SALIDA_HORA_CIERRE_PREVENTIVO = _time(16, 50, 0)

# Zona horaria de la rueda local, en nombre IANA (la resuelve `pytz` en el módulo
# que la usa, para no meter esa dependencia acá).
TZ_BYMA = "America/Argentina/Buenos_Aires"


# ---------- Filtros de entrada (EntryValidator) ----------
# docs/specs-txt/pasar_ulises_31_2.txt, secciones 1 y 3 (cuadro de los dos
# filtros de calidad previos a la compra).

# Tolerancia máxima de "persecución" del precio sobre el nivel de ruptura: si el
# papel ya trepó más de 1,0%, la señal se considera vencida (el stop del 3%
# quedaría demasiado lejos y se arruina el ratio R/B).
ENTRADA_MAX_CHASE_PCT = 0.010

# Caída diaria máxima tolerada en el índice de referencia. Por debajo de -1,0%
# el mercado está liquidando y se bloquean todas las compras del día.
ENTRADA_MERCADO_CAIDA_MAX = -0.010

# Ruedas de la media móvil simple diaria del benchmark (tendencia macro).
SMA_BENCHMARK_PERIODO = 200

# Índice de referencia según el tipo de instrumento. Los bonos no tienen
# benchmark de régimen: ese riesgo lo cubren los filtros de fixed_income_filters.
BENCHMARK_POR_TIPO = {
    "CEDEAR": "SPY",    # S&P 500 (alternativa para tecnológicos: "QQQ")
    "ACCION": "^MERV",  # índice Merval (IMV) en Yahoo Finance
    "BONO": None,
}


# ---------- Referencia del nivel de ruptura (anti-chase, Tarea 4.5) ----------
# Contra qué nivel se mide la "vigencia" de la señal (ENTRADA_MAX_CHASE_PCT).
#
# El spec (`pasar_ulises_31_2.docx`) define el breakout como el máximo de las 20
# ruedas previas, PERO ahí la señal de entrada es el cruce sobre ese máximo. Los
# 7 filtros de este proyecto no son una estrategia de ruptura: entran por
# tendencia (precio > EMA20 > EMA50) y fuerza relativa. Usar el máximo de 20
# ruedas agrega una exigencia que el spec no pide —estar en máximos— y en una
# corrida real dejó 0 candidatos de 10.
#
#   "ema_corta"              -> el disparador real de nuestra señal (EMA20).
#                               Mide cuánto se extendió el precio sobre el nivel
#                               que el filtro 3 exige superar. DEFAULT.
#   "maximo_previo"          -> literal del spec: máximo de RUEDAS_BREAKOUT
#                               ruedas previas, y se veta si el precio no lo
#                               superó todavía. El más estricto.
#   "maximo_previo_sin_piso" -> mismo nivel, pero sin vetar por "todavía no lo
#                               superó": solo rechaza si se pasó de la tolerancia.
BREAKOUT_REFERENCIA = "ema_corta"

# Modos válidos, para validar la config al importar.
BREAKOUT_MODOS = ("ema_corta", "maximo_previo", "maximo_previo_sin_piso")

# Con "maximo_previo_sin_piso" no se exige que el precio ya haya superado el
# nivel: entrar temprano en la tendencia no es "perseguir" el precio.
BREAKOUT_EXIGE_SUPERAR = BREAKOUT_REFERENCIA != "maximo_previo_sin_piso"
