"""Genera un erDiagram de Mermaid desde Base.metadata (backend/src/dossier/db/models.py).

Se ejecuta desde backend/ (pythonpath src). Imprime el bloque Mermaid por stdout.
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, "src")

from dossier.db import models  # noqa: E402,F401
from dossier.db.base import Base  # noqa: E402


def tipo(col) -> str:
    try:
        t = col.type.compile()
    except Exception:  # tipos sin dialecto por omisión (p. ej. JSONB, UUID de postgres)
        from sqlalchemy.dialects import postgresql

        t = col.type.compile(dialect=postgresql.dialect())
    t = re.sub(r"\(.*\)", "", str(t)).replace(" ", "_")
    return t.lower()


tablas = Base.metadata.sorted_tables
print("erDiagram")
for t in tablas:
    print(f"    {t.name} {{")
    for c in t.columns:
        marcas = []
        if c.primary_key:
            marcas.append("PK")
        if c.foreign_keys:
            marcas.append("FK")
        if c.unique:
            marcas.append("UK")
        m = (" " + ",".join(marcas)) if marcas else ""
        nulo = "" if c.nullable or c.primary_key else ' "not null"'
        print(f"        {tipo(c)} {c.name}{m}{nulo}")
    print("    }")
for t in tablas:
    for fk in sorted(t.foreign_keys, key=lambda f: f.parent.name):
        padre = fk.column.table.name
        hijo = t.name
        izq = "|o" if fk.parent.nullable else "||"
        print(f'    {padre} {izq}--o{{ {hijo} : "{fk.parent.name}"')
print(f"%% {len(tablas)} tablas declaradas en el ORM", file=sys.stderr)
