"""
Tests de la ingesta de filings 13F (Tarea 5.3).

Sin red: el XML de las information tables se arma a mano y las descargas están
mockeadas. Lo que más importa verificar acá:

* que se **agregue por CUSIP** (una misma tenencia aparece una vez por manager),
* que se **normalice la escala** de los filings que declaran `value` en miles
  (pasa de verdad: Baupost lo hace en el trimestre 2026-06-30),
* que un fondo caído no tumbe el barrido de los demás.
"""
import json

import pytest

from app import config, edgar_13f


NS = 'xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"'


def _tabla(filas):
    """Information table sintética. `filas` = (nombre, cusip, valor, acciones[, tipo])."""
    cuerpo = ""
    for fila in filas:
        nombre, cusip, valor, acciones = fila[:4]
        tipo = fila[4] if len(fila) > 4 else "SH"
        cuerpo += f"""
  <infoTable>
    <nameOfIssuer>{nombre}</nameOfIssuer>
    <cusip>{cusip}</cusip>
    <value>{valor}</value>
    <shrsOrPrnAmt>
      <sshPrnamt>{acciones}</sshPrnamt>
      <sshPrnamtType>{tipo}</sshPrnamtType>
    </shrsOrPrnAmt>
  </infoTable>"""
    return f"<informationTable {NS}>{cuerpo}\n</informationTable>"


CUSIP_AAPL = "037833100"
CUSIP_KO = "191216100"
CUSIP_DESCONOCIDO = "999999999"


# ---------- Parseo y agregación ----------


def test_una_cusip_repetida_se_suma():
    """Berkshire declara la misma tenencia una vez por manager: hay que sumar."""
    xml = _tabla([
        ("APPLE INC", CUSIP_AAPL, 300_000_000, 1_000_000),
        ("APPLE INC", CUSIP_AAPL, 150_000_000, 500_000),
        ("APPLE INC", CUSIP_AAPL, 60_000_000, 200_000),
    ])

    posiciones = edgar_13f.parsear_information_table(xml)

    assert len(posiciones) == 1, "tres filas de AAPL son UNA posición"
    assert posiciones[CUSIP_AAPL]["valor"] == 510_000_000
    assert posiciones[CUSIP_AAPL]["acciones"] == 1_700_000


def test_el_precio_implicito_sale_bien_despues_de_agregar():
    xml = _tabla([
        ("APPLE INC", CUSIP_AAPL, 200_000_000, 1_000_000),
        ("APPLE INC", CUSIP_AAPL, 100_000_000, 500_000),
    ])

    p = edgar_13f.parsear_information_table(xml)[CUSIP_AAPL]

    assert p["valor"] / p["acciones"] == pytest.approx(200.0)


def test_una_fila_con_numeros_rotos_se_saltea():
    xml = _tabla([("APPLE INC", CUSIP_AAPL, 1_000_000, 10_000)]).replace(
        "<value>1000000</value>", "<value>no-es-un-numero</value>"
    )

    assert edgar_13f.parsear_information_table(xml) == {}


# ---------- Normalización de escala ----------


def test_un_filing_en_dolares_no_se_toca():
    xml = _tabla([
        ("APPLE INC", CUSIP_AAPL, 289_000_000, 1_000_000),   # $289/acción
        ("COCA COLA CO", CUSIP_KO, 81_000_000, 1_000_000),   # $81/acción
    ])

    assert edgar_13f.parsear_information_table(xml)[CUSIP_AAPL]["valor"] == 289_000_000


def test_un_filing_en_miles_se_multiplica_por_mil():
    """El caso real de Baupost: precios implícitos de centavos."""
    xml = _tabla([
        ("AMAZON COM INC", CUSIP_AAPL, 238_000, 1_000_000),  # implica $0,24
        ("COCA COLA CO", CUSIP_KO, 81_000, 1_000_000),       # implica $0,08
    ])

    posiciones = edgar_13f.parsear_information_table(xml)

    assert posiciones[CUSIP_AAPL]["valor"] == 238_000_000
    assert posiciones[CUSIP_AAPL]["valor"] / posiciones[CUSIP_AAPL]["acciones"] == pytest.approx(238.0)


def test_la_escala_se_decide_con_la_mediana_no_con_una_posicion():
    """Una sola tenencia rara no puede arrastrar la decisión de todo el filing."""
    filas = [(f"EMPRESA {i}", f"{i:09d}", 100_000_000, 1_000_000) for i in range(5)]
    filas.append(("PENNY STOCK", CUSIP_KO, 100, 1_000_000))  # implica $0,0001

    posiciones = edgar_13f.parsear_information_table(_tabla(filas))

    assert edgar_13f.factor_de_escala(posiciones) == 1.0
    assert posiciones[CUSIP_KO]["valor"] == 100, "no se reescaló nada"


def test_las_posiciones_en_valor_nominal_no_definen_la_escala():
    """Las filas PRN son deuda: su 'precio' es por dólar de nominal, no por acción."""
    xml = _tabla([
        ("APPLE INC", CUSIP_AAPL, 289_000_000, 1_000_000, "SH"),
        ("BONO CORP", CUSIP_KO, 1_000_000, 1_000_000, "PRN"),  # implica 1,0
    ])

    assert edgar_13f.factor_de_escala(edgar_13f.parsear_information_table(xml)) == 1.0


def test_un_filing_sin_acciones_no_rompe():
    xml = _tabla([("BONO CORP", CUSIP_KO, 1_000_000, 0)])

    assert edgar_13f.factor_de_escala(edgar_13f.parsear_information_table(xml)) == 1.0


# ---------- Comparación entre trimestres ----------


def _pos(cusip, valor, acciones, nombre="X"):
    return {cusip: {"cusip": cusip, "nombre": nombre, "valor": valor,
                    "acciones": acciones, "tipo": "SH"}}


def test_una_posicion_que_no_estaba_es_nueva():
    movs = edgar_13f.comparar(_pos(CUSIP_AAPL, 1000, 10), {})

    assert movs[0]["tipo"] == edgar_13f.NUEVA
    assert movs[0]["ticker"] == "AAPL"


def test_una_posicion_que_desaparecio_es_cierre():
    movs = edgar_13f.comparar({}, _pos(CUSIP_AAPL, 1000, 10))

    assert movs[0]["tipo"] == edgar_13f.CIERRE
    assert movs[0]["acciones"] == 0


def test_mas_acciones_es_aumento_y_menos_es_reduccion():
    assert edgar_13f.comparar(_pos(CUSIP_AAPL, 2000, 20), _pos(CUSIP_AAPL, 1000, 10))[0]["tipo"] == edgar_13f.AUMENTO
    assert edgar_13f.comparar(_pos(CUSIP_AAPL, 500, 5), _pos(CUSIP_AAPL, 1000, 10))[0]["tipo"] == edgar_13f.REDUCCION


def test_la_misma_cantidad_es_sin_cambio():
    """El valor cambia con el precio de mercado; lo que define el movimiento son las acciones."""
    movs = edgar_13f.comparar(_pos(CUSIP_AAPL, 5000, 10), _pos(CUSIP_AAPL, 1000, 10))

    assert movs[0]["tipo"] == edgar_13f.SIN_CAMBIO


def test_las_cusip_fuera_del_mapeo_se_ignoran():
    """La Tarea 5.3 pide tickers, no CUSIPs sueltos."""
    actual = {**_pos(CUSIP_AAPL, 1000, 10), **_pos(CUSIP_DESCONOCIDO, 9999, 99)}

    movs = edgar_13f.comparar(actual, {})

    assert [m["ticker"] for m in movs] == ["AAPL"]


def test_el_peso_en_cartera_usa_el_total_del_filing():
    actual = {**_pos(CUSIP_AAPL, 250, 10), **_pos(CUSIP_DESCONOCIDO, 750, 30)}

    movs = edgar_13f.comparar(actual, {})

    assert movs[0]["peso_cartera"] == pytest.approx(0.25), "el total incluye lo no mapeado"


def test_los_movimientos_salen_ordenados_por_peso():
    actual = {**_pos(CUSIP_AAPL, 100, 10), **_pos(CUSIP_KO, 900, 10)}

    movs = edgar_13f.comparar(actual, {})

    assert [m["ticker"] for m in movs] == ["KO", "AAPL"]


# ---------- Barrido completo ----------


@pytest.fixture
def sin_red(monkeypatch, tmp_path):
    """Filings sintéticos servidos desde memoria, cache en un directorio temporal."""
    monkeypatch.setattr(config, "DIR_DATOS_13F", str(tmp_path))

    filings = {
        "111": [
            {"accession": "acc2", "reporte": "2026-06-30", "presentado": "2026-08-14"},
            {"accession": "acc1", "reporte": "2026-03-31", "presentado": "2026-05-15"},
        ],
    }
    tablas = {
        "acc2": _tabla([("APPLE INC", CUSIP_AAPL, 200_000_000, 1_000_000)]),
        "acc1": _tabla([("APPLE INC", CUSIP_AAPL, 100_000_000, 500_000)]),
    }

    monkeypatch.setattr(edgar_13f, "ultimos_filings", lambda cik, cantidad=2: filings.get(cik, []))
    monkeypatch.setattr(edgar_13f, "_url_information_table", lambda cik, acc: acc)

    class RespuestaFalsa:
        def __init__(self, texto):
            self.text = texto

    monkeypatch.setattr(edgar_13f, "_get", lambda url: RespuestaFalsa(tablas[url]))
    return tmp_path


def test_barrido_completo(sin_red):
    r = edgar_13f.descargar_movimientos({"111": "Fondo de prueba"})

    assert r["errores"] == []
    assert r["fondos"][0]["reporte"] == "2026-06-30"
    assert r["movimientos"][0]["ticker"] == "AAPL"
    assert r["movimientos"][0]["tipo"] == edgar_13f.AUMENTO
    assert r["movimientos"][0]["fondo"] == "Fondo de prueba"


def test_el_barrido_deja_los_filings_cacheados(sin_red):
    edgar_13f.descargar_movimientos({"111": "Fondo de prueba"})

    guardado = sin_red / "111" / "2026-06-30.json"
    assert guardado.exists()
    assert json.loads(guardado.read_text(encoding="utf-8"))[CUSIP_AAPL]["acciones"] == 1_000_000


def test_un_fondo_con_un_solo_filing_se_reporta_como_error(monkeypatch, sin_red):
    monkeypatch.setattr(
        edgar_13f, "ultimos_filings",
        lambda cik, cantidad=2: [{"accession": "acc2", "reporte": "2026-06-30", "presentado": "x"}],
    )

    r = edgar_13f.descargar_movimientos({"111": "Fondo nuevo"})

    assert r["movimientos"] == []
    assert "dos 13F-HR" in r["errores"][0]


def test_un_fondo_caido_no_frena_a_los_demas(monkeypatch, sin_red):
    original = edgar_13f.ultimos_filings

    def a_veces_falla(cik, cantidad=2):
        if cik == "222":
            raise ConnectionError("EDGAR no responde")
        return original(cik, cantidad)

    monkeypatch.setattr(edgar_13f, "ultimos_filings", a_veces_falla)

    r = edgar_13f.descargar_movimientos({"222": "Fondo roto", "111": "Fondo sano"})

    assert len(r["movimientos"]) == 1, "el fondo sano se procesó igual"
    assert "EDGAR no responde" in r["errores"][0]
