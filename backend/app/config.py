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


# ---------- Capital y tamaño de posición (Tarea 0.1) ----------

CAPITAL_TOTAL = _env_float("CAPITAL_TOTAL", 100_000.0)      # ARS
MAX_POSICIONES = int(_env_float("MAX_POSICIONES", 2))

# Cupo de capital de cada estrategia. Tienen que sumar 1.0: son una partición
# del capital, no dos presupuestos independientes.
#
# El swing técnico (Fases 3-4) ya tiene track record en paper trading; el de
# consenso institucional 13F (Tarea 5.5) todavía no. La repartición decidida es
# 40/60 — el ejemplo que trae el plan desde el chat de Gemini.
CUPO_SWING = _env_float("CUPO_SWING", 0.40)
CUPO_SMART_MONEY = _env_float("CUPO_SMART_MONEY", 0.60)

# Porcentaje máximo del cupo de una estrategia que puede ir a un solo activo.
#
# ⚠ Decisión consciente, fuera del rango que nombra el plan. La Tarea 0.1 sugiere
# 15-20% (manuales) o 10% (Gemini) sobre el capital TOTAL; acá se resolvió dejar
# el 50% que ya estaba. Para que el número conviva con los cupos, se aplica
# sobre el cupo de cada estrategia y no sobre el capital total: con 50% del
# capital total ($50.000) una sola posición de swing se pasaría de su propio
# cupo ($40.000), que es aritméticamente imposible.
#
# Resultado con los valores de hoy:
#   swing        cupo $40.000 → $20.000 por posición × 2 = $40.000
#   smart money  cupo $60.000 → $30.000 por posición
LIMITE_POR_OPERACION = _env_float("LIMITE_POR_OPERACION", 0.50)

# Piso de saldo disponible por debajo del cual no se abren posiciones nuevas
# (lo pide la Tarea 11.2). Con menos que esto, el costo fijo de comisiones se
# come cualquier ganancia razonable de la operación.
SALDO_MINIMO_OPERAR = _env_float("SALDO_MINIMO_OPERAR", 10_000.0)

ESTRATEGIA_SWING = "SWING"
ESTRATEGIA_SMART_MONEY = "SMART_MONEY"

CUPOS_POR_ESTRATEGIA = {
    ESTRATEGIA_SWING: CUPO_SWING,
    ESTRATEGIA_SMART_MONEY: CUPO_SMART_MONEY,
}


def cupo_de(estrategia: str) -> float:
    """Capital en ARS asignado a una estrategia."""
    return CAPITAL_TOTAL * CUPOS_POR_ESTRATEGIA.get(estrategia, 0.0)


def monto_por_posicion(estrategia: str = ESTRATEGIA_SWING) -> float:
    """Monto máximo de una sola posición dentro del cupo de su estrategia."""
    return cupo_de(estrategia) * LIMITE_POR_OPERACION


# Compatibilidad: el monto de una posición de swing, que es lo que significaba
# `MONTO_POR_POSICION` antes de que existieran los cupos.
MONTO_POR_POSICION = monto_por_posicion(ESTRATEGIA_SWING)


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


# ---------- Consenso institucional 13F (Tareas 5.3, 5.4 y 5.5) ----------
# A diferencia del RVOL y los Form 4 de arriba, esto NO es contexto: es una
# estrategia completa, con su propio cupo de capital, que genera y cierra
# operaciones por sí sola.

# Fondos que se siguen, por CIK de SEC EDGAR. Lista corta y curada a propósito:
# cada fondo son dos filings que bajar y parsear, y el consenso pierde sentido
# si se sigue a demasiados (todos terminan tocando los mismos papeles grandes).
FONDOS_13F = {
    "0001067983": "Berkshire Hathaway",
    "0001350694": "Bridgewater Associates",
    "0001037389": "Renaissance Technologies",
    "0001167483": "Tiger Global Management",
    "0001061768": "Baupost Group",
}

# Cuántos fondos distintos tienen que coincidir para generar una señal. Seguir a
# uno solo es seguir a una persona; el consenso es la señal.
SMART_MIN_CONSENSO = 2

# Peso mínimo de la posición en la cartera del fondo. Por debajo de esto, la
# posición es ruido para el fondo y no dice nada sobre su convicción.
SMART_MIN_PESO_CARTERA = 0.01   # 1,0% de la cartera del fondo

# Si el precio actual ya se despegó más que esto del precio promedio al que
# entró el fondo, la señal llegó tarde. Los 13F salen con hasta 45 días de
# rezago legal: sin este filtro se compraría sistemáticamente arriba.
SMART_MAX_DELAY_SUBA = 0.10     # +10%

# User-Agent obligatorio para la API de SEC EDGAR: rechaza pedidos sin uno que
# identifique a quien consulta. Se puede pisar desde el entorno.
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT", "Simulador Inversiones IA (contacto: ulisessbaretta@gmail.com)"
)

# Dónde se guardan los filings ya descargados, para poder comparar un trimestre
# contra el anterior. Va fuera de git (ver .gitignore).
DIR_DATOS_13F = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "13f"
)


# ---------- Renta fija ----------

SPREAD_BID_ASK_MAX = 0.006         # 0,6% de spread bid/ask máximo en CI


# ---------- Señal alternativa por RSI (Tarea 3.7) ----------
# Fuente de señal paralela a los 7 filtros, deliberadamente mucho más simple,
# para comparar cuál rinde mejor en paper trading. Conviven: ninguna reemplaza
# a la otra.

RSI_PERIODO = 14
RSI_SOBREVENTA = 30.0              # RSI por debajo de esto dispara la señal

# Spread bid/ask máximo tolerado para considerar líquido a un CEDEAR. Más
# amplio que el de bonos porque el mercado de CEDEARs es menos profundo.
#
# OJO: hoy no hay de dónde sacar el spread real — yfinance da el precio de la
# acción en EE.UU., no el libro del CEDEAR en BYMA. El chequeo está escrito y
# probado, pero es NO BLOQUEANTE hasta que `IOLClient` (Fase 8) traiga bid/ask
# de verdad. Ver `rsi_signal.chequear_liquidez`.
LIQUIDEZ_SPREAD_MAX = 0.010


# ---------- Kill switch de ejecución real ----------
#
# `MODO_FANTASMA=true` (el default) significa que NUNCA sale una orden real:
# el sistema escanea, notifica y registra igual que si operara, pero no llama a
# la API de IOL. Recién con `MODO_FANTASMA=false` se opera de verdad.
#
# Antes esto se llamaba `EJECUCION_REAL_HABILITADA` (con la lógica invertida).
# El plan (Tarea 11.2) pide unificar en un solo nombre para no terminar con dos
# variables haciendo lo mismo. La variable vieja ya no se lee: si quedó en algún
# `.env` se avisa por consola, porque ignorarla en silencio sería peligroso.

MODO_FANTASMA = _env_bool("MODO_FANTASMA", True)

if os.getenv("EJECUCION_REAL_HABILITADA") is not None:
    import warnings

    warnings.warn(
        "EJECUCION_REAL_HABILITADA quedó obsoleta y se está ignorando. "
        "Usá MODO_FANTASMA (true = no se envía ninguna orden real, es el default). "
        f"Valor efectivo ahora: MODO_FANTASMA={MODO_FANTASMA}.",
        stacklevel=2,
    )


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


# ---------- Mapeo CUSIP → ticker (Tarea 5.3) ----------
# Los 13F identifican cada posición por CUSIP, no por ticker. No existe una
# fuente pública gratuita de CUSIP→ticker (el mapeo oficial es un producto pago
# de CUSIP Global Services), así que se usa un mapeo manual acotado al universo
# habilitado, que es exactamente lo que sugiere la Tarea 5.3.
#
# Verificados contra filings 13F reales: el nombre del emisor que trae el filing
# coincide con el ticker. Los marcados con ✓ se confirmaron en el 13F de
# Berkshire del trimestre 2026-06-30.
CUSIP_A_TICKER = {
    "037833100": "AAPL",   # ✓ APPLE INC
    "191216100": "KO",     # ✓ COCA COLA CO
    "02079K305": "GOOGL",  # ✓ ALPHABET INC (clase A)
    "02079K107": "GOOG",   # ✓ ALPHABET INC (clase C)
    "67066G104": "NVDA",   # NVIDIA CORP
    "58733R102": "MELI",   # MERCADOLIBRE INC
    "594918104": "MSFT",   # MICROSOFT CORP
    "023135106": "AMZN",   # AMAZON COM INC
    "88160R101": "TSLA",   # TESLA INC
    "78462F103": "SPY",    # SPDR S&P 500 ETF TRUST
    "46090E103": "QQQ",    # INVESCO QQQ TRUST
}


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

# Vencimiento por tiempo (el `SWING_MAX_DIAS` del plan, Tarea 3.5). Red de
# seguridad contra posiciones "dormidas": si a los N días corridos desde la
# compra no tocó ni el stop-loss inicial ni el TP1, se cierra a mercado igual.
# No gana ni pierde, pero inmoviliza capital y cupo de posiciones.
#
# Son días CORRIDOS, no ruedas: el capital está inmovilizado también el fin de
# semana, así que contar ruedas subestimaría el costo de oportunidad.
SALIDA_SWING_MAX_DIAS = 10

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
