"""
Tests del orquestador de señales de bonos (`app/bond_signals.py`, Tarea 9.4).

Todo offline: `IOLClient` se reemplaza por un doble que devuelve payloads con la
forma real de la API (verificada el 2026-09-07), y el sentimiento de noticias, el
histórico de Yahoo y el contexto de smart money se mockean. Ningún test de este
archivo le pega a internet.

El caso que más importa es el de las puntas ausentes: fuera del horario de rueda
IOL devuelve `"puntas": []`, y el chequeo de spread tiene que **degradar sin
bloquear** en vez de vetar todo el universo.
"""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from app import bond_signals
from app import broker_iol
from app import config


# ---------- Dobles de la API de IOL ----------


def cotizacion(precio=85300.0, puntas=None, moneda="peso_Argentino", **extra):
    """Payload de `/api/v2/bCBA/Titulos/<X>/Cotizacion` con la forma real."""
    base = {
        "ultimoPrecio": precio,
        "variacion": 0.0,
        "apertura": precio,
        "maximo": precio * 1.002,
        "minimo": precio * 0.998,
        "fechaHora": "2026-09-04T17:00:06.943",
        "tendencia": "mantiene",
        "cierreAnterior": precio,
        "montoOperado": 88946163276.5,
        "moneda": moneda,
        "puntas": [] if puntas is None else puntas,
        "cantidadOperaciones": 30923,
        "descripcionTitulo": "Bono Rep. Argentina Usd Step Up 2030",
        "plazo": "T1",
        "laminaMinima": 1,
        "lote": 100,
    }
    base.update(extra)
    return base


def punta(bid, ask):
    return [
        {
            "cantidadCompra": 1000.0,
            "precioCompra": bid,
            "precioVenta": ask,
            "cantidadVenta": 1000.0,
        }
    ]


class ClienteFalso:
    """`IOLClient` de mentira. Registra los símbolos consultados."""

    def __init__(self, cotizaciones=None, configurado=True, error_login=None):
        self.cotizaciones = cotizaciones or {}
        self.esta_configurado = configurado
        self.error_login = error_login
        self.consultados = []
        self.logins = 0

    def get_headers(self):
        self.logins += 1
        if self.error_login is not None:
            raise self.error_login
        return {"Authorization": "Bearer falso"}

    def get_cotizacion(self, simbolo, mercado="bCBA"):
        self.consultados.append(simbolo)
        valor = self.cotizaciones.get(simbolo, cotizacion())
        if isinstance(valor, Exception):
            raise valor
        if callable(valor):
            return valor()
        return valor


def serie_bono(base=100.0, pendiente=0.2, n=60):
    """Serie alcista, para que el filtro de tendencia (precio >= EMA20) pase."""
    idx = pd.date_range("2026-06-01", periods=n, freq="B")
    close = base + pendiente * np.arange(n)
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


SENTIMIENTO_OK = {
    "simbolo": "AL30",
    "veto": False,
    "score": 0.18,
    "motivo": "Sentimiento Deuda Favorable (+0.18)",
    "titulares": [],
    "url_feed": "https://news.google.com/rss/search?q=AL30",
    "modelo_disponible": True,
}

SENTIMIENTO_VETO = {
    **SENTIMIENTO_OK,
    "veto": True,
    "score": -1.0,
    "motivo": "VETO CISNE NEGRO: Palabra crítica 'default' detectada en 'Riesgo de default'",
}


def _sin_red(monkeypatch, *, sentimiento=None, historico=None, espia=None):
    """Reemplaza todas las dependencias externas de `bond_signals` por mocks."""

    def _sentimiento(simbolo):
        if espia is not None:
            espia.append(("sentimiento", simbolo))
        if callable(sentimiento):
            return sentimiento(simbolo)
        return sentimiento if sentimiento is not None else dict(SENTIMIENTO_OK)

    def _historico(simbolo):
        if espia is not None:
            espia.append(("historico", simbolo))
        return historico

    def _contexto(ticker_yf, es_bono=False):
        if espia is not None:
            espia.append(("smart_money", ticker_yf))
        return {
            "rvol": 1.2,
            "es_acumulacion": False,
            "insiders_detectados": False,
            "insiders_detalle": "No aplica",
        }

    monkeypatch.setattr(
        bond_signals.risk_filters, "estado_sentimiento_bonos", _sentimiento
    )
    monkeypatch.setattr(bond_signals, "_historico", _historico)
    monkeypatch.setattr(bond_signals.smart_money, "contexto_smart_money", _contexto)


# Fecha fuera de toda ventana de corte (los soberanos cortan en enero y julio, y
# el veto es del día 1 al 12): 20 de marzo no cae en ninguna.
FUERA_DE_CORTE = datetime(2027, 3, 20)

# 5 de enero: mes de corte de AL30/GD30/... y día dentro de la ventana 1-12.
EN_CORTE = datetime(2027, 1, 5)


# ---------- Candidato válido ----------


def test_candidato_valido_con_precio_real_de_iol(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=85300.0, puntas=punta(85200.0, 85400.0))})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert salida["veto_global"] is None
    assert salida["iol"]["disponible"] is True
    assert salida["descartados"] == []
    assert len(salida["candidatos"]) == 1

    candidato = salida["candidatos"][0]
    assert candidato["simbolo"] == "AL30"
    assert candidato["tipo"] == bond_signals.TIPO_SOBERANO
    assert candidato["precio_entrada"] == 85300.0
    assert candidato["stop_loss"] < candidato["precio_entrada"] < candidato["take_profit"]
    assert candidato["moneda"] == "peso_Argentino"
    assert candidato["fecha_hora"] == "2026-09-04T17:00:06.943"
    assert candidato["lote"] == 100.0
    assert candidato["spread_disponible"] is True
    assert candidato["bid"] == 85200.0 and candidato["ask"] == 85400.0
    assert candidato["sentimiento_score"] == 0.18
    assert candidato["rvol"] == 1.2


def test_el_stop_respeta_el_tope_estricto_de_config(monkeypatch):
    """Sin histórico, el stop va al tope de `config.STOP_LOSS_MAX_PCT`."""
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0)})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )
    candidato = salida["candidatos"][0]

    assert candidato["datos_limitados"] is True
    assert candidato["stop_loss"] == round(100.0 * (1 - config.STOP_LOSS_MAX_PCT), 2)
    assert candidato["pct_riesgo"] == pytest.approx(config.STOP_LOSS_MAX_PCT * 100, abs=0.01)


def test_con_historico_calcula_ema20_y_atr(monkeypatch):
    _sin_red(monkeypatch, historico=serie_bono())
    # El último cierre de la serie está en 100 + 0.2*59 = 111.8; entrar arriba
    # deja el precio por encima de la EMA20 y el filtro de tendencia pasa.
    cliente = ClienteFalso({"AL30": cotizacion(precio=112.0)})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )
    candidato = salida["candidatos"][0]

    assert candidato["datos_limitados"] is False
    assert candidato["ema20"] is not None
    assert candidato["atr"] is not None


# ---------- Veto por ventana de corte de cupón ----------


def test_veto_por_corte_de_cupon_no_toca_la_red(monkeypatch):
    espia = []
    _sin_red(monkeypatch, espia=espia)
    cliente = ClienteFalso()

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=EN_CORTE
    )

    assert salida["candidatos"] == []
    assert len(salida["descartados"]) == 1
    descartado = salida["descartados"][0]
    assert descartado["simbolo"] == "AL30"
    assert descartado["etapa"] == bond_signals.ETAPA_CUPON
    assert "CUPÓN" in descartado["motivo"].upper()

    # El atajo tiene que ahorrar las llamadas de red: ni noticias ni cotización.
    assert espia == []
    assert cliente.consultados == []


def test_bono_sin_calendario_cargado_pasa_la_ventana_de_corte(monkeypatch):
    """Los provinciales no están en MESES_CORTE_CUPON: nunca los veta el calendario."""
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"CO26": cotizacion(precio=1000.0)})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["CO26"], cliente=cliente, ahora=EN_CORTE
    )

    assert len(salida["candidatos"]) == 1
    assert salida["candidatos"][0]["tipo"] == bond_signals.TIPO_PROVINCIAL


# ---------- Veto por spread bid/ask ----------


def test_veto_por_spread_ancho(monkeypatch):
    _sin_red(monkeypatch)
    # Spread de 2% sobre 100: muy por encima del 0,6% de SPREAD_BID_ASK_MAX.
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0, puntas=punta(99.0, 101.0))})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert salida["candidatos"] == []
    descartado = salida["descartados"][0]
    assert descartado["etapa"] == bond_signals.ETAPA_SPREAD
    assert "SPREAD" in descartado["motivo"].upper()
    assert f"{config.SPREAD_BID_ASK_MAX * 100:.2f}" in descartado["motivo"]


def test_spread_justo_debajo_del_limite_pasa(monkeypatch):
    _sin_red(monkeypatch)
    # 0,4% de spread sobre 100.
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0, puntas=punta(99.8, 100.2))})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert len(salida["candidatos"]) == 1
    assert salida["candidatos"][0]["spread_pct"] == pytest.approx(0.4, abs=0.001)


# ---------- Spread no verificable: NO bloquea ----------


def test_sin_puntas_el_spread_no_bloquea(monkeypatch):
    """Fuera del horario de rueda IOL manda `puntas: []`. No se veta por eso."""
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=85300.0, puntas=[])})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert salida["descartados"] == []
    candidato = salida["candidatos"][0]
    assert candidato["spread_disponible"] is False
    assert candidato["spread"] is None
    assert candidato["spread_pct"] is None
    assert candidato["bid"] is None and candidato["ask"] is None
    assert "no bloqueante" in candidato["spread_nota"].lower()


def test_puntas_en_cero_tampoco_bloquean(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0, puntas=punta(0.0, 0.0))})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert len(salida["candidatos"]) == 1
    assert salida["candidatos"][0]["spread_disponible"] is False


def test_chequear_spread_directo_sin_puntas():
    pasa, detalle = bond_signals.chequear_spread(cotizacion(puntas=[]), 85300.0)

    assert pasa is True
    assert detalle["disponible"] is False
    # Sin puntas no hay veto, así que no puede haber motivo.
    assert "motivo" not in detalle


# ---------- Veto por noticias de deuda ----------


def test_veto_por_noticias_de_deuda(monkeypatch):
    _sin_red(monkeypatch, sentimiento=dict(SENTIMIENTO_VETO))
    cliente = ClienteFalso()

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert salida["candidatos"] == []
    descartado = salida["descartados"][0]
    assert descartado["etapa"] == bond_signals.ETAPA_NOTICIAS
    assert "CISNE NEGRO" in descartado["motivo"].upper()
    # El veto de noticias corta antes de pedirle la cotización a IOL.
    assert cliente.consultados == []


# ---------- Cotización ausente o rota ----------


def test_bono_sin_ultimo_precio_se_descarta_con_motivo(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=0.0)})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    descartado = salida["descartados"][0]
    assert descartado["etapa"] == bond_signals.ETAPA_COTIZACION
    assert "SIN COTIZACIÓN" in descartado["motivo"].upper()


def test_error_de_iol_en_un_bono_se_descarta_ese_bono(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso(
        {
            "AL30": broker_iol.IOLError("IOL respondió HTTP 404 en /Titulos/AL30/Cotizacion"),
            "GD30": cotizacion(precio=90000.0),
        }
    )

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30", "GD30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert [c["simbolo"] for c in salida["candidatos"]] == ["GD30"]
    assert salida["descartados"][0]["etapa"] == bond_signals.ETAPA_COTIZACION
    assert "404" in salida["descartados"][0]["motivo"]


# ---------- Un bono roto no frena a los demás ----------


def test_un_bono_que_explota_no_tumba_el_escaneo(monkeypatch):
    def sentimiento(simbolo):
        if simbolo == "GD30":
            raise RuntimeError("boom inesperado")
        return dict(SENTIMIENTO_OK)

    _sin_red(monkeypatch, sentimiento=sentimiento)
    cliente = ClienteFalso()

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30", "GD30", "AL35"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert [c["simbolo"] for c in salida["candidatos"]] == ["AL30", "AL35"]
    assert len(salida["descartados"]) == 1
    descartado = salida["descartados"][0]
    assert descartado["simbolo"] == "GD30"
    assert descartado["etapa"] == bond_signals.ETAPA_ERROR
    assert "boom inesperado" in descartado["motivo"]


def test_un_historico_roto_no_tumba_el_escaneo(monkeypatch):
    """`_historico` traga el error de Yahoo: el bono sigue, con datos limitados.

    Acá NO se mockea `_historico` (es justamente lo que se quiere probar): se
    rompe `market_data.get_history`, que es lo que hace Yahoo con los bonos
    argentinos casi siempre.
    """

    def revienta(*a, **k):
        raise bond_signals.market_data.MarketDataError("Yahoo sin datos para AL30.BA")

    monkeypatch.setattr(
        bond_signals.risk_filters,
        "estado_sentimiento_bonos",
        lambda s: dict(SENTIMIENTO_OK),
    )
    monkeypatch.setattr(bond_signals.market_data, "get_history", revienta)
    monkeypatch.setattr(
        bond_signals.smart_money,
        "contexto_smart_money",
        lambda t, es_bono=False: {
            "rvol": 1.0,
            "es_acumulacion": False,
            "insiders_detectados": False,
            "insiders_detalle": "No aplica",
        },
    )
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0)})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert len(salida["candidatos"]) == 1
    assert salida["candidatos"][0]["datos_limitados"] is True


# ---------- IOL caído o sin credenciales ----------


def test_login_fallido_devuelve_respuesta_controlada(monkeypatch):
    espia = []
    _sin_red(monkeypatch, espia=espia)
    cliente = ClienteFalso(error_login=broker_iol.IOLError("IOL rechazó la autenticación (HTTP 400)"))

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30", "GD30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert salida["candidatos"] == []
    assert salida["descartados"] == []
    assert salida["veto_global"] is not None
    assert "VETO IOL" in salida["veto_global"]
    assert "HTTP 400" in salida["veto_global"]
    assert salida["iol"] == {
        "configurado": True,
        "disponible": False,
        "motivo": salida["veto_global"],
    }
    # No se evaluó ningún bono.
    assert espia == []
    assert cliente.consultados == []


def test_sin_credenciales_devuelve_respuesta_controlada(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso(configurado=False)

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert salida["candidatos"] == []
    assert salida["veto_global"] is not None
    assert "IOL_USERNAME" in salida["veto_global"]
    assert salida["iol"]["configurado"] is False
    assert cliente.logins == 0


def test_error_inesperado_autenticando_no_explota(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso(error_login=ValueError("algo raro"))

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert salida["veto_global"] is not None
    assert "algo raro" in salida["veto_global"]
    assert salida["candidatos"] == []


def test_usa_el_singleton_de_broker_iol_si_no_se_inyecta_cliente(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0)})
    monkeypatch.setattr(bond_signals.broker_iol, "get_client", lambda: cliente)

    salida = bond_signals.escanear_senales_bonos(bonos=["AL30"], ahora=FUERA_DE_CORTE)

    assert len(salida["candidatos"]) == 1
    assert cliente.logins == 1


# ---------- Forma de la respuesta ----------


def test_universo_por_defecto_es_el_de_config(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso()

    salida = bond_signals.escanear_senales_bonos(cliente=cliente, ahora=FUERA_DE_CORTE)

    assert salida["universo"] == list(config.UNIVERSO_BONOS)
    assert len(salida["candidatos"]) + len(salida["descartados"]) == len(
        config.UNIVERSO_BONOS
    )


def test_respuesta_trae_todas_las_claves_del_contrato(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0)})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert set(salida) == {
        "generado",
        "universo",
        "nota_precios",
        "veto_global",
        "iol",
        "candidatos",
        "descartados",
    }
    assert set(salida["candidatos"][0]) == {
        "simbolo",
        "tipo",
        "precio_entrada",
        "stop_loss",
        "take_profit",
        "pct_riesgo",
        "ratio_rb",
        "moneda",
        "fecha_hora",
        "lote",
        "lamina_minima",
        "datos_limitados",
        "ema20",
        "atr",
        "detalle",
        "spread",
        "spread_pct",
        "spread_disponible",
        "spread_nota",
        "bid",
        "ask",
        "sentimiento_score",
        "sentimiento_motivo",
        "rvol",
        "es_acumulacion",
    }


def test_simbolo_vacio_en_el_universo_no_rompe(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0)})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["", "AL30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert [c["simbolo"] for c in salida["candidatos"]] == ["AL30"]
    assert salida["descartados"][0]["etapa"] == bond_signals.ETAPA_ERROR


def test_simbolo_en_minuscula_se_normaliza(monkeypatch):
    _sin_red(monkeypatch)
    cliente = ClienteFalso({"AL30": cotizacion(precio=100.0)})

    salida = bond_signals.escanear_senales_bonos(
        bonos=["al30"], cliente=cliente, ahora=FUERA_DE_CORTE
    )

    assert cliente.consultados == ["AL30"]
    assert salida["candidatos"][0]["simbolo"] == "AL30"
