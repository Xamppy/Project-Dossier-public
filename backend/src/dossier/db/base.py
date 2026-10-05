"""
Base declarativa SQLAlchemy.

Todos los modelos ORM heredan de `Base` para compartir metadata y poder crear
tablas con `Base.metadata.create_all(...)` al arrancar (útil en desarrollo).
En producción suele usarse Alembic para migraciones versionadas.
"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Raíz de modelos; no añade columnas por sí sola."""

