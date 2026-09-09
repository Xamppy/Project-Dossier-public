#!/usr/bin/env python3
"""Verificación de calidad antes de commitear o de hacer push.

    python scripts/qa.py              antes de commitear
    python scripts/qa.py --full       antes de push, añade build del frontend
    python scripts/qa.py --fast       solo pruebas unitarias, mientras desarrollas
    python scripts/qa.py --policy     solo revisa la política de pruebas

Ejecuta únicamente lo que corresponde a lo que cambiaste: si tocaste solo el
backend, no compila el frontend. Ver docs/dev/testing-policy.md.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
FRONTEND = RAIZ / "frontend"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"
if os.name == "nt" and not os.environ.get("WT_SESSION"):
    os.system("")  # habilita ANSI en la consola clásica de Windows


class Resultado:
    def __init__(self) -> None:
        self.fallos: list[str] = []
        self.avisos: list[str] = []

    def fallo(self, que: str) -> None:
        self.fallos.append(que)

    def aviso(self, que: str) -> None:
        self.avisos.append(que)


def titulo(texto: str) -> None:
    print(f"\n{texto}\n{'-' * len(texto)}")


def python_backend() -> str:
    """El intérprete del venv del backend si existe; si no, el del sistema."""
    for candidato in (
        BACKEND / ".venv" / "Scripts" / "python.exe",
        BACKEND / ".venv" / "bin" / "python",
    ):
        if candidato.exists():
            return str(candidato)
    return sys.executable


def correr(cmd: list[str], cwd: Path, nombre: str, res: Resultado,
           obligatorio: bool = True) -> bool:
    print(f"  {GRIS}$ {' '.join(cmd)}{FIN}")
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        marca, registro = (ROJO, res.fallo) if obligatorio else (AMARILLO, res.aviso)
        print(f"  {marca}omitido{FIN}  {nombre}: no se encontró {cmd[0]}")
        registro(f"{nombre}: falta la herramienta {cmd[0]}")
        return False

    salida = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        ultima = [l for l in salida.strip().splitlines() if l.strip()]
        print(f"  {VERDE}ok{FIN}       {nombre}" + (f"  {GRIS}{ultima[-1][:70]}{FIN}" if ultima else ""))
        return True

    marca, registro = (ROJO, res.fallo) if obligatorio else (AMARILLO, res.aviso)
    print(f"  {marca}FALLA{FIN}    {nombre}")
    for linea in salida.strip().splitlines()[-25:]:
        print(f"           {linea}")
    registro(nombre)
    return False


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True,
                              text=True, encoding="utf-8", errors="replace").stdout
    except FileNotFoundError:
        return ""


def archivos_cambiados(contra: str | None) -> list[str]:
    """Lo que cambió: preparado y sin preparar, o contra una referencia."""
    if contra:
        salida = git("diff", "--name-only", contra)
    else:
        salida = git("diff", "--name-only", "HEAD") or git("diff", "--name-only", "--cached")
        salida += git("ls-files", "--others", "--exclude-standard")
    return sorted({l.strip() for l in salida.splitlines() if l.strip()})


def es_codigo(ruta: str) -> bool:
    if "/tests/" in ruta or ruta.endswith((".test.tsx", ".test.ts", ".spec.tsx", ".spec.ts")):
        return False
    if "/i18n/messages/" in ruta:
        return False
    return (ruta.startswith("backend/src/") and ruta.endswith(".py")) or (
        ruta.startswith("frontend/src/") and ruta.endswith((".ts", ".tsx"))
    )


def es_prueba(ruta: str) -> bool:
    return (
        ruta.startswith("backend/tests/")
        or ruta.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    )


def revisar_politica(cambios: list[str], res: Resultado) -> None:
    """La regla del proyecto: código que cambia trae la prueba que lo respalda."""
    titulo("Política de pruebas")

    codigo = [r for r in cambios if es_codigo(r)]
    pruebas = [r for r in cambios if es_prueba(r)]

    if not codigo:
        print(f"  {VERDE}ok{FIN}       sin cambios de código que exijan prueba")
        return

    print(f"  {len(codigo)} archivo(s) de código · {len(pruebas)} archivo(s) de prueba")
    for r in codigo[:12]:
        print(f"    {GRIS}código{FIN}  {r}")
    for r in pruebas[:12]:
        print(f"    {VERDE}prueba{FIN}  {r}")

    if not pruebas:
        print(f"\n  {ROJO}FALLA{FIN}    cambiaste código y ninguna prueba")
        print("           Consulta la tabla de docs/dev/testing-policy.md §1")
        print("           para saber qué categorías exige tu cambio.")
        print(f"           {GRIS}Si de verdad no aplica, justifícalo en el mensaje del commit.{FIN}")
        res.fallo("política de pruebas: código sin prueba")
        return

    # Aviso, no fallo: la relación no siempre es uno a uno.
    zonas_sensibles = {
        "security": "backend/src/dossier/security/",
        "billing": "backend/src/dossier/billing/",
        "db": "backend/src/dossier/db/",
        "graphs": "backend/src/dossier/graphs/",
    }
    for etiqueta, prefijo in zonas_sensibles.items():
        if any(r.startswith(prefijo) for r in codigo):
            esperada = f"backend/tests/security/" if etiqueta == "security" else "backend/tests/"
            if not any(r.startswith(esperada) for r in pruebas):
                print(f"\n  {AMARILLO}aviso{FIN}    tocaste {prefijo} sin prueba en {esperada}")
                res.aviso(f"{etiqueta} sin prueba asociada")

    print(f"\n  {VERDE}ok{FIN}       hay pruebas acompañando el cambio")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--full", action="store_true", help="Incluye build del frontend (antes de push)")
    p.add_argument("--fast", action="store_true", help="Solo pruebas unitarias")
    p.add_argument("--policy", action="store_true", help="Solo revisa la política de pruebas")
    p.add_argument("--since", metavar="REF", help="Comparar contra una referencia de git")
    p.add_argument("--no-policy", action="store_true", help="Omitir la revisión de política")
    args = p.parse_args()

    res = Resultado()
    cambios = archivos_cambiados(args.since)

    print(f"\n{'=' * 62}")
    print(f"  QA · Project Dossier")
    print(f"  {len(cambios)} archivo(s) cambiado(s)")
    print(f"{'=' * 62}")

    if not args.no_policy:
        revisar_politica(cambios, res)
    if args.policy:
        return informe(res)

    toca_backend = any(r.startswith("backend/") for r in cambios) or not cambios
    toca_frontend = any(r.startswith("frontend/") for r in cambios) or not cambios

    if toca_backend:
        titulo("Backend")
        py = python_backend()
        if py == sys.executable and not (BACKEND / ".venv").exists():
            print(f"  {AMARILLO}aviso{FIN}    no hay entorno virtual en backend/.venv")

        if args.fast:
            correr([py, "-m", "pytest", "-q", "-m", "unit"], BACKEND, "pytest (unit)", res)
        else:
            correr([py, "-m", "pytest", "-q"], BACKEND, "pytest (suite completa)", res)

        # Todavía no configurados: tarea S1.2. Avisan, no bloquean.
        if (BACKEND / "pyproject.toml").exists():
            correr([py, "-m", "ruff", "check", "."], BACKEND, "ruff", res, obligatorio=False)
            correr([py, "-m", "mypy", "src"], BACKEND, "mypy", res, obligatorio=False)
        else:
            print(f"  {GRIS}—        ruff y mypy sin configurar todavía (tarea S1.2){FIN}")

    if toca_frontend:
        titulo("Frontend")
        npm = shutil.which("npm") or "npm"
        if not (FRONTEND / "node_modules").exists():
            print(f"  {AMARILLO}aviso{FIN}    falta node_modules; ejecuta npm install en frontend/")
            res.aviso("frontend sin dependencias instaladas")
        else:
            correr([npm, "run", "lint"], FRONTEND, "eslint", res)
            if not args.fast:
                correr([npm, "test"], FRONTEND, "vitest", res)
            if args.full:
                correr([npm, "run", "build"], FRONTEND, "next build", res)

    return informe(res)


def informe(res: Resultado) -> int:
    print(f"\n{'=' * 62}")
    if res.avisos:
        print(f"  {AMARILLO}{len(res.avisos)} aviso(s){FIN}")
        for a in res.avisos:
            print(f"    - {a}")
    if res.fallos:
        print(f"  {ROJO}{len(res.fallos)} fallo(s). No commitees todavía.{FIN}")
        for f in res.fallos:
            print(f"    - {f}")
        print(f"{'=' * 62}\n")
        return 1
    print(f"  {VERDE}Todo en verde.{FIN}")
    print(f"{'=' * 62}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
