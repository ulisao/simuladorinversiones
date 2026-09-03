from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, schemas, crud
from . import config, market_data, risk_filters, signals
from .database import Base, engine, get_db
from .calculations import BrokerRates
from .market_data import MarketDataError

Base.metadata.create_all(bind=engine)

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
def close_trade(trade_id: int, data: schemas.TradeClose, db: Session = Depends(get_db)):
    trade = crud.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(404, "Operación no encontrada")
    trade = crud.close_trade(db, trade, data)
    return crud.to_trade_out(trade, _rates(db))


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
    """Último precio de cierre del ticker, para autocompletar el simulador."""
    try:
        precio = market_data.get_last_price(ticker)
    except MarketDataError as exc:
        raise HTTPException(404, str(exc))
    return schemas.PrecioMercadoOut(ticker=ticker.upper(), precio=precio)


# ---------- Riesgo ----------

@app.get("/riesgo/vix", response_model=schemas.EstadoVixOut)
def estado_del_vix():
    """Estado del circuit breaker de VIX (para mostrarlo en el dashboard)."""
    return risk_filters.estado_vix()


# ---------- Señales ----------

@app.get("/senales", response_model=schemas.SenalesOut)
def escanear_senales():
    """Escanea el universo de CEDEARs y devuelve candidatos y descartados.

    Orden de chequeos: VIX → noticias → smart money → 7 filtros técnicos.
    Es una operación lenta (le pega a Yahoo Finance por cada ticker): puede
    tardar bastante más que el resto de los endpoints.
    """
    return signals.escanear_senales()


@app.get("/config/universo")
def universo_configurado():
    """Universos de instrumentos que audita el sistema, para inspeccionarlos."""
    return {
        "tickers_byma": config.TICKERS_BYMA,
        "benchmark": config.TICKER_BENCHMARK,
        "bonos_soberanos": config.BONOS_SOBERANOS,
        "bonos_provinciales": config.BONOS_PROVINCIALES,
    }
