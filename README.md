# Simulador de Inversiones IA — Paper Trading

Digitaliza el `Simulador_Inversiones_IA_Paper_Trading.xlsx` original como una
app web: cargás cada señal (real o sugerida por un futuro bot), el sistema
calcula automáticamente comisiones, resultado neto y rendimiento %, y un
dashboard te dice si la estrategia da plata de verdad — antes de arriesgar
un peso.

Es el MVP de un proyecto más grande (ver "Roadmap" abajo): la idea final,
según los manuales que armó tu amigo, es un bot que analiza CEDEARs y bonos
argentinos con filtros técnicos + noticias (FinBERT) + circuit breaker de
VIX, y ejecuta órdenes automáticamente en InvertirOnline (IOL). Este MVP
resuelve el primer paso que los mismos manuales recomiendan: **validar la
estrategia en papel antes de conectar plata real.**

## Estructura del proyecto

```
simulador-inversiones/
├── backend/          FastAPI + SQLite. Toda la lógica de comisiones vive en
│                      app/calculations.py (fórmulas idénticas al Excel).
│                      Encima se apoya el motor de señales: config.py,
│                      market_data.py, technical_filters.py, risk_filters.py,
│                      smart_money.py, fixed_income_filters.py, signals.py,
│                      rsi_signal.py (fuente de señal alternativa),
│                      edgar_13f.py + wallstreet_tracker.py (consenso 13F).
│                      Alertas y automatización: app/notifications.py,
│                      app/weekly_report.py, scanner_job.py,
│                      position_monitor_job.py.
├── frontend/          Next.js + Tailwind. Dashboard, Simulador, Señales,
│                      Configuración.
└── docs/              Manuales originales (.docx), su texto plano en
                        specs-txt/ y parametros-riesgo.md.
```

### Arquitectura

```mermaid
flowchart LR
    subgraph NAV["Frontend — Next.js"]
        DASH[Dashboard /]
        SIM[Simulador /simulador]
        SEN[Señales /senales]
        CFG[Config /config]
    end

    subgraph API["Backend — FastAPI :8123"]
        EP[main.py]
        CALC[calculations.py]
        SIGN[signals.py]
    end

    DASH & SIM & CFG --> EP
    SEN --> EP
    EP --> CALC
    EP --> SIGN
    CALC --> SQLITE[(SQLite<br/>simulador.db)]
    SIGN -.-> EXT{{yfinance · RSS<br/>FinBERT · SEC}}
```

> [!note] Dónde está el resto de la documentación
> El plan de trabajo fase por fase está en `tareasdesarrollo.md`, y el historial
> de lo ya resuelto en `PROGRESS.md`. Las convenciones del repo, en `CLAUDE.md`.

## Cómo correrlo

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # en Windows: venv\Scripts\activate
pip install -r requirements.txt
python seed.py                  # carga las 5 operaciones de ejemplo del Excel
uvicorn app.main:app --reload --port 8123
```

La API queda en `http://localhost:8123` (documentación interactiva en
`http://localhost:8123/docs`).

> [!warning] FinBERT es pesado
> `requirements.txt` incluye `torch` y `transformers`: son ~2,5 GB instalados y
> necesitan ~1 GB de RAM libre para inferencia. En un servidor chico, comentá
> esas dos líneas — `app/risk_filters.py` está escrito para funcionar sin ellas,
> salteando el filtro de sentimiento.

### 2. Alertas y escaneo automático (opcional)

Con `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` cargados en `backend/.env`, el
sistema puede avisarte solo. Nada de esto ejecuta órdenes: solo notifica.

```bash
cd backend

# Probar que el bot llega a tu chat
curl -X POST http://localhost:8123/notificaciones/test

# Escaneo periódico + monitor de posiciones (Fase 10). Corre en primer plano.
./venv/Scripts/python.exe scanner_job.py

# Un solo ciclo, forzando el chequeo de horario a "siempre activo"
./venv/Scripts/python.exe scanner_job.py --una-vez --ignorar-horario

# Mandar el reporte semanal ahora mismo, sin esperar al viernes
./venv/Scripts/python.exe scanner_job.py --reporte-semanal
```

| Qué avisa | Cuándo | Tarea |
|---|---|---|
| Cierre de una operación | Al hacer `POST /trades/{id}/cerrar` desde la app | 7.2 |
| Venta del gestor de salidas (TP1, trailing, cierre 16:50) | En cada barrido del monitor de posiciones | 7.2 |
| Señal nueva | Cada 10 min en rueda BYMA, una vez por ticker y por día | 10.1 |
| Escaneo bloqueado (VIX en pánico o mercado bajista) | Una vez por día | 10.1 |
| Resumen de la semana | Viernes 17:30, hora del servidor | 12.2 |

> [!warning] El planificador usa el reloj del sistema
> El horario de rueda se chequea en ART, pero el `viernes 17:30` del reporte
> semanal es hora local del servidor. Dejá el servidor en
> `America/Argentina/Buenos_Aires` (es lo que pide la Tarea 10.2) para que las
> dos cosas coincidan.

### 3. Frontend

En otra terminal:

```bash
cd frontend
npm install
npm run dev
```

Abrí `http://localhost:3000`. Si el backend corre en otro puerto/host, editá
`frontend/.env.local` (`NEXT_PUBLIC_API_URL`).

### Variables de entorno

Copiá `backend/.env.example` a `backend/.env` y completá lo que necesites.
Ninguna credencial va hardcodeada ni versionada: `.env` está en `.gitignore`,
y `app/config.py` es el único módulo que las lee.

| Variable | Para qué | Obligatoria | Es secreto |
|---|---|---|---|
| `IOL_USERNAME` | Usuario de InvertirOnline. Lo usa `app/broker_iol.py` para el OAuth2 contra `/token` | Para todo `/iol/*` y `/mercado/ccl` (Fase 8) | Sí |
| `IOL_PASSWORD` | Contraseña de InvertirOnline | Para todo `/iol/*` y `/mercado/ccl` (Fase 8) | **Sí — es la contraseña de la cuenta real** |
| `IOL_API_URL` | Base de la API de IOL. Default `https://api.invertironline.com` | No | No |
| `TELEGRAM_BOT_TOKEN` | Token del bot. **Viaja dentro de la URL** que se le pega a Telegram | Solo para las alertas (Fases 7, 10 y 12) | Sí |
| `TELEGRAM_CHAT_ID` | Chat de destino de las alertas | Solo para las alertas | Identifica el destino |
| `CAPITAL_TOTAL`, `MAX_POSICIONES`, `CUPO_SWING`, `CUPO_SMART_MONEY`, `LIMITE_POR_OPERACION` | Pisan los defaults de `config.py` | No | No |
| `SEC_USER_AGENT` | Dato de contacto que exige la API de SEC EDGAR (consenso 13F). No es una credencial | No | No |
| `MODO_FANTASMA` | Kill switch. En `true` (default) nunca sale una orden real | No | No |

> [!note] Arranca sin credenciales
> Sin ninguna de estas variables el proyecto funciona igual: el simulador y el
> motor de señales no necesitan credenciales. Lo único que se cae sin
> `IOL_USERNAME`/`IOL_PASSWORD` son los endpoints `/iol/saldo` y `/mercado/ccl`,
> que devuelven un `503` con el motivo en castellano.

### Cargar las credenciales al desplegar (VPS)

El `.env` **no se commitea nunca** — está en `.gitignore` y `git ls-files
backend/.env` tiene que salir vacío. Al desplegar se crea a mano en el servidor:
no se copia desde la máquina de desarrollo por un canal que quede registrado
(nada de pegarlo en un chat, en un issue o en el historial de un shell
compartido).

```mermaid
flowchart TD
    CLONE[git clone del repo<br/>llega SIN .env] --> CREATE[Crear backend/.env<br/>en el servidor, a mano]
    EXAMPLE[backend/.env.example<br/>versionado, sin valores] -.plantilla.-> CREATE
    CREATE --> PERMS["chmod 600 backend/.env<br/>chown al usuario del servicio"]
    PERMS --> LOAD[python-dotenv lo lee<br/>solo desde app/config.py]
    LOAD --> APP[uvicorn / scanner_job]
```

Paso a paso en el VPS:

```bash
# 1. Clonar. El repo NO trae el .env: no existe del lado del servidor todavía.
git clone <repo> simuladorinversiones && cd simuladorinversiones/backend

# 2. Partir de la plantilla versionada, que viene con las claves vacías.
cp .env.example .env

# 3. Completar los valores con un editor local al servidor (nunca por copiar y
#    pegar en un canal que quede grabado).
nano .env      # IOL_USERNAME, IOL_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 4. Dejarlo legible SOLO por el usuario que corre el bot.
chmod 600 .env
chown "$USER":"$USER" .env

# 5. Verificar que git no lo ve. Las dos salidas tienen que estar vacías.
git ls-files .env
git status --porcelain | grep '\.env$'

# 6. Comprobar que las credenciales entraron bien, sin imprimirlas.
./venv/bin/python -c "from app import config; print('IOL:', bool(config.IOL_USERNAME and config.IOL_PASSWORD)); print('Telegram:', bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID))"
```

> [!warning] Qué NO hacer en el servidor
> - No pasar las credenciales por línea de comandos (`IOL_PASSWORD=... uvicorn ...`):
>   quedan en `~/.bash_history` y las ve cualquiera con `ps aux`.
> - No pegarlas en un `docker run -e`, un `systemd` `Environment=` ni un
>   `ExecStart` — usar `EnvironmentFile=/ruta/backend/.env` con permisos `600`.
> - No dejar la clave SSH del VPS dentro del repo. `.gitignore` ya bloquea
>   `*.key`, `*.pem`, `id_rsa*` y `ssh-key-*`, pero el lugar correcto es
>   `~/.ssh/` con `chmod 600`.

> [!note] Si una credencial se filtró
> Rotar primero, limpiar después. Cambiar la contraseña en IOL y regenerar el
> token con `@BotFather` es inmediato; reescribir el historial de git no
> "desfiltra" nada que ya se haya publicado.

### Tests

```bash
cd backend
./venv/Scripts/python.exe -m pytest -v          # Windows
# pytest -v                                      # Linux/Mac con el venv activado

pytest -m "not network"    # sin pegarle a Yahoo Finance / SEC / Google News
```

## Endpoints de la API

| Método | Ruta | Qué devuelve |
|---|---|---|
| `GET` | `/senales` | CEDEARs: 7 filtros técnicos + RSI de sobreventa, cada candidato con su `origen` |
| `GET` | `/senales/bonos` | Renta fija: precio **real en pesos** de BYMA, vía IOL |
| `GET` | `/senales/smart-money` | Consenso institucional 13F de 5 fondos grandes |
| `GET` | `/iol/saldo` | Saldo y tenencia **real** de la cuenta comitente (solo lectura) |
| `GET` | `/mercado/ccl` | Dólar Contado con Liquidación implícito (AL30 / AL30D) |
| `GET` | `/dashboard` | Métricas de paper trading, con desglose por estrategia |
| `GET` | `/riesgo/vix` | Estado del circuit breaker de VIX |
| `POST` | `/notificaciones/test` | Manda un mensaje de prueba a Telegram |

> [!warning] Dos fuentes de precio, y no son intercambiables
> `/senales` (CEDEARs) usa **yfinance**, que devuelve la acción subyacente en
> **USD** — sirve para el patrón técnico, no para calcular cantidades. `/senales/bonos`
> y `/iol/saldo` usan **IOL**, que da el precio **real en pesos**. Para la misma
> fecha, AAPL vale US$ 319,97 en yfinance y $ 25.400 como CEDEAR en BYMA.

## Cómo se usa: el flujo de trabajo

La app tiene cuatro páginas y el uso diario es siempre el mismo ciclo de cuatro
pasos. Nada de esto toca dinero real (ver "Notas de seguridad" al final).

```mermaid
flowchart LR
    A["1 · /senales<br/>Escanear"] --> B["2 · /simulador<br/>Cargar operación"]
    B --> C["3 · /simulador<br/>Cerrar posición"]
    C --> D["4 · /<br/>Ver el veredicto"]
    D -.-> A
```

### 1. Señales (`/senales`) — qué comprar

Tocás **"Volver a escanear"** y esperás. Tarda unos **45 segundos**: el backend
recorre los 10 CEDEARs de `TICKERS_BYMA` y por cada uno evalúa, en este orden:

```mermaid
flowchart TD
    VIX[VIX global] -->|vetea| CORTA[/Corta todo el escaneo/]
    VIX -->|OK| NEWS[Noticias · FinBERT]
    NEWS -->|vetea| DESC[/Descarta el ticker/]
    NEWS -->|OK| SM[Smart money<br/>RVOL + insiders]
    SM -->|solo informa| F7[Los 7 filtros técnicos]
    F7 -->|vetea| DESC
    F7 -->|aprueba| OK[/Señal válida/]
```

Devuelve dos tablas:

| Tabla | Qué trae | Para qué sirve |
|---|---|---|
| **Señales válidas** | Precio sugerido, stop-loss, take-profit, % de riesgo. Al lado, como contexto: RVOL, filings de insiders y score de noticias. | Lo que el sistema propone operar. |
| **Descartados** | Cada instrumento vetado **con su motivo** (`VETO RS: no supera a SPY`, `VETO TÉCNICO: estructura no alcista`, etc.). | Es la que más enseña: ahí se ve por qué el sistema no quiso operar algo. |

> [!warning] El contexto no es un filtro aprobado
> RVOL, insiders y score de noticias **no hacen mejor ni peor a una señal**: son
> información de color, no una validación adicional.

Arriba de todo se muestra el estado del VIX. Si el circuit breaker se activa
(VIX > 25 o salto de +10% en el día), **no vas a ver ninguna señal** y aparece un
cartel rojo con el motivo. No es un error: es el sistema negándose a operar en
pánico de mercado.

![Página de Señales con una señal válida y una vetada](./docs/assets/senales.png)

### 2. Cargar en el simulador — registrar la apuesta

En cada señal válida hay un botón **"Cargar en el simulador"**. Te lleva a
`/simulador` con el formulario abierto y el ticker, el precio y el motivo ya
completos.

> [!note] Decisión de diseño
> **No crea la operación solo.** Completás la cantidad y confirmás vos. Es a
> propósito: el sistema sugiere, la persona decide.

También podés cargar una operación a mano con **"+ Nueva operación"**. Ahí el
botón **"Usar precio de mercado"** trae el último cierre real del ticker, así no
hay que tipearlo.

### 3. Cerrar la posición — registrar el resultado

Cuando la operación termina, en `/simulador` tocás **"Cerrar"** en esa fila y
cargás fecha y precio de salida. Recién ahí el sistema calcula las comisiones de
ida y vuelta y el resultado neto real.

### 4. Dashboard (`/`) — ¿esto rinde o no?

Capital invertido, comisiones pagadas, ganancia/pérdida neta, rentabilidad
ponderada, ganadoras vs. perdedoras y tasa de acierto.

![Dashboard con las métricas consolidadas y el veredicto](./docs/assets/dashboard.png)

> [!warning] El veredicto es más optimista de lo que parece
> El cartel **"SISTEMA RENTABLE - LISTO PARA REAL"** se enciende con la sola
> condición de que la ganancia neta sea mayor a cero: **una única operación
> cerrada con +$50 ya lo dispara.** No es una luz verde.
>
> El criterio correcto es el de la Tarea 10.4 de `tareasdesarrollo.md`: dejar el
> sistema corriendo **3 o 4 semanas**, cargar cada señal y seguirla hasta el
> cierre, y recién ahí mirar el número. Con 2 operaciones el cartel no significa
> nada.

### Configuración (`/config`)

Ajusta las comisiones del broker (0,5% / 0,08% / 21% por defecto → 0,7018% por
tramo). Cambiarlas **recalcula todo el histórico al instante**, porque los campos
calculados no se guardan en la base: se derivan al vuelo desde `calculations.py`.

### Qué NO hace la app todavía

| No hace | Por qué | Se desbloquea con |
|---|---|---|
| Ejecutar órdenes | Fase 11, deliberadamente no construida | Validación previa (Tarea 10.4) |
| Correr 24/7 en un servidor | El scanner ya existe y corre solo, pero todavía en tu máquina | VPS (Tarea 10.2 👤) |

Hoy es **100% papel**: vos cargás, vos cerrás, el sistema calcula y opina.

## Qué valida este MVP

Las 5 operaciones de ejemplo (AAPL, NVDA, NXE, MELI, TSLA) son las mismas
del Excel original. Los cálculos del backend fueron verificados contra las
fórmulas de la planilla:

| Concepto | Valor | Qué significa |
|---|---|---|
| Comisión por tramo | **0,7018%** | `(comisión broker + derechos de mercado) × (1 + IVA)` con los valores estándar de IOL/BYMA. |
| Costo ida y vuelta | **1,4036%** | El rendimiento bruto mínimo que necesita una operación para no perder plata. |

> [!note] El caso MELI es un ejemplo intencional
> Gana bruto (+1,04%) pero **pierde neto** una vez descontadas las comisiones —
> justo lo que este simulador existe para detectar antes de operar con dinero
> real.

## Roadmap (según los manuales originales)

El plan detallado, tarea por tarea, está en `tareasdesarrollo.md`; lo ya resuelto,
con la evidencia de cómo se probó, en `PROGRESS.md`.

| # | Etapa | Estado | Detalle |
|---|---|---|---|
| 1 | **Paper trading manual** | ✅ | Cargar señales a mano y auditar si conviene seguir. |
| 2 | **Precios reales y señales técnicas** | ✅ | `yfinance` para autocompletar el precio, más los 7 filtros de los manuales (tendencia, ATR, fuerza relativa vs. SPY, earnings). Sin ejecutar nada. |
| 3 | **Filtro de noticias y riesgo** | ✅ | Circuit breaker de VIX + FinBERT local, como capa de veto antes de sugerir una compra. |
| 3b | **Consenso institucional (13F)** | ✅ | Segunda estrategia, independiente del swing técnico y con su propio cupo de capital: sigue qué compraron 5 fondos grandes en SEC EDGAR y exige que coincidan al menos dos. |
| 4 | **Conectar IOL en modo lectura** | ✅ | Saldo y tenencia real de la cuenta comitente, dólar CCL y cotizaciones reales en pesos de BYMA. El login contra IOL está verificado. Habilitó además las señales de bonos (9.4), que necesitaban precio en Contado Inmediato. |
| 5 | **Alertas y escaneo 24/7** | 🟡 | Telegram ya avisa cierres, señales nuevas y el reporte semanal, y `scanner_job.py` escanea solo sin que nadie abra la app. **Falta:** el VPS para que corra 24/7 (Tarea 10.2 👤). |
| 6 | **Ejecución automática de órdenes** | ⛔ | Recién después de varias semanas de paper trading con esperanza matemática positiva. Implica manejar plata real: logs auditables y límites de riesgo estrictos (stop-loss, tamaño de posición) desde el día uno. |

```mermaid
flowchart LR
    E1["1 · Paper trading"]:::hecho --> E2["2 · Precios y<br/>filtros técnicos"]:::hecho
    E2 --> E3["3 · Noticias y riesgo"]:::hecho
    E3 --> E4["4 · IOL lectura"]:::hecho
    E4 --> E5["5 · Alertas y 24/7"]:::parcial
    E5 --> E6["6 · Ejecución real"]:::stop

    classDef hecho fill:#065f46,stroke:#10b981,color:#fff
    classDef bloq fill:#78350f,stroke:#f59e0b,color:#fff
    classDef parcial fill:#1e3a5f,stroke:#60a5fa,color:#fff
    classDef listo fill:#3f3f46,stroke:#a1a1aa,color:#fff
    classDef stop fill:#7f1d1d,stroke:#ef4444,color:#fff
```

> [!note] Frenar en el punto 4 es una opción razonable
> Señales y datos reales con ejecución 100% manual es mucho más simple de
> mantener y ya cubre lo que el sistema promete.

## Notas de seguridad

> [!warning] Hoy el sistema no ejecuta ninguna orden real
> No se conecta a ninguna cuenta de broker. Solo registra operaciones cargadas a
> mano y sugiere señales de lectura.

Lo que ya está puesto para cuando eso cambie:

| Salvaguarda | Cómo funciona |
|---|---|
| Credenciales fuera del repo | Van en variables de entorno (`backend/.env`), nunca hardcodeadas ni versionadas. `.env` está en `.gitignore` y `app/config.py` es el único módulo que las lee. Cómo cargarlas en un servidor: ["Cargar las credenciales al desplegar (VPS)"](#cargar-las-credenciales-al-desplegar-vps). |
| Claves privadas bloqueadas por patrón | `.gitignore` ignora `*.key`, `*.pem`, `*.p12`, `id_rsa*`, `id_ed25519*` y `ssh-key-*`. Una clave privada commiteada es prácticamente imposible de sacar del historial después, así que se bloquea por forma y no por nombre puntual (Tarea 8.3). |
| Ningún secreto en logs ni en respuestas | `broker_iol.py` nunca loguea el token ni la contraseña — el usuario sale ofuscado (`ul***@...`) y su `__repr__` solo dice "autenticado / sin token". `notifications.py` redacta el `TELEGRAM_BOT_TOKEN` de todo texto derivado de una excepción o de un cuerpo de error, porque la API de Telegram lleva el token **dentro de la URL** y `requests` la incluye entera en sus errores de red (Tarea 8.3). |
| Kill switch | `MODO_FANTASMA` está en `true` por defecto. Mientras siga así, ningún código puede enviar una orden a IOL. (Reemplaza a la vieja `EJECUCION_REAL_HABILITADA`, que ya no se lee: si quedó en un `.env`, `config.py` avisa por consola.) |
| Parámetros centralizados | Los parámetros de riesgo viven en `app/config.py` y están documentados en `docs/parametros-riesgo.md`. Ningún módulo hardcodea capital, stop-loss ni tamaño de posición. |

Chequeo rápido de que nada se filtró, corriendo desde la raíz del repo:

```bash
git ls-files backend/.env                      # tiene que salir vacío
git log --all -p | grep -i "iol_password"      # solo placeholders de los manuales
git check-ignore -v ssh-key-*.key              # tiene que decir IGNORADO
```

> [!warning] `docs/parametros-riesgo.md` está marcado como PROVISORIO
> Tiene los valores por defecto de los manuales ($100.000 ARS, 2 posiciones,
> stop-loss 3%, R/B 1:2), **no valores acordados con el dueño del capital**. Hay
> que revisarlos y firmarlos (Tarea 0.1) antes de habilitar cualquier ejecución
> real.
>
> Un detalle concreto a revisar ahí: el stop se recorta al 3,0% únicamente si el
> riesgo calculado por ATR supera el **3,5%**, así que el riesgo real por
> operación puede llegar hasta 3,5% pese a que el parámetro diga 3,0%.
