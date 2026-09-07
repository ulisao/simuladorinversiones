# PROGRESS.md — Historial de tareas

Una entrada por tarea resuelta, en orden cronológico. El formato está fijado en
`CLAUDE.md`. La lista completa de tareas está en `tareasdesarrollo.md`.

---

## 2026-08-29 — Entrada retroactiva — Estado del proyecto al arrancar

> [!summary] Qué se hizo
> nada en esta entrada; documenta el punto de partida sobre el que
> se construye todo lo que sigue.

Estado al momento de escribir esto:

- **Backend** FastAPI + SQLite (SQLAlchemy 2.0), corriendo en el puerto 8123.
  - `calculations.py` replica las fórmulas del Excel
    `Simulador_Inversiones_IA_Paper_Trading.xlsx`: costo por tramo
    `(comisión + derechos) × (1 + IVA)`, y de ahí comisiones de compra/venta,
    resultado neto y rendimiento neto %.
  - Modelos `BrokerConfig` (fila única con las tasas) y `Trade` (una fila por
    operación de paper trading, con `tipo` ∈ CEDEAR/ACCION/BONO).
  - Endpoints: `/health`, `GET|PUT /broker-config`, CRUD de `/trades`,
    `POST /trades/{id}/cerrar` y `GET /dashboard`.
  - Los campos calculados **no se guardan**: se derivan al vuelo, así nunca se
    desincronizan con la config de comisiones vigente.
  - `seed.py` carga las 5 operaciones de ejemplo de la planilla original.
- **Frontend** Next.js (App Router) + Tailwind, con tres páginas: Dashboard (`/`),
  Simulador (`/simulador`) y Configuración (`/config`).
- **Docs**: los cinco manuales originales en `docs/` (`.docx`).

**Archivos tocados:** ninguno.

**Cómo se probó:** no aplica.

> [!note] Pendiente / notas
> el simulador de paper trading funciona; falta todo lo que
> está en `tareasdesarrollo.md` de la Fase 2 en adelante.

---

## 2026-08-29 — Tarea 1.2 — Documentar convenciones del repo para Claude Code

> [!summary] Qué se hizo
> se creó `CLAUDE.md` con la descripción del proyecto, la estructura
> de carpetas, las convenciones de código (backend en español, `calculations.py` no se
> toca sin tests, nada de credenciales hardcodeadas, filtros que devuelven
> `(bool, dict)` con motivo) y la instrucción explícita de agregar una entrada a
> `PROGRESS.md` al terminar cada tarea. Se creó este `PROGRESS.md` con la entrada
> retroactiva de arriba.

Extra fuera del alcance estricto de la tarea, hecho para desbloquear las tareas que
lo necesitan: se extrajo el texto de los cinco `.docx` de `docs/` a
`docs/specs-txt/*.txt`, para poder citar el código de los manuales sin depender de
abrir Word.

**Archivos tocados:** `CLAUDE.md` (nuevo), `PROGRESS.md` (nuevo),
`docs/specs-txt/*.txt` (nuevos, generados).

**Cómo se probó:** no aplica — son archivos de documentación.

> [!note] Pendiente / notas
> ninguna.

---

## 2026-08-29 — Tarea 0.1 (parcial, PROVISORIA) — Parámetros de riesgo

> [!summary] Qué se hizo
> la Tarea 0.1 es 👤 (humana) y no está resuelta, pero las tareas
> 3.2, 9.2 y 11.2 leen `docs/parametros-riesgo.md`. Para desbloquearlas se creó ese
> documento **cargado con los valores por defecto de los manuales**, marcado en grande
> como PROVISORIO y pendiente de confirmación humana. En paralelo se creó
> `backend/app/config.py`, que es de dónde los importa el código (ningún módulo
> hardcodea estos números).

Valores cargados: `CAPITAL_TOTAL` $100.000 ARS, `MAX_POSICIONES` 2,
`MONTO_POR_POSICION` $50.000, `STOP_LOSS_MAX_PCT` 3,0%, `TAKE_PROFIT_RATIO` 1:2,
`VIX_NIVEL_PANICO` 25,0, `SENTIMIENTO_MIN_ACCIONES` -0,35,
`SENTIMIENTO_MIN_BONOS` -0,30, `SPREAD_BID_ASK_MAX` 0,6%,
`EJECUCION_REAL_HABILITADA` false.

**Archivos tocados:** `docs/parametros-riesgo.md` (nuevo), `backend/app/config.py` (nuevo).

**Cómo se probó:** import del módulo sin errores (ver entrada de la Tarea 9.1).

> [!warning] Pendiente / notas
> **estos números no están acordados con el dueño del
> capital.** Hay que revisarlos y firmarlos antes de la Fase 11 (dinero real).

---

## 2026-08-29 — Tarea 1.3 — Tests automatizados de las fórmulas de comisión

> [!summary] Qué se hizo
> se cubrió `app/calculations.py` con 8 tests: las 5 operaciones de
> ejemplo del Excel (AAPL, NVDA, NXE, MELI, TSLA) con los resultados netos calculados
> a mano contra la fórmula de la planilla, el test de `BrokerRates` (0,7018% por tramo
> / 1,4036% ida y vuelta), un caso de posición abierta y uno de break-even.

Valores esperados usados (tasa 0,007018), calculados aparte y puestos como literales
—no recalculados con la función bajo test—:

| Ticker | cant × entrada → salida | costo_total_entrada | monto_neto_cobrado | resultado_neto |
|---|---|---|---|---|
| AAPL | 25 × 12500 → 13450 | 314.693,125 | 333.890,1975 | **+19.197,07** |
| NVDA | 15 × 18200 → 17600 | 274.915,914 | 262.147,248 | **−12.768,67** |
| NXE | 84 × 9400 → 10150 | 795.141,4128 | 846.616,4532 | **+51.475,04** |
| MELI | 8 × 38500 → 38900 | 310.161,544 | 309.015,9984 | **−1.145,55** |
| TSLA | 12 × 22100 → 21300 | 267.061,1736 | 253.806,1992 | **−13.254,97** |

**Archivos tocados:** `backend/tests/test_calculations.py`, `backend/tests/__init__.py`,
`backend/conftest.py` (nuevos). `backend/requirements.txt` (pytest + httpx).

**Cómo se probó:** `cd backend && ./venv/Scripts/python.exe -m pytest tests/test_calculations.py -v`
→ `8 passed in 0.11s`.

> [!note] Pendiente / notas
> ninguna.

---

## 2026-08-29 — Tarea 2.1 — Módulo de precios en vivo con yfinance

> [!summary] Qué se hizo
> `app/market_data.py` con `get_last_price(ticker)`,
> `get_history(ticker, period="60d")`, la excepción propia `MarketDataError` y una
> cache en memoria con TTL de 5 minutos (`TTL_CACHE_SEGUNDOS = 300`) que evita
> repetir el pedido del histórico de SPY en cada ticker del escaneo.

Dos decisiones que importan aguas abajo:
- `get_history` devuelve `df.copy()`, así los módulos que agregan columnas EMA no
  ensucian el DataFrame cacheado.
- Se silencia el logger de yfinance, que ante ticker inválido imprimía un
  `HTTP Error 404` que parecía un stacktrace sin manejar.

**Archivos tocados:** `backend/app/market_data.py`, `backend/tests/test_market_data.py` (nuevos).

**Cómo se probó:**

```
get_last_price('AAPL') = 319.70001220703125
get_history('AAPL')    -> shape=(60, 7)
  columnas: ['Open','High','Low','Close','Volume','Dividends','Stock Splits']
get_last_price('XXXX123') -> MarketDataError: Sin datos de mercado para 'XXXX123'
  (periodo 5d). Verifica el ticker; si es un instrumento local acordate del sufijo '.BA'.
cache: 1ra llamada get_history('SPY') 0.299s | 2da (cache) 0.000s
```

`pytest tests/test_market_data.py -v` → `10 passed`.

> [!note] Pendiente / notas
> `Ticker.history()` devuelve **7 columnas**, no 5 (OHLCV +
> `Dividends` + `Stock Splits`), y el índice es un `DatetimeIndex` con timezone.

---

## 2026-08-29 — Tarea 2.2 — Autocompletar precio actual en el simulador

> [!summary] Qué se hizo
> endpoint `GET /market/precio/{ticker}` en el backend (404 con
> `detail` en español si el ticker no existe) y botón **"Usar precio de mercado"**
> en `NewTradeForm.tsx`, con estado "Buscando…", deshabilitado si el ticker está
> vacío, y el `detail` del 404 mostrado como error legible.

**Archivos tocados:** `backend/app/main.py`, `backend/app/schemas.py`,
`frontend/components/NewTradeForm.tsx`, `frontend/lib/api.ts`, `frontend/lib/types.ts`.

**Cómo se probó:** contra el backend real:

```
GET /market/precio/AAPL     -> {"ticker":"AAPL","precio":319.70001220703125}
GET /market/precio/XXXX123  -> HTTP 404 {"detail":"Sin datos de mercado para 'XXXX123' ..."}
```

`npx tsc --noEmit` sin errores y `npm run build` compila.

> [!note] Pendiente / notas
> el botón se probó vía el HTML servido y el endpoint real;
> no se hizo una captura de pantalla del click en el navegador.

---

## 2026-08-29 — Tarea 3.1 — Cálculo de ATR y medias móviles

> [!summary] Qué se hizo
> `app/technical_filters.py` con `calculate_atr(df, period=None)`
> (cae en `config.ATR_PERIODO`), `calculate_ema(serie, span)` y
> `agregar_emas(df, spans=(20,50))`, que trabaja sobre una copia y no muta el
> DataFrame recibido.

**Archivos tocados:** `backend/app/technical_filters.py`,
`backend/tests/test_technical_filters.py` (nuevos).

**Cómo se probó:** contra el histórico real de AAPL (60 ruedas):

```
ATR(14) ultimo: 6.0371   (NaN? False)
EMA20 ultimo  : 312.8013
EMA50 ultimo  : 312.2875
Close ultimo  : 319.7
columnas del df original intactas (no mutado):
  ['Open','High','Low','Close','Volume','Dividends','Stock Splits']
```

Valores positivos y sin NaN al final de la serie. Más 10 tests deterministas
(ATR de serie plana = rango diario, gap agranda el TR, EMA20 > EMA50 en tendencia
alcista, no-mutación).

> [!note] Pendiente / notas
> ninguna.

---

## 2026-08-29 — Tarea 3.2 — Los 7 filtros de validación técnica

> [!summary] Qué se hizo
> `evaluate_7_filters(ticker)` en `technical_filters.py`: earnings,
> régimen SPY vs EMA50, tendencia precio > EMA20 > EMA50, fuerza relativa vs SPY a
> 30 ruedas, stop por ATR con tope de riesgo, y take-profit por ratio R/B. Todos los
> parámetros salen de `config.py` (nada hardcodeado).

Dos correcciones deliberadas sobre el código del manual:

| Caso | Qué hace el manual | Qué hace este repo | Por qué |
|---|---|---|---|
| Datos insuficientes | Devuelve `False, {}` | **Siempre** hay `detalle["motivo"]` | Sin motivo se pierde la trazabilidad de por qué no se operó |
| `yf.Ticker().calendar` | Asume DataFrame | Maneja `dict` y DataFrame; si no puede determinar la fecha, **no vetea** | Las versiones nuevas de yfinance devuelven `dict`, y un dato faltante no debe inventar un veto |

**Archivos tocados:** `backend/app/technical_filters.py`.

**Cómo se probó:** contra 5 tickers reales del universo BYMA:

| Ticker | Resultado | Detalle |
|---|---|---|
| AAPL | VETADO | VETO RS: no supera a SPY en 30 ruedas (-2.03% vs 3.67%) |
| NVDA | VÁLIDO | entrada 217,55 · SL 211,02 · TP 230,60 · riesgo 3,0% |
| MELI | VÁLIDO | entrada 1966,25 · SL 1907,26 · TP 2084,22 · riesgo 3,0% |
| TSLA | VETADO | VETO TÉCNICO: no se cumple precio > EMA20 > EMA50 (348.75 / 345.12 / 358.06) |
| KO | VÁLIDO | entrada 89,66 · SL 87,60 · TP 93,77 · riesgo 2,29% |

Los resultados son coherentes con el gráfico: TSLA cotiza debajo de su EMA50, y KO
sale con 2,29% — o sea el recorte al tope no se aplica siempre, discrimina bien.

> [!warning] Pendiente / notas
> el manual recorta el stop al 3,0% solo si el riesgo supera
> el **3,5%**. Se respetó tal cual, pero implica que el riesgo real por operación puede
> llegar hasta 3,5% pese a que `STOP_LOSS_MAX_PCT` diga 3,0% (se vio en AMZN: 3,27%).
> Vale revisarlo al confirmar la Tarea 0.1.

---

## 2026-08-29 — Tarea 3.3 — Endpoint de escaneo de señales

> [!summary] Qué se hizo
> `app/signals.py` con `escanear_senales(tickers=None)` y el endpoint
> `GET /senales`. Recorre `config.TICKERS_BYMA` y devuelve `candidatos` y
> `descartados` — **ningún motivo de veto se pierde**, van todos en `descartados`.
> También se agregó `GET /config/universo` para inspeccionar los universos.

**Archivos tocados:** `backend/app/signals.py` (nuevo), `backend/app/main.py`,
`backend/app/schemas.py`.

**Cómo se probó:** `GET /senales` real, HTTP 200 en 44 s — 4 candidatos, 6 descartados.
Respuesta completa: ver la entrada de la Tarea 4.3 más abajo (es la misma corrida,
ya con el veto de riesgo integrado).

> [!note] Pendiente / notas
> 44 segundos es lento para un request HTTP; la Fase 10 (scanner
> job) lo resuelve escaneando en background en vez de a pedido.

---

## 2026-08-29 — Tarea 3.4 — Página "Señales" en el frontend

> [!summary] Qué se hizo
> `frontend/app/senales/page.tsx`, agregada al `Nav` entre Simulador
> y Configuración. Muestra el estado del VIX, un cartel rojo si el circuit breaker
> está activo, la tabla de señales válidas (ticker, precio, SL, TP, riesgo y el
> contexto de RVOL/insiders/sentimiento) y una segunda tabla con los descartados y
> su motivo. Botón **"Cargar en el simulador"** por señal válida, que navega a
> `/simulador?ticker=&precio=&senal=` y prellena el formulario **sin crear la
> operación**.

### Flujo de prellenado

```mermaid
sequenceDiagram
    participant U as Usuario
    participant S as /senales
    participant API as GET /senales
    participant SIM as /simulador
    participant F as NewTradeForm

    U->>S: "Volver a escanear"
    S->>API: fetch (~45 s)
    API-->>S: candidatos + descartados
    U->>S: "Cargar en el simulador"
    S->>SIM: router.push(?ticker&precio&senal)
    SIM->>F: prefill (useSearchParams + Suspense)
    F-->>U: form abierto y completo
    Note over U,F: NO se envía solo:<br/>el usuario pone la cantidad y confirma
```

**Archivos tocados:** `frontend/app/senales/page.tsx` (nuevo),
`frontend/components/Nav.tsx`, `frontend/components/NewTradeForm.tsx`
(prop `prefill`), `frontend/app/simulador/page.tsx` (lee los query params con
`useSearchParams` dentro de un `Suspense`).

**Cómo se probó:** `npm run build` compila con la ruta `/senales` incluida;
`npx tsc --noEmit` sin errores. Flujo de prellenado verificado sobre el HTML servido:

```
GET /simulador?ticker=NVDA&precio=217.55&senal=...  -> HTTP 200
  value="NVDA"        presente
  value="217.55"      presente
  "Guardar operacion" presente (form abierto, NO enviado solo)
GET /simulador (sin params) -> form cerrado, muestra "+ Nueva operacion"
```

> [!note] Pendiente / notas
> no se tomó captura de pantalla; la verificación fue sobre el
> HTML renderizado y el endpoint real.

---

## 2026-08-29 — Tarea 4.1 — Circuit breaker de VIX

> [!summary] Qué se hizo
> `app/risk_filters.py` con `estado_vix()` (datos crudos para el
> dashboard) y `check_vix_circuit_breaker()` apoyado en ella. Veta si el VIX supera
> `config.VIX_NIVEL_PANICO` o si subió más de `config.VIX_SUBA_DIARIA_MAX` en el día.
> Endpoint `GET /riesgo/vix`.

Criterio ante error: **fail-safe, vetea**. Sin saber si el mercado está en pánico
no se abre posición (es el criterio del manual).

**Archivos tocados:** `backend/app/risk_filters.py` (nuevo), `backend/app/main.py`,
`backend/app/schemas.py`.

**Cómo se probó:**

```
GET /riesgo/vix -> {"vix_actual":14.43,"vix_previo":14.51,"cambio_pct":-0.0055,
                    "veto":false,"motivo":"VIX OK (14.43, -0.6% diario)"}
```

14,43 coincide con el cierre real del VIX del 2026-08-28. Más tests con el VIX
mockeado: nivel de pánico vetea, suba abrupta vetea, error de red vetea.

> [!note] Pendiente / notas
> ninguna.

---

## 2026-08-29 — Tarea 4.2 — Filtro de sentimiento de noticias (FinBERT)

> [!summary] Qué se hizo
> `get_finbert_sentiment(ticker)` en `risk_filters.py`. Lee el RSS de
> Yahoo Finance, veta por palabra crítica, y si no, promedia el score de los últimos
> 5 titulares con FinBERT (`ProsusAI/finbert`) corriendo local, vetando bajo
> `config.SENTIMIENTO_MIN_ACCIONES`.

**El modelo se carga perezosamente y cacheado** con `functools.lru_cache(maxsize=1)`,
y `torch`/`transformers` se importan *dentro* de esa función: si se cargara a nivel
de módulo como en el manual, `import app.main` bajaría 400 MB antes de servir el
primer request. Si las librerías no están, el módulo se importa igual y el veto por
palabras críticas sigue funcionando (degradación segura).

Criterio ante error: **fail-open, no vetea**. Un 429 de Yahoo no es riesgo del activo.

**Archivos tocados:** `backend/app/risk_filters.py`, `backend/requirements.txt`.

**Cómo se probó:** contra tickers reales:

| Ticker | Score | Titular usado |
|---|---|---|
| AAPL | +0,0678 | "John Ternus Becomes Apple's CEO on Sept. 1..." (−0,0173) |
| NVDA | +0,0489 | "Peter Thiel's Fund Reported Zero Stocks for 2 Straight Quarters..." (−0,0305) |
| TSLA | −0,2277 | "Tesla Stock in 2027: Why I Think TSLA Still Has Room to Run" (+0,1841) |

TSLA da negativo pero por encima del umbral de −0,35, así que no vetea.

> [!warning] Pendiente / notas
> **`torch` + `transformers` pesan ~2,5 GB instalados y
> FinBERT necesita ~1 GB de RAM para inferencia. Un VPS free tier de 512 MB–1 GB NO
> alcanza.** Está anotado en `requirements.txt` y en el `README`. Si el deploy va a un
> servidor chico, hay que sacar esas dos líneas: el módulo degrada solo.

---

## 2026-08-29 — Tarea 4.3 — Integrar el veto de riesgo al escaneo de señales

> [!summary] Qué se hizo
> `signals.py` aplica el orden del manual: **VIX → noticias → smart
> money → 7 filtros**. Si el circuit breaker vetea, devuelve lista vacía con
> `veto_global` y **no evalúa ningún ticker**. Si el sentimiento vetea un ticker, se
> descarta con ese motivo sin llegar a los filtros técnicos.

### Orden de chequeos implementado

```mermaid
flowchart TD
    START([GET /senales]) --> VIX{check_vix_circuit_breaker}
    VIX -->|vetea| VACIA[/candidatos: vacío<br/>veto_global: motivo/]
    VIX -->|OK| LOOP[Por cada ticker del universo]
    LOOP --> NEWS{get_finbert_sentiment}
    NEWS -->|vetea| DESC[/descartados + motivo/]
    NEWS -->|OK| SM[contexto_smart_money<br/>informativo, nunca vetea]
    SM --> F7{evaluate_7_filters}
    F7 -->|vetea| DESC
    F7 -->|aprueba| CAND[/candidatos + SL/TP/riesgo/]
```

> [!warning] Bug encontrado y corregido en el camino
> El manual matchea las palabras críticas con `if palabra in titulo`, o sea
> subcadena. En la corrida real eso vetó **SPY y MSFT** porque `"war"` matcheaba
> dentro de "hard**war**e" y "soft**war**e". Un veto es la decisión de no operar:
> no puede dispararse por letras en el medio de otra palabra. Se reemplazó por un
> patrón con límites de palabra, que sigue soportando frases ("bank run",
> "cesación de pagos") y acentos.

**Archivos tocados:** `backend/app/signals.py`, `backend/app/risk_filters.py`,
`backend/tests/test_signals.py`, `backend/tests/test_risk_filters.py`.

**Cómo se probó:** test que mockea `check_vix_circuit_breaker` con veto y confirma
que `/senales` devuelve lista vacía con el motivo, más otro que verifica que **no se
evalúa ningún ticker** cuando el VIX corta. Respuesta real de `GET /senales`
(HTTP 200, 44 s):

```json
{
  "generado": "2026-08-29T23:36:09",
  "universo": ["AAPL","NVDA","MELI","SPY","QQQ","KO","MSFT","AMZN","GOOGL","TSLA"],
  "veto_global": null,
  "vix": {"vix_actual": 14.43, "vix_previo": 14.51, "cambio_pct": -0.0055,
          "veto": false, "motivo": "VIX OK (14.43, -0.6% diario)"},
  "candidatos": [
    {"ticker":"NVDA","precio_entrada":217.55,"stop_loss":211.02,"take_profit":230.6,
     "pct_riesgo":3.0,"sentimiento_score":0.0489,"rvol":1.55,"es_acumulacion":false,
     "insiders_detectados":true,"insiders_detalle":"Insiders detectados: 40 filings Form 4 en NVDA"},
    {"ticker":"MELI","precio_entrada":1966.25,"stop_loss":1907.26,"take_profit":2084.22,
     "pct_riesgo":3.0,"sentimiento_score":0.0319,"rvol":0.68,"es_acumulacion":false,
     "insiders_detectados":true,"insiders_detalle":"Insiders detectados: 40 filings Form 4 en MELI"},
    {"ticker":"KO","precio_entrada":89.66,"stop_loss":87.6,"take_profit":93.77,
     "pct_riesgo":2.29,"sentimiento_score":0.0126,"rvol":0.69,"es_acumulacion":false,
     "insiders_detectados":true,"insiders_detalle":"Insiders detectados: 40 filings Form 4 en KO"},
    {"ticker":"AMZN","precio_entrada":266.43,"stop_loss":257.72,"take_profit":283.84,
     "pct_riesgo":3.27,"sentimiento_score":0.0682,"rvol":1.17,"es_acumulacion":false,
     "insiders_detectados":true,"insiders_detalle":"Insiders detectados: 40 filings Form 4 en AMZN"}
  ],
  "descartados": [
    {"ticker":"AAPL","motivo":"VETO RS: no supera a SPY en 30 ruedas (-2.03% vs 3.67%)."},
    {"ticker":"SPY","motivo":"VETO CISNE NEGRO: Palabra critica 'war' detectada en 'Optics Stocks Slide as AI Hardware Trade Cools...'"},
    {"ticker":"QQQ","motivo":"VETO TECNICO: estructura no alcista, no se cumple precio > EMA20 > EMA50 (716.43 / 714.22 / 715.03)."},
    {"ticker":"MSFT","motivo":"VETO CISNE NEGRO: Palabra critica 'war' detectada en 'Microsoft, Palantir Among Stocks To Watch As Software Bounces Back'"},
    {"ticker":"GOOGL","motivo":"VETO TECNICO: estructura no alcista, no se cumple precio > EMA20 > EMA50 (346.59 / 346.47 / 350.97)."},
    {"ticker":"TSLA","motivo":"VETO TECNICO: estructura no alcista, no se cumple precio > EMA20 > EMA50 (348.75 / 345.12 / 358.06)."}
  ]
}
```

> Esta corrida es **anterior** al fix de palabras críticas — se dejó tal cual porque
> es la evidencia del bug: ahí se ven SPY y MSFT vetados por el falso positivo de
> "war" dentro de "hardware" y "software". Con el fix aplicado esos dos vuelven a
> evaluarse técnicamente. Verificación del fix:
>
> ```
> 'Optics Stocks Slide as AI Hardware Trade Cools'          -> None (antes: 'war')
> 'Microsoft, Palantir ... As Software Bounces Back'        -> None (antes: 'war')
> 'Warner Bros posts quarterly results'                     -> None
> 'Israel-Hamas war escalates, oil spikes'                  -> 'war'
> 'Bank run at regional lender triggers panic'              -> 'bank run'
> 'SEC probe into accounting practices widens'              -> 'sec probe'
> 'Advierten por una cesacion de pagos inminente' (acento)  -> 'cesacion de pagos'
> ```

> [!note] Pendiente / notas
> ninguna.

---

## 2026-08-29 — Tareas 5.1 y 5.2 — Smart money: RVOL e insiders (SEC Form 4)

> [!summary] Qué se hizo
> `app/smart_money.py` con `check_unusual_volume(ticker)`,
> `check_bond_unusual_volume(ticker_yf)`, `check_sec_form4_cluster(ticker)` y
> `contexto_smart_money(ticker, es_bono=False)`. Los campos `rvol`, `es_acumulacion`,
> `insiders_detectados` e `insiders_detalle` viajan en cada candidato de `/senales`.

**Es contexto informativo, nunca vetea una señal** — hay un test que lo fija.

**Archivos tocados:** `backend/app/smart_money.py`,
`backend/tests/test_smart_money.py` (nuevos), `backend/app/signals.py`,
`backend/app/schemas.py`.

**Cómo se probó:**

```
=== Tabla ticker -> RVOL ===
TICKER      RVOL   ES_ACUMULACION
AAPL        0.81            False
NVDA        1.55            False
TSLA        0.99            False

=== check_sec_form4_cluster ===
AAPL -> (True, 'Insiders detectados: 40 filings Form 4 en AAPL')
NVDA -> (True, 'Insiders detectados: 40 filings Form 4 en NVDA')
NOEXISTE123 -> (False, 'SEC EDGAR no devolvio Atom para NOEXISTE123: probablemente
                el ticker no mapea a un CIK (respuesta HTML de error).')

=== contexto_smart_money('AAPL') ===
{'rvol': 0.81, 'es_acumulacion': False, 'insiders_detectados': True,
 'insiders_detalle': 'Insiders detectados: 40 filings Form 4 en AAPL'}
```

`pytest tests/test_smart_money.py` → `25 passed`.

> [!warning] Pendiente / notas
> **el conteo de Form 4 satura.** El feed de EDGAR pagina de
> a 40 y no filtra por fecha, así que AAPL, NVDA y TSLA devuelven exactamente 40. Con
> `INSIDERS_MIN_FILINGS=2`, cualquier emisor grande da `True` casi siempre. Se lee
> como "hay actividad de insiders registrada", **no** como "cluster de compras esta
> semana", y no distingue compra (código P) de venta ni de ejercicio de opciones —
> eso exigiría abrir cada filing, fuera del alcance de la 5.2. Como es contexto y no
> filtro, no afecta ninguna decisión, pero conviene no leerlo como señal alcista.

⚠️ **Bonos: Yahoo Finance no tiene datos.** `AL30.BA` y `GD30.BA` devuelven
`MarketDataError`. Por eso `check_bond_unusual_volume` devuelve `(True, 1.0)` sin
bloquear (criterio del manual de bonos). En la práctica el RVOL de bonos hoy es
siempre neutro; el dato real habría que sacarlo de IOL.

---

## 2026-08-29 — Tarea 9.2 — Filtros institucionales para renta fija

> [!summary] Qué se hizo
> `app/fixed_income_filters.py` con
> `evaluate_bond_filters(simbolo, precio_mercado, df_historico, ahora=None)` (veto por
> corte de cupón, tendencia vs EMA20, stop por ATR con tope estricto de 3,0%,
> take-profit por ratio) y `check_spread_bid_ask(compra, venta, ultimo)` como función
> separada y reusable, extraída del `ejecutar_ciclo` de `bot_bonds.py`.

El parámetro `ahora=` se agregó para poder testear el veto de cupón sin depender del
mes en que se corra.

**Archivos tocados:** `backend/app/fixed_income_filters.py`,
`backend/tests/test_fixed_income_filters.py` (nuevos).

**Cómo se probó:**

| Bono | Escenario | Resultado | Motivo / detalle |
|---|---|---|---|
| AL30 | sin histórico | VÁLIDO | entrada 72,50 · SL 70,33 · TP 76,85 · riesgo 3,0% · `datos_limitados=True` |
| GD30 | sin histórico | VÁLIDO | entrada 78,30 · SL 75,95 · TP 83,00 · riesgo 3,0% |
| BA37D | sin histórico (provincial) | VÁLIDO | entrada 61,20 · SL 59,36 · TP 64,87 · riesgo 3,0% |
| AL30 | serie alcista sintética | VÁLIDO | entrada 74,14 · SL 72,64 · TP 77,14 · riesgo 2,02% |
| GD30 | serie bajista sintética | VETADO | VETO TENDENCIA: cotiza a $73,49, debajo de su EMA20 ($75,06) |
| AL30 | forzando 2027-01-05 | VETADO | VETO CORTE CUPÓN: paga en el mes 1 y hoy es 05/01, dentro de la ventana (días 1 a 12) |

```
check_spread_bid_ask(72.40, 72.60, 72.50) -> (True,  spread 0.28% dentro del maximo de 0.60%)
check_spread_bid_ask(71.00, 74.00, 72.50) -> (False, VETO SPREAD: 4.14% supera el maximo de 0.60%)
check_spread_bid_ask(0, 0, 0)             -> (False, VETO SPREAD: sin cotizacion) - sin division por cero
```

`pytest tests/test_fixed_income_filters.py` → `13 passed`.

> [!note] Pendiente / notas
> los bonos argentinos no tienen histórico en Yahoo Finance, así
> que en producción el camino real va a ser el **modo degradado** (`datos_limitados`)
> hasta que la Tarea 9.4 traiga cotizaciones de IOL. Por eso los caminos de EMA20 y
> ATR se probaron con series sintéticas: con datos reales hoy no se alcanzan.

---

## 2026-08-29 — Tarea 9.3 — Filtro de noticias de deuda soberana

> [!summary] Qué se hizo
> `check_bonds_news_sentiment(simbolo_bono)` en `risk_filters.py`, con
> el feed de Google News en español (`hl=es-419&gl=AR`), las palabras críticas de deuda
> del manual y el umbral `config.SENTIMIENTO_MIN_BONOS`. Reusa el mismo modelo FinBERT
> cacheado que la Tarea 4.2 (no se carga dos veces).

Se normalizan los titulares (minúsculas + sin tildes) antes de comparar: los
titulares en español vienen acentuados ("cesación de pagos") y la lista del manual
está sin acentos, así que sin normalizar la mitad de las palabras nunca matchearía.

**Archivos tocados:** `backend/app/risk_filters.py`, `backend/tests/test_risk_filters.py`.

**Cómo se probó:**

| Bono | Score | Veto | Titular usado |
|---|---|---|---|
| AL30 | +0,3238 | No | "Los bonos en los que conviene invertir y cuáles evitar, según el nuevo semáforo de la City — iProfesional" (+0,504) |
| GD30 | +0,3559 | No | "Bonos Soberanos: ¿Momento de alargar duration? — Invertir Online" (+0,063) |

Más tests de palabras críticas con y sin tildes: "reperfilamiento", "cesacion de
pagos" y "cesación de pagos" (acentuado) detectan; "Riesgo país baja tras el pago de
cupones" no vetea.

> [!note] Pendiente / notas
> ninguna.

---

## 2026-08-29 — Consolidación y estado de la suite

> [!summary] Qué se hizo
> se cablearon todos los endpoints nuevos en `main.py`
> (`/market/precio/{ticker}`, `/riesgo/vix`, `/senales`, `/config/universo`), se
> creó `backend/pytest.ini` con los markers `network` y `slow`, se actualizó
> `requirements.txt` con las versiones instaladas, y se agregaron `.gitignore`,
> `backend/.env.example` y la documentación de variables de entorno en el `README`.

**Cómo se probó:**

```
cd backend && ./venv/Scripts/python.exe -m pytest -q
102 passed in 19.30s

./venv/Scripts/python.exe -m pytest -q -m "not network"
95 passed, 7 deselected in 3.47s
```

Frontend: `npx tsc --noEmit` sin errores, `npm run build` compila las 5 rutas
(`/`, `/config`, `/senales`, `/simulador`, `/_not-found`).

> [!note] Pendiente / notas
> ver la sección de tareas bloqueadas abajo.

---

---

## 2026-09-01 — Tarea 9.1 (entrada faltante) — Config y universo de bonos

> [!summary] Qué se hizo
> Entrada que faltaba: la Tarea 9.1 se resolvió junto con la creación de
> `backend/app/config.py` (ver la entrada de la Tarea 0.1), pero nunca se le
> escribió su propia entrada, y la de 0.1 apuntaba acá. Se agregaron
> `BONOS_SOBERANOS`, `BONOS_PROVINCIALES`, `UNIVERSO_BONOS` y
> `MESES_CORTE_CUPON`, y se confirmó que `BONO` ya estaba en `TIPOS` de
> `NewTradeForm.tsx`.

**Archivos tocados:** `backend/app/config.py`, `frontend/components/NewTradeForm.tsx` (solo verificado, sin cambios).

**Cómo se probó:**

```
TICKERS_BYMA: ['AAPL','NVDA','MELI','SPY','QQQ','KO','MSFT','AMZN','GOOGL','TSLA']
BONOS_SOBERANOS: ['AL30','GD30','AL35','GD35','AE38']
BONOS_PROVINCIALES: ['BA37D','CO26','NDT25','PMM29']
UNIVERSO_BONOS: ['AL30','GD30','AL35','GD35','AE38','BA37D','CO26','NDT25','PMM29']
MESES_CORTE_CUPON: {'AL30':[1,7],'GD30':[1,7],'AL35':[1,7],'GD35':[1,7],'AE38':[1,7]}
```

`grep TIPOS frontend/components/NewTradeForm.tsx` → `const TIPOS = ["CEDEAR", "ACCION", "BONO"];`

> [!note] Pendiente / notas
> ninguna.

---

## 2026-09-01 — Tarea 3.5 — Gestor de salidas dinámicas (PositionManager)

> [!summary] Qué se hizo
> `backend/app/position_manager.py` con la máquina de estados completa de la
> spec: SL inicial -3,0% → TP1 +4,5% que vende el 50% y cancela el SL → trailing
> de 1,2% con piso garantizado en +3,5% (monótono creciente) → TP2 techo +8,0% →
> cierre preventivo a las 16:50 hs ART. Los parámetros salen de `config.py`
> (sección `SALIDA_*`), no hardcodeados. Se agregó la tabla `PositionState` para
> persistir el estado y no perder el seguimiento ante un reinicio a mitad de
> rueda.

### Ciclo de vida de la posición

```mermaid
stateDiagram-v2
    [*] --> Abierta: compra 100%
    Abierta --> Cerrada: precio ≤ entrada·0,97<br/>INITIAL_STOP_LOSS_HIT
    Abierta --> PostTP1: precio ≥ entrada·1,045<br/>TP1_PARTIAL_50PCT (vende 50%)
    PostTP1 --> PostTP1: nuevo pico<br/>el stop sube (nunca baja)
    PostTP1 --> Cerrada: precio ≥ entrada·1,08<br/>TP2_CEILING_HIT
    PostTP1 --> Cerrada: precio ≤ stop vigente<br/>TRAILING_STOP_1.2PCT_HIT
    PostTP1 --> Cerrada: 16:50 hs ART<br/>END_OF_DAY_CUTOFF_1650
    Cerrada --> [*]
```

**Archivos tocados:** `backend/app/position_manager.py`, `backend/tests/test_position_manager.py` (nuevos); `backend/app/config.py` y `backend/app/models.py` (secciones agregadas al final); `backend/requirements.txt` (`pytz`).

**Cómo se probó:** `pytest tests/test_position_manager.py -v` → **28 passed in 0.28s**, recorriendo cada fase en orden, el borde de cantidad impar, la prioridad del cierre de las 16:50 y el round-trip de (de)serialización del estado.

> [!warning] Pendiente / notas
> Con `total_qty=1`, `total_qty // 2` da `qty=0` en el TP1: no hay orden que
> mandar pero el gestor igual pasa a estado post-TP1. El job de la Tarea 3.6
> saltea la orden en ese caso (hay test).

---

## 2026-09-01 — Tarea 3.6 — Aplicar PositionManager a las posiciones abiertas

> [!summary] Qué se hizo
> `backend/position_monitor_job.py`: recorre las operaciones abiertas, consulta
> el precio con `market_data.get_last_price` y le pasa el tick al
> `PositionManager`, persistiendo el estado después de cada uno. La **venta
> parcial del TP1 se resuelve partiendo la operación en dos registros**
> (`crud.vender_parcial`): uno cerrado por lo vendido y otro abierto por el
> resto. Se eligió así para no tocar `calculations.py`, que está congelada por
> tests: cada registro se sigue calculando con la fórmula del Excel, sin casos
> especiales.

### Cómo se refleja una venta parcial

```mermaid
flowchart LR
    A["Trade #1<br/>10 papeles @ 100<br/>ABIERTA"] -->|"TP1: vende 5 @ 104,5"| B["Trade #1<br/>5 papeles @ 100<br/>ABIERTA"]
    A --> C["Trade #2 (nuevo)<br/>5 papeles @ 100 → 104,5<br/>CERRADA"]
    B -.->|"el PositionState sigue<br/>atado al Trade #1"| D[(position_states)]
```

**Archivos tocados:** `backend/position_monitor_job.py`, `backend/tests/test_position_monitor.py` (nuevos); `backend/app/crud.py` (funciones nuevas al final); `backend/app/models.py` (se reemplazó `datetime.utcnow`, deprecado, por un helper con `timezone.utc`).

**Cómo se probó:** `pytest tests/test_position_monitor.py -q` → **21 passed in 2.06s**. El test clave verifica que partir la operación **no altera el resultado total**: la suma de los dos registros da exactamente lo mismo que la posición entera vendida al mismo precio. También se cubre que el estado sobrevive entre ciclos (el trailing sube y nunca baja), el cierre de las 16:50 y la ventana de rueda.

> [!warning] Pendiente / notas
> El criterio de aceptación pide dejar el job corriendo en horario de mercado con
> una operación real y mostrar cómo cambia de estado. **Eso no se hizo**: se
> probó con precio y timestamp inyectados. Falta la corrida en vivo.
>
> La notificación por Telegram queda como un `logger.info` en `_notificar()`:
> cuando exista la Tarea 7.1 solo hay que poner ahí el `send_telegram`.

---

## 2026-09-01 — Tarea 4.4 — Filtro de régimen de mercado y vigencia (EntryValidator)

> [!summary] Qué se hizo
> `backend/app/entry_validator.py` con los dos filtros de la spec:
> `is_market_healthy` (índice > SMA200 diaria y caída diaria ≥ -1,0%) e
> `is_signal_valid` (anti-chase, tolerancia +1,0% sobre el nivel de ruptura), más
> `can_open_position` que los encadena. Se suman `datos_benchmark(tipo)` —que
> trae precio, SMA200 y variación diaria del índice desde una sola descarga de
> `market_data.get_history(..., "1y")`— y `chequear_regimen_mercado(tipo)`, que
> devuelve `(bool, dict)` con motivo, la convención de filtros del repo.

**Archivos tocados:** `backend/app/entry_validator.py`, `backend/tests/test_entry_validator.py` (nuevos); `backend/app/config.py` (sección `ENTRADA_*` / `BENCHMARK_POR_TIPO`).

**Cómo se probó:** `pytest tests/test_entry_validator.py` → **47 passed offline + 1 network**. Tabla de escenarios (salida real):

| Escenario | Resultado | Motivo |
|---|---|---|
| Mercado sano + señal vigente | APROBADO | COMPRA APROBADA: ambos filtros verificados con éxito. |
| Índice por debajo de la SMA200 | RECHAZADO | VETO MERCADO: índice por debajo de su SMA200 (590,00 < 600,00). |
| Índice cae más de 1% en el día | RECHAZADO | VETO MERCADO: día de venta masiva en el índice (-1,50% < -1,0%). |
| Precio extendido más de 1% | RECHAZADO | VETO SEÑAL: señal vencida, precio extendido un 1,80%. |
| Precio por debajo del breakout | RECHAZADO | VETO SEÑAL: el precio actual todavía no superó el nivel de ruptura (99,40 < 100,00). |

Datos reales obtenidos: **SPY** precio 761,78 · SMA200 708,29 · rueda -0,69% (252 ruedas) → mercado sano. **^MERV** 3.049.454,50 · SMA200 2.999.461,74 · +0,51% (245 ruedas).

> [!note] Pendiente / notas
> Ante falta de datos del benchmark, `chequear_regimen_mercado` **veta**
> (fail-safe), mismo criterio que el circuit breaker de VIX: dejar pasar
> habilitaría el universo entero justo el día que Yahoo no responde. Los bonos no
> tienen benchmark (`BENCHMARK_POR_TIPO["BONO"] is None`) y el filtro no aplica.

---

## 2026-09-01 — Tarea 4.5 — Integrar EntryValidator al escaneo de señales

> [!summary] Qué se hizo
> `signals.py` reescrito con el orden que pide el checklist: **VIX → régimen de
> mercado → [por ticker] noticias → 7 filtros → anti-chase**. Los dos primeros
> son globales y cortan el escaneo sin evaluar ningún ticker. `evaluate_7_filters`
> ahora devuelve `breakout_level`, congelado en el instante en que la señal se
> valida. Se agregó `regimen_mercado` a la respuesta de `/senales`.

### Orden de chequeos

```mermaid
flowchart TD
    START([GET /senales]) --> VIX{VIX}
    VIX -->|vetea| G1[/veto_global · lista vacía/]
    VIX -->|OK| REG{Régimen de mercado<br/>índice vs SMA200 y caída diaria}
    REG -->|vetea| G1
    REG -->|OK| LOOP[Por cada ticker]
    LOOP --> NEWS{Noticias FinBERT}
    NEWS -->|vetea| DESC[/descartados + motivo/]
    NEWS -->|OK| SM[Smart money · solo informa]
    SM --> F7{7 filtros técnicos}
    F7 -->|vetea| DESC
    F7 -->|aprueba| CHASE{Anti-chase<br/>vs breakout congelado}
    CHASE -->|vetea| DESC
    CHASE -->|OK| CAND[/candidatos/]
```

**Archivos tocados:** `backend/app/signals.py`, `backend/app/schemas.py`, `backend/app/technical_filters.py` (`breakout_level`), `backend/app/entry_validator.py` (parámetro `exigir_superar`), `backend/app/config.py` (`BREAKOUT_REFERENCIA`), `backend/tests/test_signals.py`.

**Cómo se probó:** `pytest -q` → **214 passed**. Respuesta real de `GET /senales` (74 s):

```
veto_global: None | VIX: VIX OK (16.34, +9.5% diario)
REGIMEN: SPY precio 761.78 SMA200 708.29 dia -0.69%

CANDIDATOS (1):
  NVDA   entrada=217.44  EMA20=216.26  ext=0.55%  SL=210.92  TP=230.49  riesgo=3.0%

DESCARTADOS (9):
  AAPL   VETO RS: no supera a SPY en 30 ruedas (-0.15% vs 1.92%).
  MELI   VETO SEÑAL: señal vencida, precio extendido un 3.39% sobre la ruptura
  SPY    VETO TÉCNICO: estructura no alcista (761.78 / 765.0x / ...)
  QQQ    VETO SENTIMIENTO: FinBERT Score negativo (-0.61 < -0.35)
  KO     VETO TÉCNICO: estructura no alcista (88.00 / 88.47 / ...)
  MSFT   VETO SEÑAL: señal vencida, precio extendido un 3.20% sobre la ruptura
  AMZN   VETO TÉCNICO: estructura no alcista (254.92 / 260.2x / ...)
  GOOGL  VETO TÉCNICO: estructura no alcista (335.02 / 344.7x / ...)
  TSLA   VETO TÉCNICO: estructura no alcista (356.09 / 348.1x / ...)
```

Hay dos descartes reales por anti-chase (MELI y MSFT). El descarte por régimen de
mercado no se dio naturalmente —SPY está sano— y se cubre con
`test_mercado_bajista_corta_el_escaneo_sin_evaluar_tickers`, que además verifica
que **no se evalúa ningún ticker** cuando el mercado vetea.

> [!warning] Pendiente / notas
> ⚠️ **Decisión de estrategia pendiente de confirmar.** El spec define el
> `breakout_level` como el máximo de 20 ruedas previas, pero ahí la señal de
> entrada **es** el cruce de ese máximo. Nuestros 7 filtros entran por tendencia,
> no por ruptura: con el máximo de 20 ruedas el escaneo dio **0 candidatos de
> 10**, porque exigía además estar en máximos.
>
> Se agregó `config.BREAKOUT_REFERENCIA` con tres modos y default `"ema_corta"`
> (la EMA20 es el nivel que el filtro 3 exige superar, o sea el disparador real
> de nuestra señal). Con ese default el filtro discrimina bien: NVDA pasa con
> +0,55% y MELI/MSFT se descartan por +3,39% y +3,20%.
>
> Los otros dos modos son `"maximo_previo"` (literal del spec) y
> `"maximo_previo_sin_piso"` (mismo nivel, sin vetar por "todavía no lo superó").

---

## 2026-09-01 — Auditoría de las 16 tareas previas y correcciones

> [!summary] Qué se hizo
> Se auditaron las 16 tareas 🤖 ya implementadas contra el texto **actualizado**
> del plan. Resultado: 9 cumplen, 6 parcialmente, 0 incumplen. Se corrigieron
> cuatro hallazgos; los otros tres quedaron documentados.

### Hallazgos corregidos

| # | Hallazgo | Corrección |
|---|---|---|
| 1 | **El veto por palabras críticas dejaba pasar plurales.** El fix del falso positivo de `"war"` dentro de `"software"` quedó demasiado estricto: `sanctions`, `SEC probes`, `bank runs`, `defaults`, `Cesaciones de pagos` **no vetaban**. Arreglar un falso positivo había abierto un falso negativo peor. | Patrón con plural tolerado **por término** (no solo al final, porque en "cesaciones de pagos" la marca cae en la primera palabra), y `y → ies` para `bankruptcy`. 4 tests nuevos. |
| 4 | **`/senales` leía el VIX dos veces** y las lecturas podían discrepar: si la segunda fallaba, la respuesta salía con `veto_global` y el VIX en verde al lado. | Una sola lectura; el veto se deriva de ese dict. Test que cuenta las lecturas. |
| 3 | `estado_vix()` prometía fail-safe en el docstring pero con histórico vacío devolvía `veto=False`. | Se documentó la excepción real (es literal del manual) en vez de prometer algo que no hace. |
| 7 | `docs/parametros-riesgo.md` nombraba `CUPON_DIAS_VETO`, que no existe. | Corregido a `CUPON_DIA_DESDE` / `CUPON_DIA_HASTA`. |

### Hallazgos documentados, sin cambio de código

| # | Hallazgo | Por qué no se tocó |
|---|---|---|
| 2 | Nada marca `stop_loss`/`take_profit` como valor de referencia, y el frontend persiste ese texto en el campo `senal`. | No hay contradicción funcional hoy. Conviene revisarlo cuando el `PositionManager` se conecte a la ejecución real. |
| 5 | El "filtro de riesgo país" que nombra el alcance de la Tarea 9.2 no existe. | El manual **no trae código** de riesgo país: EMBI+ solo figura en la tabla descriptiva. Es imprecisión del plan, no deuda de código. |
| 6 | Faltaba la entrada de la Tarea 9.1 en `PROGRESS.md`. | Corregido: se agregó más arriba. |

**Archivos tocados:** `backend/app/risk_filters.py`, `backend/app/signals.py`, `backend/tests/test_risk_filters.py`, `backend/tests/test_signals.py`, `docs/parametros-riesgo.md`, `PROGRESS.md`.

**Cómo se probó:** verificación directa del fix de plurales contra los 6 casos que la auditoría reportó como no detectados (los 6 vetan ahora) y los 4 falsos positivos (ninguno vuelve). Suite completa: **214 passed**.

> [!note] Pendiente / notas
> `docs/parametros-riesgo.md` ahora documenta también las constantes `SALIDA_*`
> y `ENTRADA_*` de las Tareas 3.5 y 4.4.

---

## 2026-08-29 - Verificacion final del fix de palabras criticas

**Que se hizo:** se volvio a correr `GET /senales` real ya con el patron de limites
de palabra aplicado, para confirmar en el pipeline completo (no solo a nivel unitario)
que el falso positivo desaparecio y que no se rompio ningun veto legitimo.

**Como se probo:** `curl http://localhost:8123/senales` -> HTTP 200 en 44,4 s.

```
CANDIDATOS (5):   <- antes eran 4
  NVDA   entrada=217.55    SL=211.02    TP=230.6     riesgo=3.0%
  MELI   entrada=1966.25   SL=1907.26   TP=2084.22   riesgo=3.0%
  KO     entrada=89.66     SL=87.6      TP=93.77     riesgo=2.29%
  MSFT   entrada=513.53    SL=498.9     TP=542.78    riesgo=2.85%   <- recuperado
  AMZN   entrada=266.43    SL=257.72    TP=283.84    riesgo=3.27%

DESCARTADOS (5):
  AAPL   VETO RS: no supera a SPY en 30 ruedas (-2.03% vs 3.67%).
  SPY    VETO SENTIMIENTO: FinBERT Score negativo (-0.73 < -0.35)   <- motivo real ahora
  QQQ    VETO TECNICO: estructura no alcista (716.43 / 714.22 / 715.03)
  GOOGL  VETO TECNICO: estructura no alcista (346.59 / 346.47 / 350.97)
  TSLA   VETO TECNICO: estructura no alcista (348.75 / 345.12 / 358.06)

Falsos positivos de 'war' restantes: 0
```

**Lo que cambio respecto de la corrida anterior:**

- **MSFT** paso de vetado ('war' dentro de "software") a **candidato valido** con
  riesgo 2,85%. Era una senal legitima que el bug estaba descartando.
- **SPY** sigue vetado, pero ahora por un motivo real: FinBERT le da -0,73, muy por
  debajo del umbral de -0,35. El veto por sentimiento funciona; lo que estaba mal
  era solo el matcheo por subcadena.

> [!note] Pendiente / notas
> ninguna. Suite final: `102 passed` (95 sin red).

---

## 2026-09-06 — Tareas 7.1, 7.2, 10.1 y 12.2 — Telegram, escaneo periódico y reporte semanal

> [!summary] Qué se hizo
> Llegó el token del bot de Telegram (Tarea 0.3 👤), así que se liquidaron las
> cuatro tareas 🤖 que dependían solo de esa credencial: el módulo de
> notificaciones, las alertas en cierres de posición, el job de escaneo
> periódico y el reporte semanal automático. Las tareas que dependen de IOL
> (Fases 8, 9.4 y 11), de Google Sheets (6.1/6.2) o del VPS (10.3) siguen
> bloqueadas.

### Qué se construyó

| Tarea | Entregable | Dónde |
|---|---|---|
| 7.1 | `send_telegram(mensaje)` + endpoint `POST /notificaciones/test` | `backend/app/notifications.py`, `backend/app/main.py` |
| 7.2 | Alerta al cerrar una operación y en cada venta del gestor de salidas | `backend/app/main.py`, `backend/position_monitor_job.py` |
| 10.1 | Job que escanea cada 10 min en rueda BYMA y notifica lo nuevo | `backend/scanner_job.py` |
| 12.2 | Reporte semanal comparado contra el histórico | `backend/app/weekly_report.py` |

### Flujo del scanner

```mermaid
flowchart TD
    SCH{{schedule}} -->|cada 10 min| SEN[ciclo_senales]
    SCH -->|cada 1 min| POS[ciclo_posiciones]
    SCH -->|viernes 17:30| REP[weekly_report]

    SEN --> H{¿rueda BYMA?<br/>L-V 11:00-17:00 ART}
    H -- no --> NADA[No escanea]
    H -- sí --> ESC[signals.escanear_senales]
    ESC --> V{¿veto global?}
    V -- sí --> AVISO[Telegram: escaneo bloqueado<br/>1 vez por día]
    V -- no --> DED{¿ya notificada hoy?}
    DED -- sí --> SKIP[Se saltea]
    DED -- no --> TG[Telegram: señal detectada]

    POS --> CAD{¿pasó el intervalo?<br/>300 s · 60 s desde 16:40}
    CAD -- sí --> MON[position_monitor_job.ciclo]
    MON --> TG2[Telegram: ventas del gestor]

    REP --> TG3[Telegram: resumen de la semana]
```

### Decisiones

> [!note] HTML en vez del `parse_mode="Markdown"` del manual
> El manual (`Manual_Maestro_Bot_Inversion_IA_Completo.docx`, sección 8) usa
> Markdown legacy. Con eso, un motivo como `TP1_PARTIAL_50PCT` rompe el parseo
> (los `_` abren cursiva) y Telegram devuelve HTTP 400 — justo en el mensaje que
> avisa que se vendió media posición. Se usa HTML con todo valor dinámico
> escapado (`notifications.esc`), y ante un 400 de formato se reintenta **una
> vez** en texto plano: es preferible un aviso feo a ningún aviso.

> [!note] El default de `send_telegram` es texto plano
> `parse_mode` se pide explícitamente. Así, cualquier texto arbitrario (un
> mensaje de error, un motivo del gestor) no puede romper el envío por accidente;
> solo los armadores de mensaje, que escapan todo, piden `"HTML"`.

> [!note] Deduplicación en memoria, no en tabla
> El alcance de la Tarea 10.1 permite las dos. Se eligió un set en memoria con
> claves `TICKER@YYYY-MM-DD`, que se vacía al cambiar de jornada: una señal que
> sigue vigente mañana vuelve a avisar, pero no se repite doce veces el mismo
> lunes. No hace falta persistirlo — si el proceso se reinicia, el peor caso es
> un aviso repetido, y una tabla nueva por eso no se justifica.

> [!warning] `schedule` usa el reloj del sistema, no `TZ_BYMA`
> El chequeo de horario de rueda sí se hace en ART
> (`position_monitor_job.ahora_art`), pero el `friday at 17:30` del reporte
> semanal es hora local del servidor. Por eso la Tarea 10.2 👤 pide dejar el VPS
> en `America/Argentina/Buenos_Aires`.

### Bug encontrado y corregido durante la prueba real

> [!warning] `rendimiento_neto_pct` es una fracción, no un porcentaje
> La primera corrida real contra Telegram avisó **"+0.08%"** en una operación que
> había rendido **8,47%**. `calculations.compute_trade` devuelve
> `rendimiento_neto_pct` como fracción (`0.0847`), igual que el Excel y que
> `formatPct` del frontend. Los dos armadores de mensaje lo estaban imprimiendo
> como si ya fuera porcentaje. Corregido en `notifications._pct_de_fraccion` y en
> el detalle de `weekly_report`, con tests que fijan la unidad. `calculations.py`
> no se tocó: el error estaba en la presentación, no en la fórmula.

### Fuera de alcance, documentado

> [!todo] El scanner todavía no escanea bonos
> La Tarea 10.1 pide correr también `/senales/bonos`, pero ese endpoint es la
> Tarea 9.4, que depende de `IOLClient` (8.1) para las cotizaciones en CI. Queda
> el flag `scanner_job.ESCANEO_BONOS_HABILITADO = False` marcando el punto exacto
> donde se engancha cuando lleguen las credenciales de IOL.

**Archivos tocados:** `backend/app/notifications.py` (nuevo),
`backend/app/weekly_report.py` (nuevo), `backend/scanner_job.py` (nuevo),
`backend/app/main.py`, `backend/app/schemas.py`, `backend/position_monitor_job.py`,
`backend/requirements.txt`, `backend/tests/test_notifications.py` (nuevo),
`backend/tests/test_scanner_job.py` (nuevo), `backend/tests/test_weekly_report.py` (nuevo),
`README.md`, `PROGRESS.md`.

### Cómo se probó

Suite completa sin red:

```
$ ./venv/Scripts/python.exe -m pytest -q -m "not network"
245 passed, 8 deselected, 53 warnings in 12.37s
```

Los 39 tests nuevos (16 de notificaciones, 12 del scanner, 11 del reporte) corren
con `requests.post` y `signals.escanear_senales` mockeados: ninguno le pega a
Telegram ni a Yahoo Finance.

**Prueba real contra el Telegram configurado** (criterio de aceptación de las
cuatro tareas):

```
$ ./venv/Scripts/python.exe -c "from app import notifications; ..."
configurado: True
{'enviado': True, 'motivo': ''}

# 7.1 endpoint + 7.2 cierre, vía TestClient sobre la base real
POST /notificaciones/test -> {'enviado': True, 'motivo': ''}
cierre HTTP 200 | neto 85.26 | rendimiento fraccion 0.0847 -> mensaje dice +8.47%
operacion de prueba borrada

# 12.2 reporte semanal
$ ./venv/Scripts/python.exe scanner_job.py --reporte-semanal
17:05:26  INFO    Reporte semanal: {'enviado': True, 'motivo': ''}

# 10.1 scanner, con el chequeo de horario forzado a "siempre activo"
$ ./venv/Scripts/python.exe scanner_job.py --una-vez --ignorar-horario
17:05:50  INFO    FinBERT cargado (ProsusAI/finbert), etiquetas={0: 'positive', 1: 'negative', 2: 'neutral'}
17:06:21  INFO    Escaneo: 1 candidato(s), 1 nuevo(s) notificado(s), 9 descartado(s)
17:06:21  INFO    Ciclo terminado: 1 señal(es) notificada(s), 0 acción(es) del gestor
```

Contenido real del reporte semanal que llegó:

```
📊 REPORTE SEMANAL (2026-08-31 → 2026-09-06)

🟢 Resultado neto: $957.89 (+38.32%)
• Operaciones cerradas: 1 (1 ganadoras / 0 perdedoras)
• Tasa de acierto: 100.00%
• Capital movido: $2,500.00
• Comisiones pagadas: $42.10

Detalle
• AAPL $957.89 (+38.05%)

Contra el histórico
Primera semana con operaciones cerradas: no hay histórico contra el que comparar.
```

![Mensajes recibidos en Telegram: prueba, cierre de posición, señal y reporte semanal](./docs/assets/telegram-alertas.png)

> [!todo] Falta la captura
> Los cuatro mensajes llegaron al chat configurado (los `enviado: True` de arriba
> son la respuesta real de la API de Telegram), pero la captura de pantalla que
> piden los "Testing esperado" de 7.1, 7.2, 10.1 y 12.2 la tiene que sacar una
> persona desde el celular y guardarla en `docs/assets/telegram-alertas.png`.

> [!note] Pendiente / notas
> La operación de prueba que se creó para verificar la alerta de cierre se borró
> al terminar: `simulador.db` quedó con las mismas operaciones que antes.

---

---

## 2026-09-06 (2) — Reconciliación con el plan actualizado (`tareas-desarrollo.md`)

> [!summary] Qué se hizo
> Llegó una versión nueva del plan (`tareas-desarrollo.md`, reemplaza a
> `tareasdesarrollo.md`) con cambios que vienen del chat de Gemini del 6/9. Se
> compararon las dos versiones tarea por tarea y se aplicó al código todo lo que
> tocaba trabajo ya hecho, más la única tarea 🤖 nueva que no depende de
> credenciales que faltan.

### Qué cambió en el plan, y qué se hizo con cada cosa

| Tarea | Qué cambió en el plan | Estado |
|---|---|---|
| 2.1 | Advertencia: el precio de `yfinance` es la **acción subyacente en USD**, no el CEDEAR en pesos | ✅ aplicado |
| 3.5 | Sumar vencimiento por tiempo (`SWING_MAX_DIAS`) al `PositionManager` | ✅ aplicado |
| 3.7 | **Tarea nueva**: señal alternativa por RSI de sobreventa | ✅ aplicada |
| 11.2 | Renombrar el kill switch a `MODO_FANTASMA` "para no tener dos variables haciendo lo mismo" | ✅ solo el rename (el resto de 11.2 sigue bloqueado por IOL) |
| 5.3 / 5.4 / 5.5 | **Tareas nuevas**: estrategia 13F de consenso institucional | ⏸ no se empezó — ver abajo |
| 8.4 | **Tarea nueva**: dólar CCL vía `IOLClient` | ⛔ bloqueada: depende de la Tarea 8.1 (credenciales de IOL) |
| 8.1 / 11.1 / 11.2 (resto) / 0.1 / 0.5 / 10.4 | Detalles nuevos sobre reintentos de 401, rutas de la API, position sizing dinámico, cupos de capital | ⛔ bloqueadas o son 👤 |
| 1.3 / 2.2 / 3.6 / 4.5 / 5.2 / 6.2 / 8.3 / 9.4 / 11.3 | Solo cambios de formato del `.md` (`##` → `#`, callouts a texto plano) | — sin efecto en el código |

Ninguna tarea del plan viejo fue borrada en el nuevo: son 5 agregadas y 18 con
el cuerpo editado.

### Tarea 2.1 — el precio no es el del CEDEAR

> [!warning] Era una trampa real, no un detalle de documentación
> `yf.Ticker("AAPL")` devuelve la acción en Nueva York **en dólares** (hoy:
> `319.97`). El CEDEAR de AAPL en BYMA cotiza **en pesos**, con ratio de
> conversión y dólar CCL de por medio. Sirve para el patrón técnico (el CEDEAR
> sigue el movimiento porcentual del subyacente), pero **no** para calcular
> cuántos papeles comprar ni para mostrar un precio de entrada como operable.

Se agregó `market_data.ADVERTENCIA_PRECIO_REFERENCIA` como texto único y viaja
por toda la app:

```mermaid
flowchart LR
    MD["market_data<br/>ADVERTENCIA_PRECIO_REFERENCIA"] --> EP1["GET /market/precio/{ticker}<br/>advertencia + operable=false"]
    MD --> EP2["GET /senales<br/>advertencia_precios"]
    EP1 --> F1["NewTradeForm<br/>aviso al usar 'precio de mercado'"]
    EP2 --> F2["/senales<br/>banner ámbar arriba de la tabla"]
```

`operable` pasa a `true` recién cuando la cotización salga de IOL (Fase 8).

### Tarea 3.5 — vencimiento por tiempo

Quinta regla del `PositionManager`: si a los `SALIDA_SWING_MAX_DIAS` (10 días
**corridos**) la posición no tocó ni el SL inicial ni el TP1, se cierra a
mercado. Ni gana ni pierde, pero inmoviliza capital y ocupa un cupo de
`MAX_POSICIONES`.

> [!note] Tres decisiones de diseño
> 1. **Va última dentro del caso "pre-TP1".** Si en el mismo tick el precio toca
>    el SL o el TP1, mandan esas reglas: son la estrategia real, el vencimiento
>    solo barre lo que quedó dormido.
> 2. **Una posición que ya cobró TP1 no vence.** A partir de ahí la gestiona el
>    trailing, que ya tiene piso garantizado en +3,5%.
> 3. **Sin `entry_date` la regla no aplica.** Preferimos no cerrar nada antes que
>    inventar una fecha de compra. La fecha sale de `trade.fecha_compra` en cada
>    barrido del monitor, no de `PositionState`: duplicarla daría dos fuentes de
>    verdad.

### Tarea 3.7 — señal alternativa por RSI

Módulo nuevo `app/rsi_signal.py`. RSI(14) por debajo de 30 dispara señal de
compra. **No reemplaza a los 7 filtros: conviven**, y cada candidato de
`/senales` sale marcado con su `origen`.

```mermaid
flowchart TD
    T[Ticker] --> N{Noticias FinBERT}
    N -- veto --> D[Descartado]
    N -- ok --> A[7 filtros + anti-chase]
    N -- ok --> B["RSI(14) < 30"]
    A --> J{¿alguna pasó?}
    B --> J
    J -- ninguna --> D2[Descartado con LOS DOS motivos]
    J -- solo A --> O1["origen = 7_FILTROS"]
    J -- solo B --> O2["origen = RSI"]
    J -- las dos --> O3["origen = AMBOS"]
```

| Decisión | Por qué |
|---|---|
| **Sin `pandas-ta`**, RSI con pandas puro | La librería arrastra `numba`, que no soporta Python 3.14: el `pip install` falla al compilar. El repo ya calcula ATR y EMAs a mano en `technical_filters.py`; son 6 líneas y cero dependencias nuevas. |
| Suavizado de **Wilder**, no media simple | Es el RSI clásico y el que usa `pandas-ta` por defecto. Con media simple los valores cruzan el umbral de 30 en ruedas distintas: no es cosmético. Hay un test que fija la elección. |
| El **anti-chase no se aplica** a la señal de RSI | Mide si el precio se escapó *hacia arriba* del nivel de ruptura; una señal de sobreventa es por definición lo contrario. Un ticker vetado por anti-chase todavía puede entrar por RSI. |
| Mismo stop/TP que los 7 filtros | Cambia el *disparador* de la señal, no la gestión del riesgo: ATR × 1,5, recortado a 3,0%, R/B 1:2. |
| El descarte acumula **los dos motivos** | Regla del repo: los motivos de veto no se pierden nunca. |

> [!warning] El filtro de liquidez todavía no bloquea
> La tarea pide descartar por spread bid/ask > 1,0%. No hay de dónde sacar el
> libro de órdenes del CEDEAR: `yfinance` da el subyacente en EE.UU. Sin puntas
> reales, `chequear_liquidez` devuelve "pasa" con `disponible=False`. La lógica
> está escrita y probada (5 tests); se vuelve bloqueante sola en cuanto
> `IOLClient` (Fase 8) le pase bid/ask.

### Tarea 11.2 — `EJECUCION_REAL_HABILITADA` → `MODO_FANTASMA`

Solo el rename: el resto de la 11.2 (position sizing contra saldo real, campo
`modo` en `Trade`) depende de IOL y sigue bloqueado.

> [!note] Por qué se hizo ahora y no con el resto de la Fase 11
> El plan es explícito: *"usar ese nombre para no tener dos variables haciendo lo
> mismo"*. La variable vieja ya existía en el código, con la lógica **invertida**
> (`EJECUCION_REAL_HABILITADA=false` == `MODO_FANTASMA=true`). Dos nombres para
> el mismo kill switch, con sentido opuesto, es la forma más fácil de habilitar
> la ejecución real sin querer.

La variable vieja **ya no se lee**. Si quedó en un `.env`, `config.py` emite un
`warning` en vez de ignorarla en silencio — y el default siempre falla del lado
seguro. Hay tres tests que lo fijan (`tests/test_config.py`).

### Fuera de alcance, y por qué

> [!todo] Tareas 5.3 / 5.4 / 5.5 — estrategia 13F: no se empezó
> El propio plan lo dice en el encabezado de la Fase 5: *"Evaluá si tiene sentido
> meterse en esto ahora: la parte de ingesta de 13F (Tarea 5.3) es más laboriosa
> de lo que parece a simple vista, está bien dejarla para más adelante"*. Además
> la 5.5 necesita el cupo de capital por estrategia, que es la Tarea 0.1 👤 y
> todavía no está definido. Son una estrategia completa e independiente, no un
> ajuste de lo que ya existe: conviene decidirlo explícitamente antes de empezar.

> [!warning] Tarea 8.4 — dólar CCL: bloqueada
> Necesita `IOLClient.get_valor_ccl()` (cotización de AL30 y AL30D), que depende
> de la Tarea 8.1 y de las credenciales de IOL (Tarea 0.2 👤).

### Corrección al propio plan

> [!note] Inconsistencia interna en `tareas-desarrollo.md`
> La Tarea 11.2 renombra el kill switch a `MODO_FANTASMA`, pero la Tarea 12.1
> seguía diciendo `EJECUCION_REAL_HABILITADA=true`. Se corrigió esa línea a
> `MODO_FANTASMA=false` para que el documento no se contradiga.

**Archivos tocados:** `backend/app/rsi_signal.py` (nuevo),
`backend/app/config.py`, `backend/app/market_data.py`,
`backend/app/position_manager.py`, `backend/app/signals.py`,
`backend/app/schemas.py`, `backend/app/main.py`, `backend/position_monitor_job.py`,
`backend/scanner_job.py`, `backend/requirements.txt`, `backend/.env.example`,
`backend/tests/test_rsi_signal.py` (nuevo), `backend/tests/test_config.py` (nuevo),
`backend/tests/test_position_manager.py`, `backend/tests/test_signals.py`,
`frontend/lib/types.ts`, `frontend/components/NewTradeForm.tsx`,
`frontend/app/senales/page.tsx`, `docs/parametros-riesgo.md`, `README.md`,
`tareas-desarrollo.md`, `PROGRESS.md`.

### Cómo se probó

```
$ ./venv/Scripts/python.exe -m pytest -q -m "not network"
283 passed, 8 deselected, 53 warnings in 9.11s
```

38 tests nuevos (24 de la señal RSI, 9 del vencimiento por tiempo, 5 de config).

> [!warning] Bug encontrado en los tests viejos
> `tests/test_signals.py` no mockeaba la fuente nueva, así que el escaneo salía
> a Yahoo de verdad en tests marcados como "sin red" (se vio el RSI real de KO en
> el mensaje de error). Se agregó el mock de `rsi_signal.evaluar_rsi` en el
> helper `_sin_red`.

Chequeo de tipos del frontend:

```
$ node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json
TSC: sin errores de tipos
```

**Escaneo real con las dos fuentes conviviendo:**

```
veto_global: None
advertencia: Referencia técnica, no operable: es el precio de la acción subyacente ...

TICKER   ORIGEN          RSI    ENTRADA         SL         TP
QQQ      7_FILTROS     54.07     718.96     706.57     743.73

DESCARTADOS (los dos motivos, nunca uno solo):
  AAPL  -> VETO RS: no supera a SPY en 30 ruedas (-4.95% vs 4.21%). | SIN SEÑAL RSI: AAPL en 53.24, no está sobrevendido (umbral 30).
  NVDA  -> VETO SEÑAL: señal vencida, precio extendido un 5.05% sobre la ruptura. | SIN SEÑAL RSI: NVDA en 60.63, no está sobrevendido.
  KO    -> VETO TÉCNICO: estructura no alcista (88.07 / 88.52 / 86.64). | SIN SEÑAL RSI: KO en 50.15, no está sobrevendido.
  GOOGL -> VETO TÉCNICO: estructura no alcista (338.46 / 343.15 / 347.33). | SIN SEÑAL RSI: GOOGL en 45.32, no está sobrevendido.
```

> [!note] Hoy no disparó ninguna señal por RSI
> Ningún ticker del universo está por debajo de 30. Se verificó contra 10
> tickers extra para confirmar que el cálculo corre sobre datos reales: PFE
> 63.34 · INTC 53.39 · NKE 40.45 · BA 43.44 · XOM 51.86 · T 61.57 · MRNA 63.22 ·
> **LULU 31.36** (el más cerca del umbral) · DIS 50.44 · WBA sin datos. El
> mecanismo funciona; el mercado no está dando sobreventa. Los 24 tests
> cubren el caso en que sí dispara.

Endpoint de precio con la advertencia:

```
$ GET /market/precio/AAPL
HTTP 200
ticker: AAPL | precio: 319.9700012207031 | operable: False
advertencia: Referencia técnica, no operable: es el precio de la acción subyacente en
EE.UU. (USD), no el del CEDEAR en BYMA (ARS). ...
```

![Página de señales con la columna Origen y el banner de precios de referencia](./docs/assets/senales-origen.png)

> [!todo] Falta la captura
> La columna **Origen** y el banner ámbar de precios ya están en
> `/senales`; la captura la tiene que sacar una persona con el frontend
> levantado y guardarla en `docs/assets/senales-origen.png`.

> [!note] Pendiente / notas
> `tareasdesarrollo.md` (el plan viejo, sin guion) sigue en el repo y ya quedó
> desactualizado. Conviene borrarlo para no tener dos planes conviviendo, pero no
> se tocó porque está versionado en git y esa decisión es tuya.

---

---

## 2026-09-07 — Tarea 0.1 cerrada + Fase 5 completa (Tareas 5.3, 5.4 y 5.5)

> [!summary] Qué se hizo
> Con la Tarea 0.1 👤 resuelta (capital, cupos por estrategia y límite por
> operación decididos), se construyó la **estrategia de consenso institucional
> 13F** completa: ingesta desde SEC EDGAR, tracker de consenso y su integración
> con cupo de capital propio y dashboard separado por estrategia.

### Decisiones de la Tarea 0.1

| Parámetro | Valor decidido | Nota |
|---|---|---|
| `CUPO_SWING` / `CUPO_SMART_MONEY` | 40% / 60% | El ejemplo que traía el plan |
| `LIMITE_POR_OPERACION` | 50% | **Excepción consciente**: el plan sugiere 10-20% |
| `SALDO_MINIMO_OPERAR` | $10.000 | Lo pedía la Tarea 11.2 |

> [!warning] Las dos primeras decisiones se contradecían entre sí
> 50% sobre el capital total son $50.000, pero el cupo de swing (40%) es
> $40.000: una sola posición se pasaría de su propio cupo. Es aritméticamente
> imposible.
>
> Se resolvió aplicando `LIMITE_POR_OPERACION` **sobre el cupo de cada
> estrategia**, que es la única lectura donde las tres decisiones se sostienen a
> la vez. Consecuencia práctica: la exposición máxima real por posición es 20%
> del capital total en swing y 30% en smart money, no 50%. Queda documentado en
> `docs/parametros-riesgo.md` y hay un test que lo fija
> (`test_una_posicion_nunca_se_pasa_del_cupo_de_su_estrategia`).

### Cómo se reparte el capital

```mermaid
flowchart TD
    C["CAPITAL_TOTAL<br/>$100.000"] --> S["Swing técnico · 40%<br/>$40.000"]
    C --> M["Smart Money 13F · 60%<br/>$60.000"]
    S -->|"LIMITE_POR_OPERACION 50%"| S1["$20.000 por posición<br/>× 2 = $40.000"]
    M -->|"LIMITE_POR_OPERACION 50%"| M1["$30.000 por posición"]
```

### Tarea 5.3 — Ingesta de filings 13F

`backend/app/edgar_13f.py`. Baja los dos últimos 13F-HR de cada fondo, los
compara y devuelve qué se movió.

```mermaid
flowchart LR
    A["data.sec.gov/submissions"] -->|últimos dos 13F-HR| B[accession numbers]
    B --> C["Archives/.../index.json"]
    C -->|el .xml que no es primary_doc| D[information table]
    D --> E[agregar por CUSIP]
    E --> F["normalizar escala"]
    F --> G["mapear CUSIP → ticker"]
    G --> H["comparar vs trimestre anterior"]
```

> [!note] Mapeo CUSIP → ticker, verificado contra datos reales
> Los 13F identifican por CUSIP y no hay fuente pública gratuita de CUSIP→ticker
> (el mapeo oficial es un producto pago). Se usó un mapeo manual acotado al
> universo, como sugiere la propia tarea. Las 11 CUSIPs resolvieron correctamente
> contra los filings reales: el nombre del emisor que trae cada filing coincide
> con el ticker (`037833100` → APPLE INC, `191216100` → COCA COLA CO, etc.).

### Dos bugs que solo aparecieron con datos reales

> [!warning] 1. Una misma CUSIP aparece varias veces por filing
> Una fila por manager con discreción sobre esa tenencia. Sin agregar, Berkshire
> "tiene" tres posiciones chicas de Ally en vez de una grande, y todos los pesos
> en cartera salen mal.

> [!warning] 2. Hay fondos que declaran `value` en miles, no en dólares
> La SEC pide dólares desde 2023-01-03, pero **Baupost sigue presentando en
> miles**. Se detectó porque la primera corrida devolvió AMZN a **$0,24** y GOOG
> a **$0,35** — factor 1000. El peso en cartera no lo nota (es un cociente dentro
> del mismo filing), pero el precio promedio queda 1000× abajo, y es justo lo que
> alimenta el filtro anti-persecución de la 5.4.
>
> Se normaliza cada filing solo, con la **mediana** del precio implícito (no una
> posición suelta, para que una tenencia rara no arrastre la decisión) y
> descartando las filas `PRN`, que son deuda y su "precio" es por dólar de
> nominal. Verificación cruzada: tras el fix, Baupost reporta AMZN a $238,34 —
> exactamente lo mismo que los otros cuatro fondos para el mismo trimestre.

### Tarea 5.4 — Tracker de consenso

`backend/app/wallstreet_tracker.py`.

| Regla | Valor | Por qué |
|---|---|---|
| Consenso mínimo | 2 fondos | Seguir a uno es seguir a una persona |
| Peso mínimo en la cartera del fondo | 1,0% | Por debajo es ruido, no convicción |
| Suba máxima desde el filing | +10% | Los 13F llegan con hasta 45 días de rezago |

> [!note] Asimetría deliberada entre entrar y salir
> Para **comprar** hacen falta 2 fondos. Para **vender** alcanza con uno que
> reduzca o cierre. El costo de salir antes de tiempo es perderse una suba; el de
> quedarse, una caída con la tesis ya rota.

El precio de referencia de los fondos es un **promedio ponderado por valor**, no
simple: un fondo que puso $10.000M pesa más que uno que puso $50M.

### Tarea 5.5 — Integración con capital propio

- Endpoint `GET /senales/smart-money`.
- Campo `estrategia` en el modelo `Trade`, con selector en el formulario de alta.
- Dashboard con una fila por estrategia (cupo, invertido, resultado, acierto,
  abiertas), además del total general que no cambió.

> [!warning] `create_all` no migra tablas que ya existen
> `simulador.db` ya tenía operaciones cargadas, así que la columna nueva no
> aparecía sola. Se agregó `backend/app/migrations.py` con un `ALTER TABLE`
> idempotente que corre al levantar la app. No se trajo Alembic: para un ALTER de
> una línea sobre SQLite sería más máquina de la que el problema pide.
>
> Las operaciones que ya estaban quedan como `SWING`, que es la única estrategia
> que existía cuando se registraron.

### Refactor de paso

Las tres fuentes de señal calculaban el stop y el objetivo con la misma fórmula
copiada. Se extrajo `technical_filters.calcular_stop_y_objetivo`, que ahora usan
las tres: cambia el *disparador* de cada señal, nunca la gestión del riesgo.
`calculations.py` no se tocó — eso es comisiones.

**Archivos tocados:** `backend/app/edgar_13f.py` (nuevo),
`backend/app/wallstreet_tracker.py` (nuevo), `backend/app/migrations.py` (nuevo),
`backend/app/config.py`, `backend/app/models.py`, `backend/app/schemas.py`,
`backend/app/crud.py`, `backend/app/main.py`, `backend/app/technical_filters.py`,
`backend/app/rsi_signal.py`, `backend/.env.example`,
`backend/tests/test_edgar_13f.py` (nuevo), `backend/tests/test_wallstreet_tracker.py` (nuevo),
`backend/tests/test_estrategias.py` (nuevo), `frontend/lib/types.ts`,
`frontend/lib/api.ts`, `frontend/app/page.tsx`, `frontend/components/NewTradeForm.tsx`,
`docs/parametros-riesgo.md`, `README.md`, `.gitignore`, `PROGRESS.md`.

### Cómo se probó

```
$ ./venv/Scripts/python.exe -m pytest -q -m "not network"
336 passed, 8 deselected, 55 warnings in 8.71s
```

53 tests nuevos (19 de la ingesta 13F, 19 del tracker, 15 del desglose por
estrategia y la migración). Ninguno le pega a SEC EDGAR: los filings se arman a
mano como XML sintético.

```
$ node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json
TSC: sin errores de tipos
```

**Corrida real contra los 5 fondos** (trimestre 2026-06-30 vs 2026-03-31):

```
FONDO                      POSICIONES   DEL UNIVERSO
Berkshire Hathaway                 29              4
Bridgewater Associates            997             10
Renaissance Technologies         3140             11
Tiger Global Management            46              5
Baupost Group                      23              2
```

**Endpoint `/senales/smart-money`:**

```
HTTP 200
estrategia=SMART_MONEY | cupo=$60,000 | por posición=$30,000
fondos leídos: 5 | errores: ninguno

COMPRAS:
  GOOGL  consenso=2 ['Berkshire Hathaway', 'Renaissance Technologies']
         entrada=$338.46 px_fondos=$357.37 delta=-5.29% SL=328.56 TP=358.25

descartados: 10 | ventas: 0
```

> [!note] Hubo consenso real este trimestre
> GOOGL: Berkshire y Renaissance **aumentaron** posición, y el precio hoy está
> **5,29% por debajo** del promedio al que entraron — pasa el filtro
> anti-persecución. Los otros 10 tickers se descartaron con motivo: 9 por falta
> de consenso y GOOG por no tener CEDEAR habilitado.

**Dashboard separado por estrategia:**

```
SWING        cupo=$   40,000  neto=$   957.89  cerradas=1  abiertas=0
SMART_MONEY  cupo=$   60,000  neto=$     0.00  cerradas=0  abiertas=0
```

![Dashboard con las dos estrategias diferenciadas](./docs/assets/dashboard-estrategias.png)

> [!todo] Falta la captura
> La tabla "Por estrategia" ya está en el Dashboard; la captura que pide el
> "Testing esperado" de la Tarea 5.5 la tiene que sacar una persona con el
> frontend levantado, y guardarla en `docs/assets/dashboard-estrategias.png`.

> [!warning] Pendiente / notas
> Hay dos archivos de clave SSH sin versionar en la raíz del repo
> (`ssh-key-2026-09-06.key` y `.key.pub`) que **no están en `.gitignore`**. No se
> tocaron, pero conviene moverlos fuera del repo o ignorarlos antes del próximo
> commit: una clave privada commiteada es muy difícil de sacar después.

---

## 2026-09-07 — Tarea 8.3 — Endurecer manejo de credenciales

> [!note] Resumen
> Checkpoint de seguridad antes de seguir construyendo sobre `broker_iol.py`.
> Ninguna credencial real aparece en el historial de git, en el working tree ni
> en una respuesta de la API. Se encontró **una filtración real**: el
> `TELEGRAM_BOT_TOKEN` salía por log y por HTTP cuando fallaba la red, porque la
> API de Telegram lo lleva dentro de la URL. Se arregló en `notifications.py`.
> Además se blindó el `.gitignore` contra claves privadas: las dos claves SSH de
> la raíz ya no las levanta un `git add .`.

**Qué se hizo:** auditoría de exposición de secretos (historial completo de git,
working tree, logs, mensajes de excepción y respuestas de endpoints); se redactó
el token de Telegram en todo texto derivado de una excepción o de un cuerpo de
error; se agregaron patrones de clave privada y de `.env` al `.gitignore`; se
documentó en `README.md` cómo cargar las credenciales al desplegar en el VPS.

**Archivos tocados:**

| Archivo | Cambio |
|---|---|
| `.gitignore` | Patrones nuevos de claves privadas (`*.key`, `*.pem`, `id_rsa*`, `ssh-key-*`, …) y de `.env` en cualquier carpeta, con `!**/.env.example` para que la plantilla siga versionada |
| `backend/app/notifications.py` | `_redactar()` + `MARCA_REDACTADO`; se aplica al `motivo` del error de red y a `_detalle_error()` |
| `backend/tests/test_notifications.py` | 4 tests nuevos de no-filtración (error de red, cuerpo de error, `chat_id`, sin credenciales) |
| `README.md` | Tabla de variables de entorno ampliada (columna "Es secreto", `IOL_API_URL`); sección nueva "Cargar las credenciales al desplegar (VPS)"; 2 filas nuevas en "Notas de seguridad" |

> [!warning] Hallazgo 1 (ARREGLADO) — el `TELEGRAM_BOT_TOKEN` se filtraba por log y por HTTP
> La API de Telegram no tiene header de autenticación: el token **es parte de la
> ruta** (`/bot<TOKEN>/sendMessage`). `requests` mete la URL completa en el texto
> de sus excepciones de red, y ese texto entraba tal cual en el `motivo` que
> `send_telegram` loguea y devuelve — y `POST /notificaciones/test` devuelve ese
> `motivo` al cliente HTTP.
>
> Verificado antes del arreglo con `requests` real contra un host inexistente:
>
> ```
> TIPO: ConnectionError
> MENSAJE: HTTPSConnectionPool(host='no-existe-este-host-xyz.invalid', port=443): Max retries exceeded with url: /bot8123456789:AAH-TOKEN-SECRETO-DE-PRUEBA/sendMessage (Caused by NameResolutionError(...))
> ¿FILTRA EL TOKEN?: True
> ```

```mermaid
flowchart LR
    EXC["requests lanza<br/>ConnectionError con<br/>/bot TOKEN /sendMessage"] --> RED["_redactar()<br/>(nuevo, Tarea 8.3)"]
    RED --> MOT["motivo"]
    MOT --> LOG["logger.warning"]
    MOT --> HTTP["respuesta de<br/>POST /notificaciones/test"]
    RED -.antes no existía:<br/>el token llegaba entero.-> FUGA["FUGA"]
```

> [!warning] Hallazgo 2 (ARREGLADO) — claves SSH sin ignorar en la raíz
> `ssh-key-2026-09-06.key` (una **clave privada RSA sin cifrar**, confirmado por
> su encabezado `-----BEGIN RSA PRIVATE KEY-----`) y `ssh-key-2026-09-06.key.pub`
> estaban sin versionar y **sin ignorar**: un `git add .` los commiteaba. Se
> agregaron los patrones al `.gitignore`. **Los archivos no se tocaron** — son
> del usuario, que está levantando el VPS.

> [!todo] Pendiente para el usuario — mover las claves SSH fuera del repo
> Ignorarlas evita el commit accidental, pero el lugar correcto de una clave
> privada es `~/.ssh/` con `chmod 600`, no la raíz de un repo que se clona y se
> comparte.

> [!warning] Hallazgo 3 (DELEGADO — no se tocó) — `frontend/.env.local` está trackeado
> `git ls-files` lo lista. Hoy su contenido no es secreto
> (`NEXT_PUBLIC_API_URL=http://127.0.0.1:8123`, y todo `NEXT_PUBLIC_*` es público
> por diseño en Next.js), así que **no hay filtración**. El riesgo es a futuro: si
> alguien agrega una clave ahí, se commitea sola, porque `.gitignore` no aplica a
> archivos ya trackeados. Sacarlo del índice requiere `git rm --cached
> frontend/.env.local` + commit, y esta tarea no hace commits ni toca el frontend.

### Cómo se probó

#### 1. `.env` fuera de git

```
$ git ls-files backend/.env
(vacío)

$ git check-ignore -v backend/.env
.gitignore:19:backend/.env	backend/.env
```

#### 2. Historial completo de git — el testing que pide el plan

```
$ git log --all -p | grep -i "iol_password"
+| `IOL_USERNAME` / `IOL_PASSWORD` | API de InvertirOnline | Solo desde la Fase 8 |
+IOL_PASSWORD=
+IOL_PASSWORD = os.getenv("IOL_PASSWORD", "")
+IOL_PASSWORD = os.getenv("IOL_PASSWORD", "tu_password_iol")
+from config_bonds import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, UNIVERSO_BONOS, MONTO_POR_POSICION
+        payload = {"username": IOL_USERNAME, "password": IOL_PASSWORD, "grant_type": "password"}
+IOL_PASSWORD = os.getenv("IOL_PASSWORD", "tu_password_iol")
+from config import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL
+            "password": IOL_PASSWORD,
+IOL_PASSWORD = os.getenv("IOL_PASSWORD", "tu_password_iol")
+from config_bonds import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, UNIVERSO_BONOS, MONTO_POR_POSICION
+        payload = {"username": IOL_USERNAME, "password": IOL_PASSWORD, "grant_type": "password"}
+IOL_PASSWORD = os.getenv("IOL_PASSWORD", "tu_password_iol")
+from config import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL
+            "password": IOL_PASSWORD,
+- Credenciales desde variables de entorno (`IOL_USERNAME`, `IOL_PASSWORD`),
+`git log --all -p | grep -i "iol_password"` (debe estar vacía).
```

> [!note] Por qué la salida no está vacía y aun así está bien
> El plan esperaba una salida vacía. Lo que hay son **el nombre de la variable y
> placeholders**, ningún valor: `os.getenv("IOL_PASSWORD", "")` en
> `backend/app/config.py`, `IOL_PASSWORD=` (sin valor) en `backend/.env.example`,
> y `"tu_password_iol"` en los `docs/specs-txt/*.txt`, que son el texto plano de
> los manuales `.docx`. Ninguna es una credencial. La verificación que importa —
> los valores reales del `.env` — está en el punto 3.

```
$ git log --all -p | grep -i "iol_username"
+| `IOL_USERNAME` / `IOL_PASSWORD` | API de InvertirOnline | Solo desde la Fase 8 |
+IOL_USERNAME=
+IOL_USERNAME = os.getenv("IOL_USERNAME", "")
+IOL_USERNAME = os.getenv("IOL_USERNAME", "tu_usuario@correo.com")
+from config_bonds import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, UNIVERSO_BONOS, MONTO_POR_POSICION
+        payload = {"username": IOL_USERNAME, "password": IOL_PASSWORD, "grant_type": "password"}
+IOL_USERNAME = os.getenv("IOL_USERNAME", "tu_usuario@correo.com")
+from config import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL
+            "username": IOL_USERNAME,
+IOL_USERNAME = os.getenv("IOL_USERNAME", "tu_usuario@correo.com")
+from config_bonds import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, UNIVERSO_BONOS, MONTO_POR_POSICION
+        payload = {"username": IOL_USERNAME, "password": IOL_PASSWORD, "grant_type": "password"}
+IOL_USERNAME = os.getenv("IOL_USERNAME", "tu_usuario@correo.com")
+from config import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL
+            "username": IOL_USERNAME,
+- Credenciales desde variables de entorno (`IOL_USERNAME`, `IOL_PASSWORD`),

$ git log --all -p | grep -i "access_token"
+            self.token = data["access_token"]
+            self.token = data["access_token"]
+            self.token = data["access_token"]
+            self.token = data["access_token"]

$ git log --all -p | grep -i "refresh_token"
(vacío — exit 1)

$ git log --all -p | grep -i "telegram_bot_token"
+| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Alertas | Solo desde la Fase 7 |
+TELEGRAM_BOT_TOKEN=
+TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
+TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "123456789:ABCDEF_tu_token")
+from config_bonds import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, UNIVERSO_BONOS, MONTO_POR_POSICION
+        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
+TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "123456789:ABCDEF_tu_token_aqui")
+from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TICKERS_BYMA, MONTO_POR_POSICION
+    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
+TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "123456789:ABCDEF_tu_token")
+from config_bonds import IOL_USERNAME, IOL_PASSWORD, IOL_API_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, UNIVERSO_BONOS, MONTO_POR_POSICION
+        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
+TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "123456789:ABCDEF_tu_token_aqui")
+from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TICKERS_BYMA, MONTO_POR_POSICION
+    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
+**Objetivo:** Tener un `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` listos para
+  usando `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` desde variables de
```

#### 3. Los valores REALES del `.env` — la verificación que importa

Script que lee cada valor de `backend/.env` y lo busca literalmente en el
historial completo, en `HEAD` y en el working tree. Nunca imprime el valor, solo
cuántas veces aparece:

```
commits en historial: 1
archivos trackeados:  88

TELEGRAM_BOT_TOKEN : historial_git=0 | HEAD=[ninguno] | working_tree=[ninguno]
TELEGRAM_CHAT_ID   : historial_git=0 | HEAD=[ninguno] | working_tree=[ninguno]
IOL_USERNAME       : historial_git=0 | HEAD=[ninguno] | working_tree=[ninguno]
IOL_PASSWORD       : historial_git=0 | HEAD=[ninguno] | working_tree=[ninguno]
MODO_FANTASMA      : historial_git=531 | HEAD=[PROGRESS.md, config.py, ...] | working_tree=[...]
```

> [!note] `MODO_FANTASMA` no es un falso positivo preocupante
> Su valor es `true`, así que la búsqueda literal matchea en cualquier archivo
> que contenga esa palabra. No es un secreto: es el kill switch.

Segunda pasada, esta vez **sin excluir nada** — incluyendo `.git/` entero,
`backend/venv/`, `frontend/node_modules/` y el propio `backend/.env`:

```
TELEGRAM_BOT_TOKEN : ocurrencias_en_historial_git=0  archivos_working_tree=[./backend/.env ]
TELEGRAM_CHAT_ID   : ocurrencias_en_historial_git=0  archivos_working_tree=[./backend/.env ]
IOL_USERNAME       : ocurrencias_en_historial_git=0  archivos_working_tree=[./backend/.env ]
IOL_PASSWORD       : ocurrencias_en_historial_git=0  archivos_working_tree=[./backend/.env ]
```

Cada credencial real existe en **exactamente un archivo**: `backend/.env`, que
está ignorado y sin trackear. Ni siquiera aparece dentro de `.git/`.

#### 4. `.env.example` completo y sin valores reales

```
$ cat backend/.env.example | grep -E "^[A-Z_]+=" | head
IOL_USERNAME=
IOL_PASSWORD=
IOL_API_URL=https://api.invertironline.com
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
CAPITAL_TOTAL=100000
...
```

Las 5 claves que hay cargadas en `backend/.env` (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `IOL_USERNAME`, `IOL_PASSWORD`, `MODO_FANTASMA`) están todas
en el `.example`, vacías. Las credenciales de IOL están cargadas y verificadas
contra la API real (Tareas 8.1 y 8.2).

#### 5. El `.gitignore` nuevo bloquea las claves

```
$ git check-ignore -v ssh-key-2026-09-06.key
.gitignore:39:ssh-key-*	ssh-key-2026-09-06.key
$ git check-ignore -v ssh-key-2026-09-06.key.pub
.gitignore:39:ssh-key-*	ssh-key-2026-09-06.key.pub
$ git check-ignore -v id_rsa
.gitignore:34:id_rsa*	id_rsa
$ git check-ignore -v cert.pem
.gitignore:26:*.pem	cert.pem
$ git check-ignore -v xxx/.env.local
.gitignore:16:**/.env.*	xxx/.env.local
$ git check-ignore -v xxx/.env.example
.gitignore:18:!**/.env.example	xxx/.env.example      (negado = SÍ se versiona)

$ git add --dry-run . | grep -iE "ssh-key|\.key"
(vacío — las claves ya no entran en un `git add .`)

$ git ls-files | git check-ignore --stdin -v
(vacío — ningún archivo ya trackeado quedó ignorado por los patrones nuevos)
```

#### 6. Suite completa

```
$ cd backend && ./venv/Scripts/python.exe -m pytest -q -m "not network"
394 passed, 8 deselected, 69 warnings in 8.89s
```

### Auditoría de código — qué se revisó y qué se encontró

| Superficie | Resultado |
|---|---|
| `backend/app/broker_iol.py` | **Limpio.** No loguea token ni contraseña; el usuario sale ofuscado (`_usuario_ofuscado`), el `__repr__` solo dice "autenticado / sin token", y `_detalle_error` recorta el cuerpo a 300 chars. La contraseña viaja en el body del POST, no en la URL, así que la excepción de `requests` no la incluye |
| `backend/app/notifications.py` | **Filtraba el token** (Hallazgo 1). Arreglado |
| `backend/app/config.py` | Limpio. Todo `os.getenv(...)` con default vacío, sin credenciales hardcodeadas |
| `backend/app/main.py` (solo lectura) | Ningún endpoint devuelve credenciales. `/iol/saldo` y `/mercado/ccl` propagan `str(exc)` de `IOLError`, que trae la URL de la API pero ningún secreto |
| `print()` en el backend | Solo en `seed.py` (mensajes de siembra), ninguno con secretos |
| `logger.*` en jobs y módulos nuevos (`scanner_job`, `weekly_report`, `edgar_13f`, `wallstreet_tracker`, `rsi_signal`, `migrations`, `position_monitor_job`) | Ninguno toca credenciales. Los que loguean `resultado["motivo"]` de Telegram ahora reciben el texto ya redactado |
| Patrones de secreto en el working tree (`BEGIN * PRIVATE KEY`, `AKIA…`, `xox…`, `sk-…`, `ghp_…`) | Sin coincidencias fuera de `backend/venv/` (código de librerías) |

**Pendiente / notas:**

> [!todo] Para el usuario
> 1. Mover `ssh-key-2026-09-06.key` y `.key.pub` a `~/.ssh/` con `chmod 600`. Ya
>    están ignoradas, pero no deberían vivir en el repo.
> 2. Decidir qué hacer con `frontend/.env.local`, que está trackeado (Hallazgo 3).
>    Hoy no filtra nada; el riesgo es que mañana alguien le meta una clave.

> [!warning] Lo que NO se pudo verificar
> - No se probó `send_telegram` contra la API real de Telegram: la redacción se
>   verificó con `requests.post` mockeado (4 tests nuevos) y con una prueba
>   aparte de que `requests` sí incluye la URL en el texto de sus excepciones.
> - No se auditó el historial de un remoto: el repo tiene **un solo commit local**
>   (`2aab1d5 base`) y `git log --all` cubre todas las refs que existen acá. Si el
>   repo se publicó en algún lado antes, eso no se puede ver desde la máquina.
> - No se tocaron `main.py`, `schemas.py`, `broker_iol.py`, `bond_signals.py` ni
>   el frontend (hay trabajo en paralelo sobre ellos). Se revisaron en modo
>   lectura y no se encontró nada que arreglar en ellos, salvo el Hallazgo 3.
> - No se hizo ningún commit de git, por indicación explícita de la tarea.

---

---

---

## 2026-09-07 — Tareas 8.1, 8.2 y 8.4 — Conexión real con InvertirOnline

> [!summary] Qué se hizo
> Con las credenciales de IOL ya cargadas, se construyó `IOLClient` y las dos
> lecturas que colgaban de él: saldo/tenencia real y dólar CCL. **El login contra
> la cuenta real funciona** — es el criterio de aceptación de la Tarea 8.1.
> Todo es de solo lectura: no se envía ninguna orden.

### Tarea 8.1 — `IOLClient`

`backend/app/broker_iol.py`. Autenticación OAuth2 y mantenimiento del token.

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

| Manual (sección 7) | Acá | Por qué |
|---|---|---|
| `login()` dentro de `__init__` | Login perezoso, en el primer uso | Instanciar no puede pegarle a la red: rompería importar el módulo, los tests y el arranque del backend si IOL está caído |
| Ignora el `refresh_token` | Lo usa, y cae a la contraseña si falla | Mandar la contraseña en cada renovación es peor: el refresh existe justo para no hacerlo |
| Solo maneja el vencimiento por tiempo | Además reintenta **una vez** ante un `401` | Lo pide el plan actualizado. Un patrón de 401 repetidos es la forma más común de que el bot quede ciego sin que nadie lo note |
| `print("Autenticación exitosa")` | `logger.info` con el usuario ofuscado, y **nunca** el token ni la contraseña | Tarea 8.3 |

### Rutas de la API: verificadas, no copiadas

> [!note] El plan avisaba que las fuentes no coinciden
> La Tarea 11.1 advierte que los manuales y el chat de Gemini difieren en algunas
> rutas de IOL. En vez de elegir una y confiar, se probaron contra la API real
> antes de escribir el código que las usa:

| Ruta | HTTP | Qué devuelve |
|---|---|---|
| `POST /token` | 200 | `access_token`, `refresh_token`, `expires_in` |
| `GET /api/v2/estadocuenta` | 200 | `cuentas[]` con `disponible`, `titulosValorizados`, `total` |
| `GET /api/v2/portafolio/argentina` | 200 | `activos[]` con `titulo.simbolo`, `ppc`, `ultimoPrecio`, `valorizado` |
| `GET /api/v2/bCBA/Titulos/{simbolo}/Cotizacion` | 200 | `ultimoPrecio`, `moneda`, `puntas`, `lote` |

> [!warning] Fuera del horario de rueda, `puntas` viene vacío
> Verificado contra la API: la cotización trae `"puntas": []` con el mercado
> cerrado. Por eso `get_puntas()` devuelve **`None`** en vez de `(0, 0)`: un
> spread calculado sobre ceros sería peor que no tener el dato. Los filtros de
> liquidez ya saben degradar cuando falta.

### Tarea 8.2 — Saldo y tenencia real

`GET /iol/saldo` + una sección nueva en el Dashboard, con **borde ámbar y la
leyenda "Cuenta real — IOL"**, separada del bloque de paper trading por un
divisor y su propio título.

> [!note] Por qué se piden aparte del dashboard
> El saldo real y el dashboard se consultan en llamadas separadas, con su propio
> estado de error. Si IOL está caído, el paper trading se sigue viendo igual: era
> lo que ya funcionaba antes de existir esta integración y no tiene por qué
> depender de ella.

El error de IOL sale como **503**, no 500: el problema es el servicio de arriba,
no este backend.

### Tarea 8.4 — Dólar CCL

`GET /mercado/ccl`. Se calcula con el mismo bono cotizando en las dos monedas:
`AL30` en pesos sobre `AL30D` en dólares. Se muestra en el encabezado de la
sección de cuenta real.

> [!note] Es contexto, no un filtro
> No veta nada, tal cual pide el alcance de la tarea: los manuales lo mencionan
> como variable macro a monitorear. Convertirlo en veto ante una brecha alta es
> una tarea aparte, a decidir con datos reales primero.

### Confirmación de la advertencia de la Tarea 2.1

Con las dos fuentes disponibles al mismo tiempo quedó a la vista el problema que
la Tarea 2.1 documentaba:

| Fuente | AAPL |
|---|---|
| yfinance (acción en EE.UU.) | **US$ 319,97** |
| IOL (CEDEAR en BYMA) | **$ 25.400 ARS** |

Son instrumentos distintos con números distintos. El precio de yfinance sigue
sirviendo para el patrón técnico y **no** para calcular cantidades.

**Archivos tocados:** `backend/app/broker_iol.py` (nuevo),
`backend/app/main.py`, `backend/app/schemas.py`,
`backend/tests/test_broker_iol.py` (nuevo), `frontend/app/page.tsx`,
`frontend/lib/types.ts`, `frontend/lib/api.ts`, `PROGRESS.md`.

### Cómo se probó

**Login real contra la cuenta (criterio de aceptación de la 8.1):**

```
$ python -c "from app.broker_iol import IOLClient; c = IOLClient(); c.login()"
INFO    Autenticación exitosa en IOL (usuario ma***@gmail.com).
configurado: True | token antes del login: False
token vigente: True
repr: IOLClient(usuario=ma***@gmail.com, autenticado)
header Authorization empieza con: Bearer eyJhbGc...
hay refresh_token: True
```

**Endpoints contra datos reales:**

```
GET /iol/saldo   -> 200 | disponible: 539.36 | posiciones: 11
   primera: AL29 82.0 ganancia 2.8 %
GET /mercado/ccl -> 200 | {'ccl': 1525.39, 'bono_pesos': 'AL30', 'precio_pesos': 85300.0,
                           'bono_dolares': 'AL30D', 'precio_dolares': 55.92,
                           'fecha_hora': '2026-09-04T17:00:06.943'}
```

**Suite completa, sin red:**

```
$ ./venv/Scripts/python.exe -m pytest -q -m "not network"
367 passed, 8 deselected, 69 warnings in 8.75s
```

31 tests nuevos, **ninguno le pega a IOL**: `requests` está mockeado en todos.
Cuatro de ellos son específicamente de no filtrar secretos (usuario ofuscado en
logs, contraseña ausente de errores y de `caplog`, token ausente del `repr`).

**Chequeo de tipos del frontend:**

```
$ node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json
TSC: sin errores de tipos
```

![Dashboard con la sección de cuenta real de IOL y el CCL](./docs/assets/dashboard-iol.png)

> [!todo] Falta la captura
> El "Testing esperado" de la Tarea 8.2 pide una captura del dashboard con el
> saldo real **y** una de la app de IOL confirmando que coincide. Las dos las
> tiene que sacar una persona. Guardar la del dashboard en
> `docs/assets/dashboard-iol.png`.

> [!warning] Pendiente / notas
> Ahora que hay cotización real en pesos, hay dos cosas que **quedaron sin
> conectar a propósito**, porque cambian comportamiento existente y conviene
> decidirlas explícitamente:
>
> 1. **`/market/precio/{ticker}` sigue usando yfinance.** Podría usar IOL y pasar
>    a `operable=true`, pero el histórico para ATR/EMAs/RSI **tiene que seguir**
>    saliendo de yfinance (IOL no da 60 ruedas de OHLCV). Mezclar las dos fuentes
>    sin pensarlo daría un stop calculado sobre una escala y un precio sobre otra.
> 2. **`rsi_signal.chequear_liquidez` sigue sin bid/ask.** Ya se le puede pasar
>    `get_puntas()`, pero fuera de rueda devuelve `None` igual, así que activarlo
>    solo cambia algo en horario de mercado.

---

## 2026-09-07 — Tarea 9.4 (módulo) — Escaneo de señales de bonos

> [!note] Resumen
> Se creó `backend/app/bond_signals.py`, el orquestador de señales de renta fija:
> el equivalente de `signals.py` para bonos, pero con el **precio real de BYMA**
> traído de InvertirOnline vía `IOLClient` en vez del subyacente en USD de Yahoo.
> Esta entrada cubre **solo el módulo**; el endpoint HTTP `GET /senales/bonos` y
> la pestaña del frontend se documentan aparte.

### Orden de chequeos

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

### Decisiones de diseño

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| Las puntas se leen de la cotización ya traída | `IOLClient.get_puntas()` | Ese método vuelve a pedir la cotización entera: serían 2 llamadas HTTP por bono y el spread podría quedar de un snapshot distinto al del último precio |
| Login único antes del bucle (`get_headers()`) | Dejar que falle bono por bono | Con IOL caído saldrían 9 descartes con el mismo error; así sale un `veto_global` con el motivo |
| Veto de corte de cupón adelantado, antes de la red | Confiar solo en `evaluate_bond_filters` | Es calendario puro: descarta sin gastar una llamada a FinBERT ni a IOL. `fixed_income_filters` lo revalida y sigue siendo la fuente de verdad |
| Cada descartado lleva `etapa` además de `motivo` | Solo `motivo` | Permite auditar en qué filtro se cayó cada bono sin parsear el texto |

> [!warning] El spread degrada, no bloquea
> Verificado contra la API real: fuera del horario de rueda IOL devuelve
> `"puntas": []`. En ese caso el candidato sale con `spread_disponible=false` y
> una nota, igual que hace `rsi_signal.chequear_liquidez`. Inventar un spread o
> vetar el universo entero serían las dos peores salidas.

### Firma de entrada

```python
escanear_senales_bonos(
    bonos: list[str] | None = None,      # default: config.UNIVERSO_BONOS
    cliente: IOLClient | None = None,    # default: broker_iol.get_client()
    ahora: datetime | None = None,       # default: ahora — para el calendario de cupón
) -> dict
```

**Qué se hizo:** módulo nuevo `bond_signals.py` con el escaneo completo de renta
fija (cupón → noticias → cotización real de IOL → spread → filtros
institucionales → contexto), más su batería de tests sin red.
**Archivos tocados:** `backend/app/bond_signals.py` (nuevo),
`backend/tests/test_bond_signals.py` (nuevo), `PROGRESS.md`.

**Cómo se probó:**

```
$ ./venv/Scripts/python.exe -m pytest tests/test_bond_signals.py -q
.......................                                                  [100%]
23 passed in 0.77s

$ ./venv/Scripts/python.exe -m pytest -q -m "not network"
........................................................................ [ 91%]
..................................                                       [100%]
394 passed, 8 deselected, 69 warnings in 9.18s
```

Corrida real contra la API de IOL (solo lectura, domingo 2026-09-07, mercado
cerrado): **9 candidatos de 9 bonos, 0 descartados**, con precios reales en
pesos de BYMA y FinBERT activo.

```
"iol": {"configurado": true, "disponible": true, "motivo": "Sesión de InvertirOnline activa"}
AL30  SOBERANO    85300.0 peso_Argentino  spread_disp=False  sent=0.3594
GD30  SOBERANO    88510.0 peso_Argentino  spread_disp=False  sent=0.4033
AL35  SOBERANO   116500.0 peso_Argentino  spread_disp=False  sent=0.3096
GD35  SOBERANO   121900.0 peso_Argentino  spread_disp=False  sent=0.3497
AE38  SOBERANO   120330.0 peso_Argentino  spread_disp=False  sent=0.1945
BA37D PROVINCIAL 109500.0 peso_Argentino  spread_disp=False  sent=0.1615
CO26  PROVINCIAL   5725.0 peso_Argentino  spread_disp=False  sent=0.2344
NDT25 PROVINCIAL  98310.0 peso_Argentino  spread_disp=False  sent=0.2971
PMM29 PROVINCIAL  73600.0 peso_Argentino  spread_disp=False  sent=0.4238
```

Todos salieron con `datos_limitados: true`: Yahoo Finance no tiene serie para
ningún `<BONO>.BA` del universo, así que el stop va al tope estricto de
`config.STOP_LOSS_MAX_PCT` (3,0%) y no se evalúan EMA20 ni ATR. Es el modo
degradado previsto en `fixed_income_filters`, no una falla.

> [!done] `es_acumulacion` venía en `true` sin ser acumulación — CORREGIDO
> `smart_money.check_bond_unusual_volume` devuelve `(True, 1.0)` cuando **no hay
> datos**, con el sentido de "neutro, seguí adelante", y `contexto_smart_money`
> mapeaba ese `True` a `es_acumulacion`. Como los bonos nunca tienen histórico en
> Yahoo, el campo salía siempre en `true` con `rvol = 1.0`: un dato falso.
>
> Corregido en `smart_money.contexto_smart_money`: `es_acumulacion` ahora se
> deriva del RVOL contra `RVOL_ACUMULACION_BONOS`, que sin datos da `False`.
> "No sé" se informa como "no", no como "sí". Dos tests de regresión en
> `tests/test_smart_money.py`.

### Integración (completada el mismo día)

| Pieza | Dónde |
|---|---|
| Endpoint `GET /senales/bonos` | `backend/app/main.py` |
| Schemas `SenalBono`, `BonoDescartado`, `EstadoIOL`, `SenalesBonosOut` | `backend/app/schemas.py` |
| Pestaña "Bonos" con su tabla y sus descartados | `frontend/app/senales/page.tsx` |
| `ESCANEO_BONOS_HABILITADO = True` + `_ciclo_bonos()` | `backend/scanner_job.py` |

> [!warning] Los tests del scanner salían a la red sin darse cuenta
> Al sumar el barrido de bonos a `ciclo_senales`, `tests/test_scanner_job.py`
> empezó a llamar a IOL y a FinBERT de verdad en tests marcados como "sin red"
> — la suite se colgó. Es **el mismo patrón** que había pasado con `rsi_signal`
> en la Tarea 3.7: al agregar una fuente nueva al ciclo, los mocks viejos dejan
> de cubrirlo. Se agregó un fixture `autouse` que apaga los bonos por defecto y
> 5 tests nuevos que los prenden explícitamente.

**Corrida real del scanner con bonos habilitados:**

```
$ ./venv/Scripts/python.exe scanner_job.py --una-vez --ignorar-horario
09:00:54  INFO    FinBERT cargado (ProsusAI/finbert)
09:01:48  INFO    Escaneo CEDEARs: 1 candidato(s), 1 nuevo(s) notificado(s), 9 descartado(s)
09:01:48  INFO    Autenticación exitosa en IOL (usuario ma***@gmail.com).
09:02:26  INFO    Escaneo bonos: 9 candidato(s), 9 nuevo(s) notificado(s), 0 descartado(s)
09:02:26  INFO    Ciclo terminado: 10 señal(es) notificada(s), 0 acción(es) del gestor
```

Las 10 señales llegaron a Telegram. Suite final: **401 passed**.

---

## Estado real de las tareas — auditado el 2026-09-07 (2)

De las **37 tareas 🤖** del plan: **33 hechas, 4 pendientes**. Ninguna de las
cuatro que faltan se puede empezar sin algo que tiene que aportar una persona.

> [!done] Las 5 tareas que estaban sin bloqueo se completaron
> 8.1, 8.2, 8.3, 8.4 y 9.4, todas el 2026-09-07. Ver las entradas de esa fecha
> más arriba. **El login contra IOL funciona** y los precios de bonos ya salen
> de la cotización real en pesos.

### Lo que falta: 4 tareas, todas esperando algo 👤

```mermaid
flowchart LR
    VPS[/"10.2 👤<br/>VPS preparado"/]:::cred --> T103[10.3 · systemd]
    VAL[/"10.4 👤<br/>3-4 semanas validando<br/>en modo solo sugerir"/]:::cred --> T11
    OK["8.1 / 8.2 / 8.3 ✅<br/>IOL en modo lectura"]:::hecho --> T11["11.1 / 11.2 / 11.3<br/>Ejecución real"]
    classDef cred fill:#78350f,stroke:#f59e0b,color:#fff
    classDef hecho fill:#065f46,stroke:#10b981,color:#fff
```

| Tarea | Qué falta | Quién |
|---|---|---|
| **10.3** — Servicios systemd | El VPS preparado (Tarea 10.2). `scanner_job.py` ya existe y es exactamente lo que el servicio va a levantar | 👤 |
| **11.1** — Envío de órdenes en CI | El período de validación (Tarea 10.4). La parte de IOL ya está: `IOLClient` autenticado y con las rutas verificadas | 👤 |
| **11.2** — Guardrails de riesgo | Ídem. El kill switch `MODO_FANTASMA` y los parámetros de capital ya existen | 👤 |
| **11.3** — Auditoría de órdenes | Ídem | 👤 |

> [!warning] Las tres de la Fase 11 no están bloqueadas por código
> Están bloqueadas **a propósito**. La Tarea 10.4 pide 3-4 semanas corriendo en
> modo solo sugerir antes de habilitar dinero real, y ese es el punto entero de
> la fase. `MODO_FANTASMA` sigue en `true`.

### Las 33 tareas 🤖 hechas

| Fase | Tareas | Estado |
|---|---|---|
| 1 — Base del proyecto | 1.2, 1.3 | ✅ |
| 2 — Datos de mercado | 2.1, 2.2 | ✅ |
| 3 — Filtros técnicos | 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7 | ✅ |
| 4 — Riesgo y noticias | 4.1, 4.2, 4.3, 4.4, 4.5 | ✅ |
| 5 — Smart money | 5.1, 5.2, 5.3, 5.4, 5.5 | ✅ |
| 7 — Telegram | 7.1, 7.2 | ✅ |
| 8 — IOL modo lectura | 8.1, 8.2, 8.3, 8.4 | ✅ |
| 9 — Bonos | 9.1, 9.2, 9.3, 9.4 | ✅ |
| 10 — Automatización | 10.1 (falta 10.3) | ✅ |
| 12 — Producción | 12.2 | ✅ |

*(La Fase 6 — Google Sheets — se descartó el 2026-09-07.)*

### Estado de las credenciales

| Variable | Estado | Qué desbloqueó |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | ✅ cargadas y **probadas** (llegaron mensajes reales) | 7.1, 7.2, 10.1, 12.2 |
| `IOL_USERNAME` / `IOL_PASSWORD` | ✅ cargadas y **probadas** (login exitoso contra la cuenta) | 8.1, 8.2, 8.3, 8.4, 9.4 |
| `SEC_USER_AGENT` | ✅ default válido (no es credencial) | 5.3, 5.4, 5.5 |

### Endpoints disponibles

| Método | Ruta | Qué devuelve |
|---|---|---|
| `GET` | `/senales` | CEDEARs: 7 filtros + RSI, con `origen` |
| `GET` | `/senales/bonos` | Renta fija, con precio **real** en pesos de IOL |
| `GET` | `/senales/smart-money` | Consenso institucional 13F |
| `GET` | `/iol/saldo` | Saldo y tenencia **real** de la cuenta comitente |
| `GET` | `/mercado/ccl` | Dólar CCL implícito |
| `GET` | `/dashboard` | Paper trading, con desglose por estrategia |
| `GET` | `/riesgo/vix` | Circuit breaker de VIX |
| `POST` | `/notificaciones/test` | Prueba de Telegram |

> [!todo] Próximo paso real
> Terminar el VPS (Tarea 10.2 👤) y dejar el `scanner_job.py` corriendo 24/7 con
> `MODO_FANTASMA=true`. Ese es el período de validación de la Tarea 10.4, y es lo
> único que separa al sistema de poder operar de verdad.
