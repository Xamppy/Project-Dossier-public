"""Tabla de las últimas N ejecuciones de GitHub Actions (evidencia CI/CD, Fase 2).

    python docs/evidencias/fase2/_herramientas/tabla_ejecuciones.py [N] [--md salida.md]

Usa `gh run list --json` y, por cada ejecución, `gh run view --json jobs` para calcular
la duración real: desde el inicio del primer job hasta el término del último. El campo
`updatedAt` de la ejecución no sirve como término: GitHub lo actualiza después (p. ej.
cuando un workflow_run dependiente se encola), y da duraciones infladas.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess


def gh(*args: str) -> object:
    salida = subprocess.run(["gh", *args], check=True, capture_output=True)
    return json.loads(salida.stdout.decode("utf-8"))


def fecha(s: str | None) -> dt.datetime | None:
    if not s or s.startswith("0001"):
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def duracion(run_id: int) -> str:
    jobs = gh("run", "view", str(run_id), "--json", "jobs")["jobs"]  # type: ignore[index]
    inicios = [fecha(j.get("startedAt")) for j in jobs]
    fines = [fecha(j.get("completedAt")) for j in jobs]
    inicios = [x for x in inicios if x]
    fines = [x for x in fines if x]
    if not inicios or not fines:
        return "-"
    seg = int((max(fines) - min(inicios)).total_seconds())
    if seg < 0:
        return "-"
    return f"{seg // 60}m{seg % 60:02d}s"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("n", nargs="?", type=int, default=30)
    ap.add_argument("--md")
    a = ap.parse_args()
    campos = "databaseId,number,workflowName,headBranch,event,status,conclusion,createdAt,headSha"
    runs = gh("run", "list", "--limit", str(a.n), "--json", campos)
    filas = []
    for r in runs:  # type: ignore[union-attr]
        estado = r["conclusion"] or r["status"]
        dur = duracion(r["databaseId"]) if r["status"] == "completed" else "(en curso)"
        filas.append([str(r["databaseId"]), f'{r["workflowName"]} #{r["number"]}', r["headBranch"],
                      r["event"], estado, dur, r["headSha"][:7], r["createdAt"].replace("T", " ")[:16]])
    cab = ["id", "workflow", "rama", "evento", "conclusión", "duración", "sha", "creada (UTC)"]
    anchos = [max(len(c), *(len(f[i]) for f in filas)) for i, c in enumerate(cab)]
    print("  ".join(c.ljust(anchos[i]) for i, c in enumerate(cab)))
    print("  ".join("-" * w for w in anchos))
    for f in filas:
        print("  ".join(v.ljust(anchos[i]) for i, v in enumerate(f)))
    cuenta: dict[str, int] = {}
    for f in filas:
        cuenta[f[4]] = cuenta.get(f[4], 0) + 1
    print()
    print("Resumen: " + ", ".join(f"{k}={v}" for k, v in sorted(cuenta.items())))
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write("| " + " | ".join(cab) + " |\n|" + "---|" * len(cab) + "\n")
            for f in filas:
                fh.write("| " + " | ".join(v.replace("|", "\\|") for v in f) + " |\n")


if __name__ == "__main__":
    main()
