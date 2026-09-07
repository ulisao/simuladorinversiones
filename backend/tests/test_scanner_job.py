"""
Tests del job de escaneo periódico (Tarea 10.1).

Todo mockeado: ni Yahoo Finance ni Telegram. Lo que se verifica es la lógica
propia del job — respetar el horario de rueda, no repetir la misma señal en el
día, reiniciar al cambiar de jornada y respetar la cadencia del monitor de
posiciones cerca del cierre preventivo.
"""
from datetime import datetime, timedelta

import pytest
import pytz

import position_monitor_job
import scanner_job
from app.config import TZ_BYMA


ART = pytz.timezone(TZ_BYMA)

# Lunes 2026-09-07, 12:00 hs ART: en plena rueda.
EN_RUEDA = ART.localize(datetime(2026, 9, 7, 12, 0))
# Sábado 2026-09-05: fuera de rueda.
FIN_DE_SEMANA = ART.localize(datetime(2026, 9, 5, 12, 0))
# Martes siguiente, misma hora.
DIA_SIGUIENTE = ART.localize(datetime(2026, 9, 8, 12, 0))

CANDIDATO_NVDA = {
    "ticker": "NVDA",
    "precio_entrada": 217.55,
    "stop_loss": 211.02,
    "take_profit": 230.6,
    "pct_riesgo": 3.0,
}
CANDIDATO_MELI = {
    "ticker": "MELI",
    "precio_entrada": 1966.25,
    "stop_loss": 1907.26,
    "take_profit": 2084.22,
    "pct_riesgo": 3.0,
}


@pytest.fixture(autouse=True)
def estado_limpio():
    scanner_job.reiniciar_estado()
    scanner_job._ultimo_monitor = None
    yield
    scanner_job.reiniciar_estado()
    scanner_job._ultimo_monitor = None


@pytest.fixture(autouse=True)
def sin_bonos(monkeypatch):
    """Apaga el escaneo de bonos salvo que el test lo pida explícitamente.

    Sin esto, `ciclo_senales` sale a IOL y a FinBERT de verdad en tests que
    están marcados como "sin red" (pasó: la suite se colgó al agregar la 9.4).
    Los tests de bonos mockean `bond_signals.escanear_senales_bonos` y prenden
    el flag ellos mismos.
    """
    monkeypatch.setattr(scanner_job, "ESCANEO_BONOS_HABILITADO", False)


@pytest.fixture
def enviados(monkeypatch):
    """Captura los mensajes que el job manda a Telegram."""
    mensajes = []

    def send_falso(mensaje, parse_mode=None):
        mensajes.append(mensaje)
        return {"enviado": True, "motivo": ""}

    monkeypatch.setattr(scanner_job.notifications, "send_telegram", send_falso)
    return mensajes


def _reloj(monkeypatch, momento):
    monkeypatch.setattr(position_monitor_job, "ahora_art", lambda: momento)


def _escaneo(monkeypatch, resultado, contador=None):
    def escanear():
        if contador is not None:
            contador.append(1)
        return resultado

    monkeypatch.setattr(scanner_job.signals, "escanear_senales", escanear)


def _resultado(candidatos, veto=None):
    return {
        "generado": "2026-09-07T12:00:00",
        "universo": ["NVDA", "MELI"],
        "veto_global": veto,
        "vix": {},
        "regimen_mercado": None,
        "candidatos": candidatos,
        "descartados": [],
    }


# ---------- Horario de rueda ----------


def test_fuera_de_rueda_no_escanea(monkeypatch, enviados):
    corridas = []
    _reloj(monkeypatch, FIN_DE_SEMANA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA]), corridas)

    assert scanner_job.ciclo_senales() == []
    assert corridas == [], "ni siquiera se le pega a Yahoo fuera de rueda"
    assert enviados == []


def test_ignorar_horario_permite_probar_con_el_mercado_cerrado(monkeypatch, enviados):
    _reloj(monkeypatch, FIN_DE_SEMANA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA]))

    avisados = scanner_job.ciclo_senales(ignorar_horario=True)

    assert [c["ticker"] for c in avisados] == ["NVDA"]
    assert len(enviados) == 1


# ---------- Deduplicación ----------


def test_notifica_cada_senal_una_sola_vez_por_dia(monkeypatch, enviados):
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA, CANDIDATO_MELI]))

    primera = scanner_job.ciclo_senales()
    segunda = scanner_job.ciclo_senales()

    assert [c["ticker"] for c in primera] == ["NVDA", "MELI"]
    assert segunda == [], "el segundo ciclo no puede repetir lo ya avisado"
    assert len(enviados) == 2


def test_una_senal_nueva_en_el_mismo_dia_si_se_notifica(monkeypatch, enviados):
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA]))
    scanner_job.ciclo_senales()

    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA, CANDIDATO_MELI]))
    segunda = scanner_job.ciclo_senales()

    assert [c["ticker"] for c in segunda] == ["MELI"]
    assert len(enviados) == 2


def test_al_cambiar_el_dia_la_misma_senal_vuelve_a_avisar(monkeypatch, enviados):
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA]))
    scanner_job.ciclo_senales()

    _reloj(monkeypatch, DIA_SIGUIENTE)
    avisados = scanner_job.ciclo_senales()

    assert [c["ticker"] for c in avisados] == ["NVDA"]
    assert len(enviados) == 2


# ---------- Veto global ----------


def test_el_veto_global_se_avisa_una_vez_y_no_notifica_candidatos(monkeypatch, enviados):
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([], veto="VETO VIX: pánico (28.4 > 25.0)"))

    assert scanner_job.ciclo_senales() == []
    assert scanner_job.ciclo_senales() == []

    assert len(enviados) == 1
    assert "VETO VIX" in enviados[0]


def test_un_error_del_escaneo_no_tumba_el_ciclo(monkeypatch, enviados):
    _reloj(monkeypatch, EN_RUEDA)

    def revienta():
        raise RuntimeError("yfinance caído")

    monkeypatch.setattr(scanner_job.signals, "escanear_senales", revienta)

    assert scanner_job.ciclo_senales() == []
    assert enviados == []


# ---------- Monitor de posiciones ----------


def test_el_monitor_respeta_su_cadencia_normal(monkeypatch):
    corridas = []
    _reloj(monkeypatch, EN_RUEDA)
    monkeypatch.setattr(
        position_monitor_job, "ciclo", lambda ignorar_horario=False: corridas.append(1) or []
    )

    scanner_job.ciclo_posiciones()
    scanner_job.ciclo_posiciones()  # un minuto después no llega a los 300 s

    assert len(corridas) == 1

    _reloj(monkeypatch, EN_RUEDA + timedelta(seconds=301))
    scanner_job.ciclo_posiciones()

    assert len(corridas) == 2


def test_cerca_del_cierre_preventivo_el_monitor_corre_cada_minuto(monkeypatch):
    corridas = []
    monkeypatch.setattr(
        position_monitor_job, "ciclo", lambda ignorar_horario=False: corridas.append(1) or []
    )

    # 16:41 ART: dentro de la ventana fina de `position_monitor_job`.
    fino = ART.localize(datetime(2026, 9, 7, 16, 41))
    _reloj(monkeypatch, fino)
    scanner_job.ciclo_posiciones()

    _reloj(monkeypatch, fino + timedelta(seconds=61))
    scanner_job.ciclo_posiciones()

    assert len(corridas) == 2, "a 61 s ya corresponde otro sondeo antes de las 16:50"


def test_un_error_del_monitor_no_tumba_el_ciclo(monkeypatch):
    _reloj(monkeypatch, EN_RUEDA)

    def revienta(ignorar_horario=False):
        raise RuntimeError("base bloqueada")

    monkeypatch.setattr(position_monitor_job, "ciclo", revienta)

    assert scanner_job.ciclo_posiciones() == []


def test_el_ciclo_completo_corre_señales_y_posiciones(monkeypatch, enviados):
    corridas = []
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA]))
    monkeypatch.setattr(
        position_monitor_job, "ciclo", lambda ignorar_horario=False: corridas.append(1) or []
    )

    resumen = scanner_job.ciclo()

    assert [c["ticker"] for c in resumen["senales_notificadas"]] == ["NVDA"]
    assert len(corridas) == 1


# ---------- Programación ----------


def test_programar_registra_los_tres_jobs():
    import schedule

    schedule.clear()
    try:
        scanner_job.programar()
        assert len(schedule.get_jobs()) == 3
    finally:
        schedule.clear()


# ---------- Escaneo de bonos (Tarea 9.4) ----------


BONO_AL30 = {
    "simbolo": "AL30",
    "tipo": "SOBERANO",
    "precio_entrada": 85300.0,
    "stop_loss": 82741.0,
    "take_profit": 90418.0,
    "pct_riesgo": 3.0,
}


def _escaneo_bonos(monkeypatch, candidatos, veto=None):
    monkeypatch.setattr(scanner_job, "ESCANEO_BONOS_HABILITADO", True)
    monkeypatch.setattr(
        scanner_job.bond_signals,
        "escanear_senales_bonos",
        lambda: {
            "generado": "2026-09-07T12:00:00",
            "universo": ["AL30"],
            "veto_global": veto,
            "iol": {"configurado": True, "disponible": veto is None, "motivo": ""},
            "candidatos": candidatos,
            "descartados": [],
        },
    )


def test_el_ciclo_notifica_bonos_ademas_de_cedears(monkeypatch, enviados):
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA]))
    _escaneo_bonos(monkeypatch, [BONO_AL30])

    avisados = scanner_job.ciclo_senales()

    assert len(avisados) == 2, "una señal de CEDEAR y una de bono"
    assert len(enviados) == 2
    assert any("AL30" in m for m in enviados)


def test_un_bono_ya_notificado_no_se_repite(monkeypatch, enviados):
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([]))
    _escaneo_bonos(monkeypatch, [BONO_AL30])

    scanner_job.ciclo_senales()
    segunda = scanner_job.ciclo_senales()

    assert segunda == []
    assert len(enviados) == 1


def test_con_iol_caido_los_bonos_avisan_una_vez_y_no_frenan_los_cedears(monkeypatch, enviados):
    """El escaneo de acciones no depende de IOL: tiene que seguir funcionando."""
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA]))
    _escaneo_bonos(monkeypatch, [], veto="IOL no responde")

    avisados = scanner_job.ciclo_senales()

    assert [c["ticker"] for c in avisados] == ["NVDA"], "el CEDEAR se notificó igual"
    assert any("IOL no responde" in m for m in enviados)

    scanner_job.ciclo_senales()
    assert sum("IOL no responde" in m for m in enviados) == 1, "el veto se avisa una vez"


def test_un_error_escaneando_bonos_no_tumba_el_ciclo(monkeypatch, enviados):
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([CANDIDATO_NVDA]))
    monkeypatch.setattr(scanner_job, "ESCANEO_BONOS_HABILITADO", True)
    monkeypatch.setattr(
        scanner_job.bond_signals,
        "escanear_senales_bonos",
        lambda: (_ for _ in ()).throw(RuntimeError("IOL explotó")),
    )

    avisados = scanner_job.ciclo_senales()

    assert [c["ticker"] for c in avisados] == ["NVDA"]


def test_con_el_flag_apagado_no_se_escanean_bonos(monkeypatch, enviados):
    corridas = []
    _reloj(monkeypatch, EN_RUEDA)
    _escaneo(monkeypatch, _resultado([]))
    monkeypatch.setattr(scanner_job, "ESCANEO_BONOS_HABILITADO", False)
    monkeypatch.setattr(
        scanner_job.bond_signals,
        "escanear_senales_bonos",
        lambda: corridas.append(1) or {},
    )

    scanner_job.ciclo_senales()

    assert corridas == []
