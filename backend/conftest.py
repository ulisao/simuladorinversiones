"""
Configuración mínima de pytest: asegura que `backend/` esté en sys.path para que
los tests puedan importar `from app.calculations import ...` sin instalar el
paquete. Correr siempre desde `backend/`:

    ./venv/Scripts/python.exe -m pytest tests/ -v
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest


@pytest.fixture(autouse=True)
def _auth_apagada_por_defecto(monkeypatch):
    """Apaga la API key en toda la suite salvo donde se la prueba a propósito.

    La API falla cerrada: sin `API_KEY` responde 503. Eso es correcto en
    producción, pero haría que los ~40 tests que le pegan a un endpoint tuvieran
    que arrastrar un header que no es lo que están probando.

    `tests/test_auth.py` vuelve a encenderla con sus propias fixtures — que corren
    después de esta y pisan el valor — así que la protección sí queda cubierta.
    """
    from app import config

    monkeypatch.setattr(config, "API_AUTH_DESHABILITADA", True, raising=False)
