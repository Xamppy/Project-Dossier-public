#!/usr/bin/env python3
"""Consulta y actualiza el estado de las tareas del proyecto.

Lee y escribe .harness/feature_list.json, que es la fuente de verdad del estado.

    python .harness/next.py                    tareas disponibles ahora
    python .harness/next.py --owner FO         solo las de un responsable
    python .harness/next.py --sprint 1         solo las de un sprint
    python .harness/next.py --all              incluye las bloqueadas por dependencias
    python .harness/next.py --status           resumen del proyecto
    python .harness/next.py --show S2.1        detalle de una tarea
    python .harness/next.py --claim S2.1 --as "FO (agente)"
    python .harness/next.py --set S2.1 in_progress --branch feat/S2.1-agente-europeo
    python .harness/next.py --check            verifica consistencia del archivo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# La consola de Windows usa cp1252 por omisión y rompe los acentos.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

HERE = Path(__file__).resolve().parent
DB = HERE / "feature_list.json"

OPEN_STATES = {"pending", "claimed", "in_progress", "review", "blocked"}
VALID = ["pending", "claimed", "in_progress", "review", "blocked", "done"]

MARK = {
    "pending": "  ",
    "claimed": "->",
    "in_progress": ">>",
    "review": "??",
    "blocked": "!!",
    "done": "ok",
}


def load() -> dict:
    if not DB.exists():
        sys.exit(f"No existe {DB}")
    return json.loads(DB.read_text(encoding="utf-8"))


def save(doc: dict) -> None:
    DB.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def by_id(doc: dict) -> dict:
    return {f["id"]: f for f in doc["features"]}


def blockers(feat: dict, index: dict) -> list[str]:
    """Dependencias que todavía no están done."""
    return [d for d in feat["depends_on"] if index.get(d, {}).get("status") != "done"]


def line(f: dict, index: dict) -> str:
    pend = blockers(f, index)
    tail = ""
    if pend:
        tail = f"  <- espera {', '.join(pend)}"
    elif f["blocks"]:
        tail = f"  -> desbloquea {len(f['blocks'])}"
    gap = f" [{f['gap']}]" if f["gap"] else ""
    return (
        f"  {MARK[f['status']]} {f['id']:<6} {f['owner']:<3} {f['area']:<9} "
        f"{f['title'][:62]:<62}{gap}{tail}"
    )


def cmd_available(doc: dict, args) -> None:
    index = by_id(doc)
    rows = [f for f in doc["features"] if f["status"] == "pending"]
    if args.owner:
        rows = [f for f in rows if f["owner"] == args.owner.upper()]
    if args.sprint is not None:
        rows = [f for f in rows if f["sprint"] == args.sprint]
    if not args.all:
        rows = [f for f in rows if not blockers(f, index)]

    if not rows:
        print("Nada disponible con esos filtros.")
        return

    # Las que desbloquean más van primero: son ruta crítica.
    rows.sort(key=lambda f: (f["sprint"], -len(f["blocks"]), f["id"]))

    title = "Tareas disponibles" if not args.all else "Tareas pendientes (todas)"
    print(f"\n{title}\n")
    sprint = None
    for f in rows:
        if f["sprint"] != sprint:
            sprint = f["sprint"]
            s = doc["sprints"][str(sprint)]
            print(f"Sprint {sprint} | {s['name']} | vence {s['due']}")
        print(line(f, index))
    print()


def cmd_status(doc: dict) -> None:
    index = by_id(doc)
    feats = doc["features"]
    print(f"\n{doc['project']}")
    print(f"Tablero: {doc['board']}\n")

    counts: dict[str, int] = {}
    for f in feats:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    done = counts.get("done", 0)
    print(f"Total {len(feats)} tareas | {done} terminadas ({done * 100 // len(feats)} %)")
    print("  " + " | ".join(f"{k}: {v}" for k, v in counts.items() if v))

    print("\nPor sprint")
    for sid, s in doc["sprints"].items():
        rows = [f for f in feats if f["sprint"] == int(sid)]
        d = sum(1 for f in rows if f["status"] == "done")
        bar = "#" * d + "." * (len(rows) - d)
        print(f"  S{sid}  {d:>2}/{len(rows):<2}  {bar:<15}  {s['name']} (vence {s['due']})")

    print("\nPor responsable")
    for o, label in doc["owners"].items():
        rows = [f for f in feats if f["owner"] == o]
        d = sum(1 for f in rows if f["status"] == "done")
        print(f"  {o}  {d}/{len(rows):<3} {label}")

    print("\nBrechas del alcance firme")
    for g, label in doc["gaps"].items():
        rows = [f for f in feats if f["gap"] == g]
        d = sum(1 for f in rows if f["status"] == "done")
        state = "cerrada" if rows and d == len(rows) else "abierta"
        print(f"  {g}  {d}/{len(rows)}  {state:<8} {label}")

    active = [f for f in feats if f["status"] in ("claimed", "in_progress", "review")]
    if active:
        print("\nEn curso ahora")
        for f in active:
            who = f.get("owner_session") or f["owner"]
            br = f"  {f['branch']}" if f.get("branch") else ""
            print(f"  {MARK[f['status']]} {f['id']:<6} {who:<16} {f['title'][:50]}{br}")

    stuck = [f for f in feats if f["status"] == "blocked"]
    if stuck:
        print("\nBloqueadas")
        for f in stuck:
            print(f"  !! {f['id']:<6} {f['title'][:50]}")
            if f.get("notes"):
                print(f"        {f['notes']}")
    print()


def cmd_show(doc: dict, fid: str) -> None:
    index = by_id(doc)
    f = index.get(fid.upper())
    if not f:
        sys.exit(f"No existe la tarea {fid}")
    s = doc["sprints"][str(f["sprint"])]
    print(f"\n{f['id']} · {f['title']}\n")
    print(f"  Estado        {f['status']}")
    print(f"  Responsable   {f['owner']} — {doc['owners'][f['owner']]}")
    print(f"  Sprint        {f['sprint']} | {s['name']} | {s['weeks']}")
    print(f"  Vence         {f['due']}")
    print(f"  Área          {f['area']}")
    print(f"  Actividad     {f['activity']}" + (f" | {f['objective']}" if f["objective"] else ""))
    if f["gap"]:
        print(f"  Brecha        {f['gap']} — {doc['gaps'][f['gap']]}")
    if f["depends_on"]:
        pend = blockers(f, index)
        for d in f["depends_on"]:
            st = index.get(d, {}).get("status", "?")
            print(f"  Depende de    {d} ({st})")
        if pend:
            print(f"  NO DISPONIBLE Faltan: {', '.join(pend)}")
    if f["blocks"]:
        print(f"  Desbloquea    {', '.join(f['blocks'])}")
    if f.get("branch"):
        print(f"  Rama          {f['branch']}")
    if f.get("owner_session"):
        print(f"  Sesión        {f['owner_session']}")
    if f.get("notes"):
        print(f"  Notas         {f['notes']}")
    if f.get("evidence"):
        for e in f["evidence"]:
            print(f"  Evidencia     {e}")
    print(f"  Trello        {f['trello']}")
    print()


def cmd_claim(doc: dict, fid: str, who: str) -> None:
    index = by_id(doc)
    f = index.get(fid.upper())
    if not f:
        sys.exit(f"No existe la tarea {fid}")
    if f["status"] != "pending":
        sys.exit(f"{f['id']} está en '{f['status']}', no en 'pending'. No se puede tomar.")
    pend = blockers(f, index)
    if pend:
        sys.exit(f"{f['id']} espera a: {', '.join(pend)}")
    f["status"] = "claimed"
    f["owner_session"] = who
    save(doc)
    print(f"{f['id']} tomada por {who}.")
    print(f"  {f['title']}")
    print("\nCommitea este cambio SOLO, antes de escribir código:")
    print(f'  git add .harness/feature_list.json')
    print(f'  git commit -m "chore(harness): claim {f["id"]}"')


def cmd_set(doc: dict, fid: str, status: str, args) -> None:
    index = by_id(doc)
    f = index.get(fid.upper())
    if not f:
        sys.exit(f"No existe la tarea {fid}")
    if status not in VALID:
        sys.exit(f"Estado inválido. Válidos: {', '.join(VALID)}")
    if status == "blocked" and not args.notes:
        sys.exit("Para 'blocked' hace falta --notes con el motivo.")
    old = f["status"]
    f["status"] = status
    if args.branch:
        f["branch"] = args.branch
    if args.notes:
        f["notes"] = args.notes
    if args.evidence:
        f.setdefault("evidence", []).append(args.evidence)
    save(doc)
    print(f"{f['id']}: {old} -> {status}")
    if status == "done":
        opened = [b for b in f["blocks"] if index[b]["status"] == "pending"
                  and not blockers(index[b], index)]
        if opened:
            print(f"  Desbloqueadas: {', '.join(opened)}")
        print("\n  Recordatorio: 'done' lo pone quien REVISA, no quien implementa.")


def cmd_check(doc: dict) -> None:
    index = by_id(doc)
    problems = []
    for f in doc["features"]:
        for d in f["depends_on"]:
            if d not in index:
                problems.append(f"{f['id']}: depende de {d}, que no existe")
        if f["status"] not in VALID:
            problems.append(f"{f['id']}: estado inválido '{f['status']}'")
        if f["status"] == "done":
            for d in f["depends_on"]:
                if index[d]["status"] != "done":
                    problems.append(
                        f"{f['id']}: está done pero su dependencia {d} está en "
                        f"'{index[d]['status']}'"
                    )
        if f["status"] == "blocked" and not f.get("notes"):
            problems.append(f"{f['id']}: bloqueada sin motivo en notes")
    active = [f for f in doc["features"] if f["status"] in ("claimed", "in_progress")]
    sessions: dict[str, list[str]] = {}
    for f in active:
        s = f.get("owner_session")
        if s:
            sessions.setdefault(s, []).append(f["id"])
    for s, ids in sessions.items():
        if len(ids) > 1:
            problems.append(f"{s} tiene {len(ids)} tareas a la vez: {', '.join(ids)}")

    if problems:
        print(f"\n{len(problems)} problema(s):\n")
        for p in problems:
            print(f"  - {p}")
        print()
        sys.exit(1)
    print(f"OK. {len(doc['features'])} tareas, sin inconsistencias.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--owner", help="Filtrar por responsable (FO, DG, FD, EQ)")
    p.add_argument("--sprint", type=int, help="Filtrar por sprint")
    p.add_argument("--all", action="store_true", help="Incluir las que esperan dependencias")
    p.add_argument("--status", action="store_true", help="Resumen del proyecto")
    p.add_argument("--show", metavar="ID", help="Detalle de una tarea")
    p.add_argument("--claim", metavar="ID", help="Tomar una tarea")
    p.add_argument("--as", dest="who", help="Identificador de sesión para --claim")
    p.add_argument("--set", nargs=2, metavar=("ID", "ESTADO"), help="Cambiar estado")
    p.add_argument("--branch", help="Rama asociada")
    p.add_argument("--notes", help="Nota (obligatoria para 'blocked')")
    p.add_argument("--evidence", help="Añadir evidencia (URL o ruta)")
    p.add_argument("--check", action="store_true", help="Verificar consistencia")
    args = p.parse_args()

    doc = load()
    if args.check:
        cmd_check(doc)
    elif args.status:
        cmd_status(doc)
    elif args.show:
        cmd_show(doc, args.show)
    elif args.claim:
        if not args.who:
            sys.exit('Falta --as. Ejemplo: --as "FO (agente)"')
        cmd_claim(doc, args.claim, args.who)
    elif args.set:
        cmd_set(doc, args.set[0], args.set[1], args)
    else:
        cmd_available(doc, args)


if __name__ == "__main__":
    main()
