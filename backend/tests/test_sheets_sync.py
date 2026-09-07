"""
Tests de la sincronización a Google Sheets (Tareas 6.1 y 6.2).

Nada acá le pega a la API de Google: la hoja se reemplaza por un doble
(`HojaFalsa`) que registra las filas que recibe. Lo que se verifica es lo que
puede romper de verdad:

* que las comisiones salgan de `calculations.py` y **no** del 0,6% del manual,
* que un segundo click no duplique filas,
* que un fallo de escritura **no** marque nada como sincronizado.
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config, models, sheets_sync
from app.calculations import BrokerRates
from app.database import Base


# ---------- Andamiaje ----------


class HojaFalsa:
    """Doble de `gspread.Worksheet`: guarda lo que le mandan, no habla con Google."""

    def __init__(self, primera_fila=None, falla_al_escribir=False):
        self.filas = []
        self.encabezados_escritos = None
        self._primera_fila = primera_fila or []
        self._falla = falla_al_escribir

    def row_values(self, n):
        return self._primera_fila

    def update(self, range_name=None, values=None):
        self.encabezados_escritos = values[0] if values else None

    def append_rows(self, filas, value_input_option=None):
        if self._falla:
            raise RuntimeError("cuota de la API agotada")
        self.filas.extend(filas)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    sesion = sessionmaker(bind=engine)()
    yield sesion
    sesion.close()


def _trade(db, ticker="AAPL", precio_salida=110.0, sincronizado=False):
    t = models.Trade(
        ticker=ticker,
        tipo="CEDEAR",
        fecha_compra=date(2026, 9, 1),
        cantidad=10,
        precio_entrada=100.0,
        fecha_venta=date(2026, 9, 5) if precio_salida is not None else None,
        precio_salida=precio_salida,
        sincronizado_sheets=sincronizado,
    )
    db.add(t)
    db.commit()
    return t


@pytest.fixture
def configurado(monkeypatch, tmp_path):
    """Finge que hay credenciales válidas en disco."""
    fake = tmp_path / "credenciales_google.json"
    fake.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "GOOGLE_CREDENTIALS_PATH", str(fake))
    return fake


# ---------- Configuración ----------


def test_sin_ruta_no_esta_configurado(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CREDENTIALS_PATH", "")
    assert sheets_sync.esta_configurado() is False
    assert "GOOGLE_CREDENTIALS_PATH" in sheets_sync.motivo_no_configurado()


def test_ruta_que_no_existe_no_esta_configurado(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CREDENTIALS_PATH", "/no/existe/creds.json")
    assert sheets_sync.esta_configurado() is False
    motivo = sheets_sync.motivo_no_configurado()
    assert "No existe el archivo" in motivo and "0.4" in motivo


def test_con_archivo_esta_configurado(configurado):
    assert sheets_sync.esta_configurado() is True
    assert sheets_sync.motivo_no_configurado() == ""


# ---------- Armado de la fila (columnas A-K del manual) ----------


def test_la_fila_tiene_las_11_columnas_del_manual(db):
    t = _trade(db)
    rates = BrokerRates(comision_broker=0.005, derechos_mercado=0.0008, iva=0.21)
    fila = sheets_sync.fila_desde_trade(t, rates)
    assert len(fila) == len(sheets_sync.ENCABEZADOS) == 11


def test_el_orden_de_columnas_es_el_del_manual(db):
    t = _trade(db, ticker="NVDA")
    rates = BrokerRates(comision_broker=0.005, derechos_mercado=0.0008, iva=0.21)
    fila = sheets_sync.fila_desde_trade(t, rates)
    assert fila[1] == "NVDA"          # B Ticker
    assert fila[2] == "VENTA"         # C Tipo_Operacion
    assert fila[3] == "CI (t0)"       # D Plazo
    assert fila[4] == 10              # E Cantidad
    assert fila[5] == 100.0           # F Precio_Entrada
    assert fila[6] == 110.0           # G Precio_Salida
    assert fila[10] == "CERRADA"      # K Estado


def test_las_comisiones_salen_de_calculations_no_del_06_del_manual(db):
    """El manual hardcodea 0,6% por tramo; la tasa real del Excel es 0,7018%."""
    t = _trade(db)
    rates = BrokerRates(comision_broker=0.005, derechos_mercado=0.0008, iva=0.21)
    fila = sheets_sync.fila_desde_trade(t, rates)

    tasa = rates.costo_efectivo_por_tramo
    esperado = round(10 * 100.0 * tasa + 10 * 110.0 * tasa, 2)
    assert fila[7] == pytest.approx(esperado, abs=0.02)

    # Y explícitamente distinto de lo que daría el 0,6% del manual.
    del_manual = round((10 * 100.0) * 0.006 + (10 * 110.0) * 0.006, 2)
    assert fila[7] != pytest.approx(del_manual, abs=0.01)


def test_el_rendimiento_va_como_porcentaje_no_como_fraccion(db):
    """`compute_trade` devuelve 0.0847; la columna J del manual quiere '8.47%'."""
    t = _trade(db)
    rates = BrokerRates(comision_broker=0.005, derechos_mercado=0.0008, iva=0.21)
    fila = sheets_sync.fila_desde_trade(t, rates)
    assert fila[9].endswith("%")
    valor = float(fila[9].rstrip("%"))
    # 10 papeles de 100 a 110 con ~0,7% por tramo -> ~8,5%, no 0,085.
    assert 7.0 < valor < 10.0


# ---------- Qué se considera pendiente ----------


def test_solo_las_cerradas_y_no_sincronizadas_estan_pendientes(db):
    _trade(db, ticker="CERRADA_NUEVA")
    _trade(db, ticker="YA_SUBIDA", sincronizado=True)
    _trade(db, ticker="ABIERTA", precio_salida=None)

    pendientes = sheets_sync.trades_pendientes(db)
    assert [t.ticker for t in pendientes] == ["CERRADA_NUEVA"]


# ---------- Sincronización ----------


def test_sin_credenciales_no_sincroniza_pero_informa_los_pendientes(db, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CREDENTIALS_PATH", "")
    _trade(db)
    r = sheets_sync.sincronizar(db)
    assert r["sincronizadas"] == 0
    assert r["pendientes"] == 1          # sigue pendiente, no se perdió
    assert "GOOGLE_CREDENTIALS_PATH" in r["motivo"]


def test_sin_nada_pendiente_no_toca_la_red(db, configurado, monkeypatch):
    def explotar():
        raise AssertionError("no debería abrir la hoja si no hay nada que subir")

    monkeypatch.setattr(sheets_sync, "_abrir_hoja", explotar)
    r = sheets_sync.sincronizar(db)
    assert r == {"sincronizadas": 0, "pendientes": 0, "motivo": ""}


def test_sincroniza_y_marca_las_operaciones(db, configurado, monkeypatch):
    hoja = HojaFalsa(primera_fila=sheets_sync.ENCABEZADOS)
    monkeypatch.setattr(sheets_sync, "_abrir_hoja", lambda: hoja)
    t = _trade(db)

    r = sheets_sync.sincronizar(db)

    assert r["sincronizadas"] == 1 and r["pendientes"] == 0 and r["motivo"] == ""
    assert len(hoja.filas) == 1
    db.refresh(t)
    assert t.sincronizado_sheets is True


def test_un_segundo_click_no_duplica_filas(db, configurado, monkeypatch):
    """Criterio de aceptación de la Tarea 6.2."""
    hoja = HojaFalsa(primera_fila=sheets_sync.ENCABEZADOS)
    monkeypatch.setattr(sheets_sync, "_abrir_hoja", lambda: hoja)
    _trade(db)

    primera = sheets_sync.sincronizar(db)
    segunda = sheets_sync.sincronizar(db)

    assert primera["sincronizadas"] == 1
    assert segunda["sincronizadas"] == 0
    assert len(hoja.filas) == 1, "la segunda corrida duplicó la fila"


def test_si_falla_la_escritura_no_marca_nada_y_se_puede_reintentar(
    db, configurado, monkeypatch
):
    """Marcar antes de escribir dejaría la hoja incompleta para siempre."""
    rota = HojaFalsa(primera_fila=sheets_sync.ENCABEZADOS, falla_al_escribir=True)
    monkeypatch.setattr(sheets_sync, "_abrir_hoja", lambda: rota)
    t = _trade(db)

    r = sheets_sync.sincronizar(db)
    assert r["sincronizadas"] == 0 and r["pendientes"] == 1
    assert "No se pudo escribir" in r["motivo"]
    db.refresh(t)
    assert t.sincronizado_sheets is False

    # Con la hoja sana, el reintento la sube.
    sana = HojaFalsa(primera_fila=sheets_sync.ENCABEZADOS)
    monkeypatch.setattr(sheets_sync, "_abrir_hoja", lambda: sana)
    assert sheets_sync.sincronizar(db)["sincronizadas"] == 1


def test_nunca_propaga_una_excepcion(db, configurado, monkeypatch):
    """Regla de CLAUDE.md: los módulos de datos externos no rompen el endpoint."""
    def explotar():
        raise RuntimeError("Google devolvió 500")

    monkeypatch.setattr(sheets_sync, "_abrir_hoja", explotar)
    _trade(db)
    r = sheets_sync.sincronizar(db)      # no debe levantar
    assert r["sincronizadas"] == 0 and r["motivo"]


def test_escribe_los_encabezados_si_la_hoja_esta_vacia(db, configurado, monkeypatch):
    vacia = HojaFalsa(primera_fila=[])
    monkeypatch.setattr(sheets_sync, "_abrir_hoja", lambda: vacia)
    _trade(db)

    sheets_sync.sincronizar(db)
    assert vacia.encabezados_escritos == sheets_sync.ENCABEZADOS


def test_no_reescribe_los_encabezados_si_ya_estan(db, configurado, monkeypatch):
    hoja = HojaFalsa(primera_fila=sheets_sync.ENCABEZADOS)
    monkeypatch.setattr(sheets_sync, "_abrir_hoja", lambda: hoja)
    _trade(db)

    sheets_sync.sincronizar(db)
    assert hoja.encabezados_escritos is None


def test_sube_varias_en_una_sola_llamada(db, configurado, monkeypatch):
    """La cuota de Sheets es de 60 escrituras/min: hay que ir en lote."""
    hoja = HojaFalsa(primera_fila=sheets_sync.ENCABEZADOS)
    llamadas = {"n": 0}
    original = hoja.append_rows

    def contar(filas, value_input_option=None):
        llamadas["n"] += 1
        original(filas, value_input_option=value_input_option)

    hoja.append_rows = contar
    monkeypatch.setattr(sheets_sync, "_abrir_hoja", lambda: hoja)
    for i in range(5):
        _trade(db, ticker=f"T{i}")

    r = sheets_sync.sincronizar(db)
    assert r["sincronizadas"] == 5
    assert llamadas["n"] == 1, "debería ser una sola llamada en lote"


# ---------- Estado ----------


def test_estado_reporta_pendientes_sin_tocar_la_red(db, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CREDENTIALS_PATH", "")
    _trade(db)
    e = sheets_sync.estado(db)
    assert e["configurado"] is False and e["pendientes"] == 1 and e["motivo"]
