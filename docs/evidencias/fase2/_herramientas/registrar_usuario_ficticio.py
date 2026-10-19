"""Registra una cuenta ficticia por la ruta real POST /auth/register (evidencia de almacenamiento).

    TEST_DATABASE_URL=postgresql://usuario:clave@127.0.0.1:5432/algo_test \\
        backend/.venv/Scripts/python.exe docs/evidencias/fase2/_herramientas/registrar_usuario_ficticio.py

Usa TestClient de FastAPI sobre la aplicación real, sin levantar el servidor ni sus
trabajadores. La contraseña se guarda con bcrypt (security/passwords.py). Se niega a
correr si la base no contiene «test» en su nombre. No imprime el token completo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(RAIZ / "backend" / "src"))

url = (os.getenv("TEST_DATABASE_URL") or "").strip()
if "test" not in url.rsplit("/", 1)[-1]:
    sys.exit("TEST_DATABASE_URL debe apuntar a una base cuyo nombre contenga «test».")
os.environ.update(
    {
        "DATABASE_URL": url,
        "JWT_SECRET": "clave-solo-para-evidencias-no-usar-en-produccion",
        "DATABASE_AUTO_CREATE_TABLES": "0",
        "CALENDAR_AUTOMATION_ENABLED": "0",
        "DOSSIER_GENERATION_WORKER_ENABLED": "0",
        "DOSSIER_RETENTION_WORKER_ENABLED": "0",
        "DOSSIER_REDIS_ENABLED": "0",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from dossier.api.app import app  # noqa: E402

cliente = TestClient(app)  # sin "with": no corre el lifespan (trabajadores apagados)
cuentas = [
    {"email": "ana.demo@example.org", "full_name": "Ana Demo", "workspace_kind": "work",
     "company_name": "Empresa Ficticia Demo SpA", "locale": "es"},
    {"email": "luis.demo@example.com", "full_name": "Luis Demo", "workspace_kind": "personal", "locale": "en"},
]
for cuenta in cuentas:
    r = cliente.post("/auth/register", json={**cuenta, "password": "ClaveFicticia-2026"})
    datos = r.json()
    token = datos.get("access_token", "")
    print(f"POST /auth/register {cuenta['email']} -> HTTP {r.status_code}; "
          f"access_token={token[:12]}… ({len(token)} caracteres)")
    if r.status_code != 200:
        print("  detalle:", datos)
