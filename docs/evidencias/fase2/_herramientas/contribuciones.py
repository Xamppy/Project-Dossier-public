"""Aporte por integrante: commits, líneas, PR y tareas del harness (evidencia Fase 2).

    python docs/evidencias/fase2/_herramientas/contribuciones.py [REF] [--json salida.json]

REF por omisión: origin/main (lo integrado). Se excluyen de las líneas: package-lock.json,
specs/fixtures/, imágenes y .docx/.pdf. Los binarios (numstat «-») no suman líneas.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

# Alias de git -> integrante. Verificados con `git shortlog -sne --all`.
ALIAS = {
    "fe.orellanaa@duocuc.cl": "FO",
    "134563505+xamppy@users.noreply.github.com": "FO",
    "dari.garcia@duocuc.cl": "DG",
    "134294253+darygod@users.noreply.github.com": "DG",
    "fe.docmac@duocuc.cl": "FD",
    "49699333+dependabot[bot]@users.noreply.github.com": "bot",
}
GITHUB = {"Xamppy": "FO", "darygod": "DG", "app/dependabot": "bot", "dependabot": "bot"}
NOMBRES = {
    "FO": "Felipe Orellana Álvarez",
    "DG": "Darío García Avendaño",
    "FD": "Felipe Docmac Bravo",
    "bot": "dependabot[bot]",
}
EXCLUIR = re.compile(
    r"(^|/)package-lock\.json$|^specs/fixtures/|\.(png|jpe?g|gif|webp|ico|bmp|svg|docx|pdf)$",
    re.IGNORECASE,
)


def sh(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True).stdout.decode("utf-8", "replace")


def quien(email: str) -> str:
    return ALIAS.get(email.lower(), "?" + email)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ref", nargs="?", default="origin/main")
    ap.add_argument("--json")
    a = ap.parse_args()
    raiz = Path(sh("git", "rev-parse", "--show-toplevel").strip())

    commits: Counter[str] = Counter()
    coautor: Counter[str] = Counter()
    merges: Counter[str] = Counter()
    mas: Counter[str] = Counter()
    menos: Counter[str] = Counter()
    mas_excl: Counter[str] = Counter()
    archivos: dict[str, set[str]] = defaultdict(set)
    primeras: dict[str, str] = {}
    ultimas: dict[str, str] = {}

    # El commit raíz importa el sistema heredado (proyecto de continuidad): se informa aparte.
    raices = set(sh("git", "rev-list", "--max-parents=0", a.ref).split())
    mas_raiz: Counter[str] = Counter()
    sep = "\x1e"
    log = sh("git", "log", a.ref, "--no-merges", "--numstat",
             f"--format={sep}%H\x1f%ae\x1f%ad\x1f%B\x1f", "--date=short")
    for bloque in log.split(sep)[1:]:
        cab, _, resto = bloque.partition("\x1f")
        email, fecha, cuerpo_y_stats = resto.split("\x1f", 2)[0], resto.split("\x1f", 2)[1], resto.split("\x1f", 2)[2]
        cuerpo, _, stats = cuerpo_y_stats.partition("\x1f")
        k = quien(email)
        commits[k] += 1
        primeras[k] = fecha
        ultimas.setdefault(k, fecha)
        if re.search(r"^Co-Authored-By:", cuerpo, re.IGNORECASE | re.MULTILINE):
            coautor[k] += 1
        for ln in stats.strip().splitlines():
            partes = ln.split("\t")
            if len(partes) != 3:
                continue
            ad, de, ruta = partes
            if ad == "-":
                continue
            if EXCLUIR.search(ruta):
                mas_excl[k] += int(ad)
                continue
            mas[k] += int(ad)
            menos[k] += int(de)
            if cab in raices:
                mas_raiz[k] += int(ad)
            archivos[k].add(ruta)

    for email in sh("git", "log", a.ref, "--merges", "--format=%ae").split():
        merges[quien(email)] += 1

    prs = json.loads(sh("gh", "pr", "list", "--state", "all", "--limit", "500",
                        "--json", "number,author,state,mergedBy"))
    pr_ab: Counter[str] = Counter()
    pr_mz: Counter[str] = Counter()
    pr_mezclados_por: Counter[str] = Counter()
    for pr in prs:
        k = GITHUB.get(pr["author"]["login"], pr["author"]["login"])
        if pr["state"] == "MERGED":
            pr_mz[k] += 1
            pr_mezclados_por[GITHUB.get((pr.get("mergedBy") or {}).get("login", ""), "?")] += 1
        elif pr["state"] == "OPEN":
            pr_ab[k] += 1

    fl = json.loads((raiz / ".harness" / "feature_list.json").read_text(encoding="utf-8"))
    tareas: dict[str, Counter[str]] = defaultdict(Counter)
    for t in fl.get("tasks", fl.get("features", [])):
        tareas[t.get("owner", "?")][t.get("status", "?")] += 1

    orden = ["FO", "DG", "FD", "bot"]
    print(f"Referencia: {a.ref} · commits sin merges · exclusiones: package-lock.json, specs/fixtures/, imágenes, .docx/.pdf")
    print()
    cab = f"{'':4}{'integrante':26}{'commits':>8}{'c/ Co-Authored-By':>19}{'+líneas':>10}{'-líneas':>10}{'archivos':>9}{'merges hechos':>14}{'primer':>12}{'último':>12}"
    print(cab)
    print("-" * len(cab))
    for k in orden + sorted(set(commits) - set(orden)):
        print(f"{k:4}{NOMBRES.get(k, k):26}{commits[k]:>8}{coautor[k]:>19}{mas[k]:>10}{menos[k]:>10}"
              f"{len(archivos[k]):>9}{merges[k]:>14}{primeras.get(k, '-'):>12}{ultimas.get(k, '-'):>12}")
    print(f"{'':4}{'TOTAL':26}{sum(commits.values()):>8}{sum(coautor.values()):>19}{sum(mas.values()):>10}"
          f"{sum(menos.values()):>10}{'':>9}{sum(merges.values()):>14}")
    print()
    print("Líneas añadidas excluidas por la regla (lockfile, fixtures, imágenes, .docx/.pdf):",
          ", ".join(f"{k}={mas_excl[k]}" for k in orden))
    print("Commit raíz (importación del sistema heredado):", ", ".join(sorted(r[:7] for r in raices)))
    print("+líneas sin contar el commit raíz:",
          ", ".join(f"{k}={mas[k] - mas_raiz[k]} (raíz: {mas_raiz[k]})" for k in orden))
    print()
    print("Pull requests (gh pr list --state all):")
    for k in orden:
        print(f"  {k:4} abiertos={pr_ab[k]:<3} mezclados={pr_mz[k]:<3} mezclados por este integrante={pr_mezclados_por[k]}")
    print()
    estados = fl.get("status_values", [])
    print("Tareas del harness por owner y estado (.harness/feature_list.json):")
    print(f"  {'owner':6}" + "".join(f"{e:>12}" for e in estados) + f"{'total':>8}")
    for k in ["FO", "DG", "FD", "EQ"]:
        print(f"  {k:6}" + "".join(f"{tareas[k][e]:>12}" for e in estados) + f"{sum(tareas[k].values()):>8}")

    if a.json:
        Path(a.json).write_text(json.dumps({
            "ref": a.ref,
            "integrantes": {k: {"nombre": NOMBRES.get(k, k), "commits": commits[k], "co_authored_by": coautor[k],
                                "lineas_mas": mas[k], "lineas_menos": menos[k],
                                "lineas_mas_sin_raiz": mas[k] - mas_raiz[k], "archivos": len(archivos[k]),
                                "merges": merges[k], "pr_abiertos": pr_ab[k], "pr_mezclados": pr_mz[k],
                                "tareas": dict(tareas.get(k, {}))} for k in orden},
        }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
