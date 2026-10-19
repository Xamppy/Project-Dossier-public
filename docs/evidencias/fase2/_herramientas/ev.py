"""Ejecuta un comando, guarda su salida literal en .txt y genera .html + .png.

Uso:
  python ev.py --out <ruta/sin/extension> --cwd <dir> --cmd "<comando>"
               [--titulo T] [--png-tail N] [--png-head N] [--png-grep REGEX]
               [--mostrar "<comando a mostrar>"] [--ok-codes 0,1]

El comando se ejecuta con bash -c en <cwd>, heredando el entorno. La salida
(stdout+stderr combinados) se guarda sin modificar. Si el PNG muestra un
extracto, el encabezado del PNG lo dice explícitamente.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import math
import os
import re
import subprocess
import sys
from pathlib import Path

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SHA = os.environ.get("SHA", "?")
W = os.environ.get("W", "")


def rel(p: str) -> str:
    try:
        r = os.path.relpath(p, W).replace("\\", "/")
        return "." if r == "." else r + "/"
    except ValueError:
        return p


def render(out: Path, titulo: str, comando: str, cwd_rel: str, fecha: str, codigo: int,
           lineas: list[str], nota: str) -> None:
    font_px, line_px, char_px = 13, 18, 7.4
    maxcols = 200
    cuerpo = "\n".join(lineas)
    filas = 0
    ancho_max = 0
    for ln in lineas:
        n = len(ln.expandtabs(8))
        ancho_max = max(ancho_max, min(n, maxcols))
        filas += max(1, math.ceil(n / maxcols)) if n else 1
    ancho_max = max(ancho_max, len(comando) + 4, 100)
    ancho_max = min(ancho_max, maxcols)
    width = int(ancho_max * char_px) + 80
    cmd_filas = max(1, math.ceil(len(comando) / (maxcols - 4)))
    height = 70 + cmd_filas * 22 + (24 if nota else 0) + filas * line_px + 80
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{html.escape(titulo)}</title>
<style>
html,body{{margin:0;background:#0d1117;color:#e6edf3;font-family:Consolas,'Cascadia Mono','Courier New',monospace;}}
.wrap{{padding:20px 24px;}}
h1{{font-size:14px;margin:0 0 6px 0;color:#7ee787;font-weight:600}}
.cmd{{font-size:{font_px}px;color:#79c0ff;white-space:pre-wrap;word-break:break-all;margin:0 0 4px 0}}
.meta{{font-size:12px;color:#8b949e;margin:0 0 10px 0}}
.nota{{font-size:12px;color:#d29922;margin:0 0 8px 0}}
pre{{font-size:{font_px}px;line-height:{line_px}px;margin:0;white-space:pre-wrap;word-break:break-all;
   max-width:{maxcols}ch;border-top:1px solid #30363d;border-bottom:1px solid #30363d;padding:8px 0}}
footer{{font-size:12px;color:#8b949e;margin-top:10px}}
</style></head><body><div class="wrap">
<h1>{html.escape(titulo)}</h1>
<div class="cmd">$ {html.escape(comando)}</div>
<div class="meta">directorio: {html.escape(cwd_rel)} · código de salida: {codigo}</div>
{f'<div class="nota">{html.escape(nota)}</div>' if nota else ''}
<pre>{html.escape(cuerpo)}</pre>
<footer>commit {SHA} · {html.escape(fecha)} · Project Dossier · evidencia Fase 2</footer>
</div></body></html>"""
    out.with_suffix(".html").write_text(doc, encoding="utf-8")
    png = out.with_suffix(".png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", f"--window-size={width},{height}",
                    f"--screenshot={png}", out.with_suffix(".html").resolve().as_uri()],
                   check=True, capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cwd", required=True)
    ap.add_argument("--cmd", required=True)
    ap.add_argument("--mostrar")
    ap.add_argument("--titulo", default="")
    ap.add_argument("--png-tail", type=int)
    ap.add_argument("--png-head", type=int)
    ap.add_argument("--png-grep")
    ap.add_argument("--keep-html", action="store_true")
    a = ap.parse_args()

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", NO_COLOR="1", FORCE_COLOR="0")
    inicio = dt.datetime.now().astimezone()
    p = subprocess.run(["bash", "-c", a.cmd], cwd=a.cwd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    salida = p.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    salida = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", salida)
    fecha = inicio.strftime("%Y-%m-%d %H:%M:%S %z")
    mostrado = a.mostrar or a.cmd
    titulo = a.titulo or out.name
    cwd_rel = rel(a.cwd)
    cab = (f"# {titulo}\n# Fecha: {fecha}\n# Commit: {SHA}\n# Directorio: {cwd_rel}\n"
           f"# Comando: {mostrado}\n# Código de salida: {p.returncode}\n"
           "# ---- salida literal ----\n")
    out.with_suffix(".txt").write_text(cab + salida, encoding="utf-8")

    lineas = salida.rstrip("\n").split("\n")
    nota = ""
    total = len(lineas)
    if a.png_grep:
        rx = re.compile(a.png_grep)
        lineas = [ln for ln in lineas if rx.search(ln)]
        nota = f"Extracto: {len(lineas)} de {total} líneas que coinciden con /{a.png_grep}/. Salida completa en {out.name}.txt"
    if a.png_head and len(lineas) > a.png_head:
        lineas = lineas[: a.png_head]
        nota = f"Extracto: primeras {a.png_head} de {total} líneas. Salida completa en {out.name}.txt"
    if a.png_tail and len(lineas) > a.png_tail:
        lineas = lineas[-a.png_tail:]
        nota = f"Extracto: últimas {a.png_tail} de {total} líneas. Salida completa en {out.name}.txt"
    render(out, titulo, mostrado, cwd_rel, fecha, p.returncode, lineas, nota)
    if not a.keep_html:
        out.with_suffix(".html").unlink()
    print(f"[{p.returncode}] {out.with_suffix('.txt')} ({total} líneas)")


if __name__ == "__main__":
    main()
