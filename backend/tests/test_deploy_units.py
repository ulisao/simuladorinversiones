"""Tests de las units systemd (Tarea 10.3).

No se puede correr `systemd-analyze verify` desde Windows ni desde CI sin
systemd, así que se valida lo que sí se puede validar estáticamente: que los
archivos parseen, que tengan las directivas que pide la tarea (`Restart=always`,
`RestartSec=10`) y — lo importante — que **ninguna credencial quede embebida**
en la unit, porque `systemctl show` las imprimiría en el journal.
"""
import configparser
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
UNITS = ["tradingbot-api.service", "tradingbot-scanner.service"]


def _parsear(nombre: str) -> configparser.ConfigParser:
    # systemd admite claves repetidas (After=, Environment=): strict=False.
    cp = configparser.ConfigParser(strict=False)
    leidos = cp.read(DEPLOY / nombre, encoding="utf-8")
    assert leidos, f"no se pudo leer {nombre}"
    return cp


@pytest.fixture(params=UNITS)
def unit(request):
    return request.param, _parsear(request.param), (DEPLOY / request.param).read_text(
        encoding="utf-8"
    )


def test_las_units_existen():
    for nombre in UNITS:
        assert (DEPLOY / nombre).is_file(), f"falta deploy/{nombre}"


def test_secciones_obligatorias(unit):
    nombre, cp, _ = unit
    for seccion in ("Unit", "Service", "Install"):
        assert cp.has_section(seccion), f"{nombre}: falta [{seccion}]"


def test_reinicia_solo(unit):
    """El criterio de la Tarea 10.3: que se levanten solos ante cualquier corte."""
    nombre, cp, _ = unit
    assert cp.get("Service", "Restart") == "always", nombre
    assert cp.get("Service", "RestartSec") == "10", nombre
    assert cp.get("Install", "WantedBy") == "multi-user.target", nombre


def test_execstart_absoluto_y_en_una_linea(unit):
    nombre, cp, _ = unit
    ejec = cp.get("Service", "ExecStart")
    assert ejec.startswith("/"), f"{nombre}: systemd exige ruta absoluta en ExecStart"
    assert "\\" not in ejec, f"{nombre}: ExecStart partido en varias lineas"


def test_corre_sin_privilegios(unit):
    nombre, cp, _ = unit
    usuario = cp.get("Service", "User")
    assert usuario and usuario != "root", f"{nombre}: no puede correr como root"
    assert cp.get("Service", "NoNewPrivileges") == "true", nombre


def test_credenciales_por_archivo_nunca_embebidas(unit):
    """`systemctl show` imprime todo Environment=; el .env va por EnvironmentFile=."""
    nombre, cp, texto = unit
    assert cp.get("Service", "EnvironmentFile").endswith("/.env"), nombre
    for clave in ("IOL_USERNAME", "IOL_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        assert f"Environment={clave}" not in texto, f"{nombre}: {clave} embebida en la unit"


def test_zona_horaria_argentina(unit):
    """`schedule` usa el reloj del proceso: sin esto el reporte semanal sale a otra hora."""
    _, _, texto = unit
    assert "Environment=TZ=America/Argentina/Buenos_Aires" in texto


def test_la_api_no_escucha_hacia_afuera():
    """main.py no tiene auth y su CORS es '*': bindear 0.0.0.0 expondria /iol/saldo."""
    cp = _parsear("tradingbot-api.service")
    ejec = cp.get("Service", "ExecStart")
    assert "--host 127.0.0.1" in ejec
    assert "0.0.0.0" not in ejec


def test_el_scanner_corre_el_job_correcto():
    cp = _parsear("tradingbot-scanner.service")
    assert cp.get("Service", "ExecStart").endswith("scanner_job.py")
    # Sin esto, journalctl -f no muestra nada hasta que Python vacia el buffer.
    assert "Environment=PYTHONUNBUFFERED=1" in (DEPLOY / "tradingbot-scanner.service").read_text(
        encoding="utf-8"
    )
