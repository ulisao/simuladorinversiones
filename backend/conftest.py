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
