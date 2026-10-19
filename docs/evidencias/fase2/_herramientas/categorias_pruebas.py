"""Conteo de pruebas por categoría y carpeta, a partir de salidas reales de las suites.

    python categorias_pruebas.py <salida pytest -v> <salida vitest run>

Backend: la categoría la asigna tests/conftest.py según la carpeta (raíz = unit,
integration/, security/, stress/). Frontend: Vitest no tiene categorías; se agrupa
por carpeta de src/.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

CATEGORIA = {"integration": "integración", "security": "seguridad", "stress": "estrés"}
PY = re.compile(r"^tests[\\/](\S+?)::\S+.*?\s(PASSED|FAILED|SKIPPED|ERROR)\b")
VT = re.compile(r"^\s*[✓×❯]\s+(src/\S+)\s+\((\d+) tests?")

estados: dict[str, Counter[str]] = defaultdict(Counter)
archivos: dict[str, set[str]] = defaultdict(set)
for ln in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    m = PY.match(ln)
    if not m:
        continue
    ruta = m.group(1).replace("\\", "/")
    carpeta = ruta.split("/")[0] if "/" in ruta else ""
    cat = CATEGORIA.get(carpeta, "unitaria")
    estados[cat][m.group(2)] += 1
    archivos[cat].add(ruta)

print("BACKEND (pytest -v con Postgres) — categoría asignada por carpeta en tests/conftest.py")
print(f"  {'categoría':12}{'carpeta':22}{'archivos':>9}{'pruebas':>9}{'pasan':>8}{'omitidas':>10}{'fallan':>8}")
carpetas = {"unitaria": "tests/", "integración": "tests/integration/", "seguridad": "tests/security/", "estrés": "tests/stress/"}
tot = Counter()
for cat in ["unitaria", "integración", "seguridad", "estrés"]:
    e = estados[cat]
    n = sum(e.values())
    tot.update(e)
    print(f"  {cat:12}{carpetas[cat]:22}{len(archivos[cat]):>9}{n:>9}{e['PASSED']:>8}{e['SKIPPED']:>10}{e['FAILED'] + e['ERROR']:>8}")
print(f"  {'TOTAL':12}{'':22}{sum(len(v) for v in archivos.values()):>9}{sum(tot.values()):>9}{tot['PASSED']:>8}{tot['SKIPPED']:>10}{tot['FAILED'] + tot['ERROR']:>8}")

print()
print("FRONTEND (vitest run) — por carpeta de src/")
grupos: Counter[str] = Counter()
gfiles: Counter[str] = Counter()
for ln in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
    m = VT.match(ln)
    if not m:
        continue
    partes = m.group(1).split("/")
    clave = "/".join(partes[:3]) if len(partes) > 3 else "/".join(partes[:2])
    grupos[clave] += int(m.group(2))
    gfiles[clave] += 1
print(f"  {'carpeta':36}{'archivos':>9}{'pruebas':>9}")
for k in sorted(grupos):
    print(f"  {k:36}{gfiles[k]:>9}{grupos[k]:>9}")
print(f"  {'TOTAL':36}{sum(gfiles.values()):>9}{sum(grupos.values()):>9}")
