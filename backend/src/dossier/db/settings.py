"""
Configuración de PostgreSQL solo desde el entorno.
Nunca guardes contraseñas en código: cada quien usa su .env local (gitignored).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

# Si ejecutas este archivo con "Run Python File" desde el IDE, añade la raíz de `src/`.
if importlib.util.find_spec("dossier") is None:
    _here = Path(__file__).resolve().parent
    for _root in [_here, *_here.parents]:
        if (_root / "dossier" / "__init__.py").is_file():
            sys.path.insert(0, str(_root))
            break

from dossier.config import load_env


def _database_url_for_sqlalchemy(url: str) -> str:
    """
    Railway y otros proveedores suelen dar `postgresql://` o `postgres://`.
    SQLAlchemy 2 asocia eso al driver **psycopg2** (no instalado aquí).
    Este proyecto usa **psycopg3** (`pip install psycopg[binary]`).
    """
    u = url.strip()
    if u.startswith(("postgresql+psycopg://", "postgresql+asyncpg://")):
        return u
    if u.startswith("postgres://"):
        return "postgresql+psycopg://" + u[len("postgres://") :]
    if u.startswith("postgresql://"):
        return "postgresql+psycopg://" + u[len("postgresql://") :]
    return u


def build_database_url() -> str | None:
    """
    Devuelve la URL SQLAlchemy para psycopg3, o None si no hay configuración.

    Prioridad:
    1. DATABASE_URL (si está definida y no vacía)
    2. POSTGRES_HOST + POSTGRES_USER + POSTGRES_PASSWORD + POSTGRES_DB (+ POSTGRES_PORT)
    """
    load_env()

    direct = (os.getenv("DATABASE_URL") or "").strip()
    if direct:
        return _database_url_for_sqlalchemy(direct)

    host = (os.getenv("POSTGRES_HOST") or "").strip()
    if not host:
        return None

    port = (os.getenv("POSTGRES_PORT") or "5432").strip()
    user = (os.getenv("POSTGRES_USER") or "postgres").strip()
    password = os.getenv("POSTGRES_PASSWORD") or ""
    database = (os.getenv("POSTGRES_DB") or "").strip()
    if not database:
        return None

    user_q = quote_plus(user)
    pwd_q = quote_plus(password)
    auth = f"{user_q}:{pwd_q}@" if password else f"{user_q}@"

    return f"postgresql+psycopg://{auth}{host}:{port}/{quote_plus(database)}"
