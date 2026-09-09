#!/usr/bin/env python3
"""Instala los ganchos de git que ejecutan la verificación de calidad.

    python scripts/install-hooks.py              instalar
    python scripts/install-hooks.py --uninstall  desinstalar
    python scripts/install-hooks.py --check      ver qué hay instalado

Qué queda instalado:

    pre-commit   python scripts/qa.py           pruebas y política
    pre-push     python scripts/qa.py --full    lo anterior más el build

Aviso sobre worktrees: git guarda los ganchos en el directorio común del
repositorio, así que **se comparten entre todos los worktrees**. Instalarlos aquí
los activa también en los demás. Es lo que se quiere casi siempre, pero conviene
saberlo antes de que sorprenda.

Para saltarse un gancho en un caso puntual: `git commit --no-verify`. Está
disponible a propósito; úsalo cuando de verdad corresponda y di por qué en el
mensaje del commit.
"""
from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

MARCA = "# instalado por scripts/install-hooks.py"

PRE_COMMIT = f"""#!/bin/sh
{MARCA}
# Verificación antes de commitear: pruebas y política de pruebas.
# Saltar en un caso puntual: git commit --no-verify

echo "QA previo al commit..."
python "$(git rev-parse --show-toplevel)/scripts/qa.py" || {{
  echo ""
  echo "El commit se detuvo: la verificación falló."
  echo "Corrige lo anterior, o usa --no-verify si de verdad corresponde."
  exit 1
}}
"""

PRE_PUSH = f"""#!/bin/sh
{MARCA}
# Verificación antes de push: lo del commit más el build del frontend.
# Saltar en un caso puntual: git push --no-verify

echo "QA previo al push..."
python "$(git rev-parse --show-toplevel)/scripts/qa.py" --full || {{
  echo ""
  echo "El push se detuvo: la verificación falló."
  echo "Corrige lo anterior, o usa --no-verify si de verdad corresponde."
  exit 1
}}
"""

GANCHOS = {"pre-commit": PRE_COMMIT, "pre-push": PRE_PUSH}


def dir_ganchos() -> Path:
    """Dónde viven los ganchos, funcione o no dentro de un worktree."""
    salida = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if salida.returncode != 0:
        sys.exit("No parece un repositorio git.")
    comun = Path(salida.stdout.strip())
    if not comun.is_absolute():
        comun = (RAIZ / comun).resolve()
    return comun / "hooks"


def es_worktree() -> bool:
    return (RAIZ / ".git").is_file()


def instalar() -> int:
    destino = dir_ganchos()
    destino.mkdir(parents=True, exist_ok=True)

    if es_worktree():
        print("Aviso: este directorio es un worktree.")
        print(f"Los ganchos van a {destino} y se comparten con los demás worktrees.\n")

    for nombre, contenido in GANCHOS.items():
        ruta = destino / nombre
        if ruta.exists():
            previo = ruta.read_text(encoding="utf-8", errors="replace")
            if MARCA not in previo:
                respaldo = ruta.with_suffix(".anterior")
                respaldo.write_text(previo, encoding="utf-8")
                print(f"  {nombre}: ya existía y no era nuestro. Copia en {respaldo.name}")
        ruta.write_text(contenido, encoding="utf-8", newline="\n")
        if os.name != "nt":
            ruta.chmod(ruta.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        print(f"  instalado  {nombre}")

    print("\nListo.")
    print("  pre-commit  ->  python scripts/qa.py")
    print("  pre-push    ->  python scripts/qa.py --full")
    print("\nSaltar en un caso puntual: git commit --no-verify")
    return 0


def desinstalar() -> int:
    destino = dir_ganchos()
    quitados = 0
    for nombre in GANCHOS:
        ruta = destino / nombre
        if not ruta.exists():
            continue
        if MARCA not in ruta.read_text(encoding="utf-8", errors="replace"):
            print(f"  {nombre}: no es nuestro, se deja como está")
            continue
        ruta.unlink()
        print(f"  quitado  {nombre}")
        quitados += 1
        respaldo = ruta.with_suffix(".anterior")
        if respaldo.exists():
            respaldo.rename(ruta)
            print(f"  restaurado el {nombre} anterior")
    print(f"\n{quitados} gancho(s) quitado(s).")
    return 0


def comprobar() -> int:
    destino = dir_ganchos()
    print(f"Directorio de ganchos: {destino}")
    if es_worktree():
        print("(worktree: compartido con los demás worktrees)")
    print()
    for nombre in GANCHOS:
        ruta = destino / nombre
        if not ruta.exists():
            print(f"  {nombre:<12} no instalado")
        elif MARCA in ruta.read_text(encoding="utf-8", errors="replace"):
            print(f"  {nombre:<12} instalado")
        else:
            print(f"  {nombre:<12} existe, pero no es nuestro")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--check", action="store_true")
    args = p.parse_args()

    if args.check:
        return comprobar()
    if args.uninstall:
        return desinstalar()
    return instalar()


if __name__ == "__main__":
    sys.exit(main())
