"""Compara dos salidas de `pytest -v`: qué pruebas se omiten sin Postgres y pasan con él.

    python comparar_pytest.py sin_postgres.txt con_postgres.txt
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

LINEA = re.compile(r"^(tests[\\/]\S+::\S+(?:\[.*?\])?)\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)")


def estados(ruta: str) -> dict[str, str]:
    salida: dict[str, str] = {}
    for ln in Path(ruta).read_text(encoding="utf-8").splitlines():
        m = LINEA.match(ln)
        if m:
            salida[m.group(1)] = m.group(2)
    return salida


sin, con = estados(sys.argv[1]), estados(sys.argv[2])
activadas = sorted(t for t, e in sin.items() if e == "SKIPPED" and con.get(t) == "PASSED")
fallan = sorted(t for t, e in sin.items() if e == "SKIPPED" and con.get(t) not in ("PASSED", "SKIPPED"))
siguen = sorted(t for t, e in con.items() if e == "SKIPPED")
print(f"Pruebas en la salida sin Postgres: {len(sin)} · con Postgres: {len(con)}")
print(f"Omitidas sin Postgres que PASAN con Postgres: {len(activadas)}")
print(f"Omitidas sin Postgres que FALLAN con Postgres: {len(fallan)}")
print(f"Siguen omitidas con Postgres (pendientes de su tarea): {len(siguen)}")
print()
print("Pruebas que ejercitan Postgres real, por archivo:")
por_archivo = Counter(t.split("::")[0].replace("\\", "/") for t in activadas)
for archivo, n in sorted(por_archivo.items()):
    print(f"  {n:4d}  {archivo}")
if fallan:
    print("\nFallan:")
    for t in fallan:
        print("  " + t)
