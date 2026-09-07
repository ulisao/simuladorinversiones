from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas, crud
from . import config, market_data, migrations, notifications, risk_filters, signals
from . import bond_signals, broker_iol, edgar_13f, wallstreet_tracker
from .database import Base, engine, get_db
from .calculations import BrokerRates
from .market_data import MarketDataError

Base.metadata.create_all(bind=engine)
# create_all no toca tablas que ya existen: las columnas nuevas sobre una base
# con datos las agrega esto (ver app/migrations.py).
migrations.migrar(engine)

app = FastAPI(
    title="Simulador de Inversiones IA - Paper Trading",
    description=(
        "API que digitaliza el Simulador_Inversiones_IA_Paper_Trading.xlsx: "
        "registra operaciones de paper trading y calcula comisiones/resultado neto "
        "con las mismas fórmulas que la planilla, para auditar si una estrategia "
        "rinde de verdad antes de arriesgar dinero real."
    ),
    version="0.1.0",
)

# En desarrollo permitimos cualquier origen; restringir en producción al dominio del frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------- Configuración de broker ----------

@app.get("/broker-config", response_model=schemas.BrokerConfigOut)
def read_broker_config(db: Session = Depends(get_db)):
    cfg = crud.get_or_create_broker_config(db)
    rates = BrokerRates(cfg.comision_broker, cfg.derechos_mercado, cfg.iva)
    return schemas.BrokerConfigOut(
        id=cfg.id,
        comision_broker=cfg.comision_broker,
        derechos_mercado=cfg.derechos_mercado,
        iva=cfg.iva,
        costo_efectivo_por_tramo=round(rates.costo_efectivo_por_tramo, 6),
        costo_efectivo_total_ida_y_vuelta=round(rates.costo_efectivo_total_ida_y_vuelta, 6),
    )


@app.put("/broker-config", response_model=schemas.BrokerConfigOut)
def write_broker_config(data: schemas.BrokerConfigBase, db: Session = Depends(get_db)):
    cfg = crud.update_broker_config(db, data)
    rates = BrokerRates(cfg.comision_broker, cfg.derechos_mercado, cfg.iva)
    return schemas.BrokerConfigOut(
        id=cfg.id,
        comision_broker=cfg.comision_broker,
        derechos_mercado=cfg.derechos_mercado,
        iva=cfg.iva,
        costo_efectivo_por_tramo=round(rates.costo_efectivo_por_tramo, 6),
        costo_efectivo_total_ida_y_vuelta=round(rates.costo_efectivo_total_ida_y_vuelta, 6),
    )


# ---------- Operaciones (trades) ----------

def _rates(db: Session) -> BrokerRates:
    cfg = crud.get_or_create_broker_config(db)
    return BrokerRates(cfg.comision_broker, cfg.derechos_mercado, cfg.iva)


@app.get("/trades", response_model=list[schemas.TradeOut])
def list_trades(db: Session = Depends(get_db)):
    rates = _rates(db)
    return [crud.to_trade_out(t, rates) for t in crud.list_trades(db)]


@app.post("/trades", response_model=schemas.TradeOut, status_code=201)
def create_trade(data: schemas.TradeCreate, db: Session = Depends(get_db)):
    rates = _rates(db)
    trade = crud.create_trade(db, data)
    return crud.to_trade_out(trade, rates)


@app.get("/trades/{trade_id}", response_model=schemas.TradeOut)
def read_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = crud.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(404, "Operación no encontrada")
    return crud.to_trade_out(trade, _rates(db))


@app.patch("/trades/{trade_id}", response_model=schemas.TradeOut)
def patch_trade(trade_id: int, data: schemas.TradeUpdate, db: Session = Depends(get_db)):
    trade = crud.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(404, "Operación no encontrada")
    trade = crud.update_trade(db, trade, data)
    return crud.to_trade_out(trade, _rates(db))


@app.post("/trades/{trade_id}/cerrar", response_model=schemas.TradeOut)
def close_trade(
    trade_id: int,
    data: schemas.TradeClose,
    tareas: BackgroundTasks,
    db: Session = Depends(get_db),
):
    trade = crud.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(404, "Operación no encontrada")
    trade = crud.close_trade(db, trade, data)
    salida = crud.to_trade_out(trade, _rates(db))

    # Alerta de cierre (Tarea 7.2). Va en background para no demorar la respuesta
    # con una llamada a Telegram; el módulo nunca lanza, así que un fallo de red
    # no puede afectar al cierre ya persistido.
    tareas.add_task(
        notifications.send_telegram,
        notifications.mensaje_cierre_operacion(salida),
        "HTML",
    )
    return salida


@app.delete("/trades/{trade_id}", status_code=204)
def remove_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = crud.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(404, "Operación no encontrada")
    crud.delete_trade(db, trade)


# ---------- Dashboard ----------

@app.get("/dashboard", response_model=schemas.DashboardOut)
def dashboard(db: Session = Depends(get_db)):
    return crud.build_dashboard(db)


# ---------- Datos de mercado ----------

@app.get("/market/precio/{ticker}", response_model=schemas.PrecioMercadoOut)
def precio_de_mercado(ticker: str):
    """Último precio de cierre del ticker, para autocompletar el simulador.

    `operable=False` mientras el precio venga de yfinance: es la acción
    subyacente en USD, no el CEDEAR en ARS (Tarea 2.1). Pasa a `True` cuando la
    cotización salga de IOL (Fase 8).
    """
    try:
        precio = market_data.get_last_price(ticker)
    except MarketDataError as exc:
        raise HTTPException(404, str(exc))
    return schemas.PrecioMercadoOut(
        ticker=ticker.upper(),
        precio=precio,
        advertencia=market_data.ADVERTENCIA_PRECIO_REFERENCIA,
        operable=False,
    )


# ---------- Riesgo ----------

@app.get("/riesgo/vix", response_model=schemas.EstadoVixOut)
def estado_del_vix():
    """Estado del circuit breaker de VIX (para mostrarlo en el dashboard)."""
    return risk_filters.estado_vix()


# ---------- Notificaciones ----------

@app.post("/notificaciones/test", response_model=schemas.NotificacionOut)
def probar_notificacion():
    """Manda un mensaje fijo al Telegram configurado (Tarea 7.1).

    Siempre responde 200: si el bot no está configurado o Telegram falla, el
    motivo viaja en el cuerpo (`enviado=False`).
    """
    return notifications.send_telegram(notifications.MENSAJE_DE_PRUEBA, parse_mode="HTML")


# ---------- Cuenta real de IOL (Fase 8, solo lectura) ----------
#
# Nada de esta sección envía órdenes. La ejecución real es la Fase 11 y está
# detrás del kill switch `MODO_FANTASMA`.


@app.get("/iol/saldo", response_model=schemas.SaldoIOLOut)
def saldo_iol():
    """Saldo y tenencia real de la cuenta comitente (Tarea 8.2).

    Es **plata real**, no el paper trading del simulador.
    """
    cliente = broker_iol.get_client()
    try:
        estado = cliente.get_estado_cuenta()
        posiciones = cliente.get_portafolio()
    except broker_iol.IOLError as exc:
        raise HTTPException(503, str(exc))

    en_pesos = [
        c for c in (estado.get("cuentas") or []) if c.get("moneda") == "peso_Argentino"
    ]
    return schemas.SaldoIOLOut(
        disponible=round(sum(float(c.get("disponible") or 0.0) for c in en_pesos), 2),
        titulos_valorizados=round(
            sum(float(c.get("titulosValorizados") or 0.0) for c in en_pesos), 2
        ),
        total=round(sum(float(c.get("total") or 0.0) for c in en_pesos), 2),
        posiciones=posiciones,
        consultado=datetime.now().isoformat(timespec="seconds"),
    )


@app.get("/mercado/ccl", response_model=schemas.CclOut)
def dolar_ccl():
    """Dólar Contado con Liquidación implícito (Tarea 8.4).

    Se calcula con el mismo bono cotizando en pesos (AL30) y en dólares (AL30D).
    Es contexto macro: **no bloquea ninguna operación**.
    """
    try:
        return broker_iol.get_client().get_valor_ccl()
    except broker_iol.IOLError as exc:
        raise HTTPException(503, str(exc))


# ---------- Señales ----------

@app.get("/senales", response_model=schemas.SenalesOut)
def escanear_senales():
    """Escanea el universo de CEDEARs y devuelve candidatos y descartados.

    Orden de chequeos: VIX → noticias → smart money → 7 filtros técnicos.
    Es una operación lenta (le pega a Yahoo Finance por cada ticker): puede
    tardar bastante más que el resto de los endpoints.
    """
    return signals.escanear_senales()


@app.get("/senales/bonos", response_model=schemas.SenalesBonosOut)
def escanear_senales_bonos():
    """Escanea el universo de bonos soberanos y provinciales (Tarea 9.4).

    A diferencia de `/senales`, los precios son **reales en pesos de BYMA**:
    salen de la cotización de IOL, no de yfinance.

    Si IOL no está disponible, la respuesta sale igual con HTTP 200, lista vacía
    y el motivo en `veto_global` — el mismo contrato que el veto de VIX.
    """
    return bond_signals.escanear_senales_bonos()


@app.get("/senales/smart-money", response_model=schemas.SenalesSmartMoneyOut)
def escanear_smart_money(db: Session = Depends(get_db)):
    """Señales de consenso institucional 13F (Tareas 5.3, 5.4 y 5.5).

    Estrategia independiente del swing técnico, con su propio cupo de capital.
    Es **lenta por naturaleza**: los 13F son trimestrales y salen con hasta 45
    días de rezago legal, así que la respuesta cambia pocas veces al año.

    Los filings se cachean en disco, así que la primera llamada de cada trimestre
    es la única que baja todo de SEC EDGAR.
    """
    datos = edgar_13f.descargar_movimientos()
    tracker = wallstreet_tracker.WallStreetAdvancedTracker()
    resultado = tracker.procesar_reportes(datos["movimientos"])

    abiertas = [
        t.ticker
        for t in crud.listar_trades_abiertos(db)
        if (t.estrategia or config.ESTRATEGIA_SWING) == config.ESTRATEGIA_SMART_MONEY
    ]

    return schemas.SenalesSmartMoneyOut(
        generado=datetime.now().isoformat(timespec="seconds"),
        estrategia=config.ESTRATEGIA_SMART_MONEY,
        cupo_asignado=round(config.cupo_de(config.ESTRATEGIA_SMART_MONEY), 2),
        monto_por_posicion=round(
            config.monto_por_posicion(config.ESTRATEGIA_SMART_MONEY), 2
        ),
        advertencia_precios=market_data.ADVERTENCIA_PRECIO_REFERENCIA,
        fondos=datos["fondos"],
        compras=resultado["compras"],
        ventas=tracker.senales_de_venta(datos["movimientos"], abiertas),
        descartados=resultado["descartados"],
        errores=datos["errores"],
    )


@app.get("/config/universo")
def universo_configurado():
    """Universos de instrumentos que audita el sistema, para inspeccionarlos."""
    return {
        "tickers_byma": config.TICKERS_BYMA,
        "benchmark": config.TICKER_BENCHMARK,
        "bonos_soberanos": config.BONOS_SOBERANOS,
        "bonos_provinciales": config.BONOS_PROVINCIALES,
        "fondos_13f": config.FONDOS_13F,
        "cupos_por_estrategia": config.CUPOS_POR_ESTRATEGIA,
    }
