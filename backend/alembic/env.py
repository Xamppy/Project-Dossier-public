"""Configuración de entorno de Alembic (S1.1).

Reutiliza `dossier.db.settings.build_database_url()` para no duplicar la
lógica de resolución de DATABASE_URL / POSTGRES_* que ya usa la app, y
`dossier.db.base.Base` + `dossier.db.models` como metadata objetivo, para
que `alembic revision --autogenerate` compare contra los modelos ORM reales.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Permite `import dossier...` sin instalar el paquete (igual que hace
# `db/connection.py` cuando corre fuera de un entorno con `pip install -e .`).
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SRC = _BACKEND_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dossier.db.base import Base  # noqa: E402
from dossier.db.settings import build_database_url  # noqa: E402

# Importa los modelos para que se registren en Base.metadata antes de
# que Alembic la lea (si no se importa el módulo, la metadata queda vacía).
from dossier.db import models as _models  # noqa: E402,F401

# Objeto de configuración de Alembic (acceso a valores de alembic.ini).
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata objetivo para autogenerate.
target_metadata = Base.metadata


def _resolve_db_url() -> str:
    url = build_database_url()
    if not url:
        raise RuntimeError(
            "PostgreSQL no está configurado. Define DATABASE_URL o POSTGRES_* en "
            "backend/.env antes de correr Alembic (ver backend/.env.example)."
        )
    return url


def run_migrations_offline() -> None:
    """Genera SQL sin conectarse a la base (modo `--sql`)."""
    url = _resolve_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Conecta a la base real y aplica/compara migraciones."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _resolve_db_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
