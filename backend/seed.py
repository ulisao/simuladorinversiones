"""
Carga las 5 operaciones de ejemplo del Simulador_Inversiones_IA_Paper_Trading.xlsx
original, para validar que el backend calcula exactamente lo mismo que la planilla.

Uso:
    cd backend && source venv/bin/activate && python seed.py
"""
from datetime import date

from app.database import Base, engine, SessionLocal
from app import models, crud, schemas

Base.metadata.create_all(bind=engine)

EJEMPLOS = [
    dict(ticker="AAPL", tipo="CEDEAR", fecha_compra=date(2026, 8, 3), cantidad=25,
         precio_entrada=12500, fecha_venta=date(2026, 8, 14), precio_salida=13450,
         senal="Salida por Take-Profit (+7.6%)"),
    dict(ticker="NVDA", tipo="CEDEAR", fecha_compra=date(2026, 8, 5), cantidad=15,
         precio_entrada=18200, fecha_venta=date(2026, 8, 11), precio_salida=17600,
         senal="Salida por Stop-Loss (-3.3%)"),
    dict(ticker="NXE", tipo="CEDEAR", fecha_compra=date(2026, 8, 10), cantidad=84,
         precio_entrada=9400, fecha_venta=date(2026, 8, 21), precio_salida=10150,
         senal="Ruptura semanal alcista (+8.0%)"),
    dict(ticker="MELI", tipo="CEDEAR", fecha_compra=date(2026, 8, 12), cantidad=8,
         precio_entrada=38500, fecha_venta=date(2026, 8, 18), precio_salida=38900,
         senal="Ganancia absorbida por comisiones"),
    dict(ticker="TSLA", tipo="CEDEAR", fecha_compra=date(2026, 8, 17), cantidad=12,
         precio_entrada=22100, fecha_venta=date(2026, 8, 25), precio_salida=21300,
         senal="Salida preventiva por noticias"),
]


def main():
    db = SessionLocal()
    try:
        crud.get_or_create_broker_config(db)  # asegura defaults 0.5% / 0.08% / 21%

        if db.query(models.Trade).count() > 0:
            print("Ya hay operaciones cargadas, no se vuelve a sembrar.")
            return

        for ej in EJEMPLOS:
            trade = crud.create_trade(
                db,
                schemas.TradeCreate(
                    ticker=ej["ticker"],
                    tipo=ej["tipo"],
                    fecha_compra=ej["fecha_compra"],
                    cantidad=ej["cantidad"],
                    precio_entrada=ej["precio_entrada"],
                    senal=ej["senal"],
                ),
            )
            crud.close_trade(
                db,
                trade,
                schemas.TradeClose(
                    fecha_venta=ej["fecha_venta"],
                    precio_salida=ej["precio_salida"],
                ),
            )
        print(f"Sembradas {len(EJEMPLOS)} operaciones de ejemplo.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
