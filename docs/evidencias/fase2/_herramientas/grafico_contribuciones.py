"""HTML con Chart.js (cdnjs) a partir del JSON de contribuciones.py; luego se captura a PNG.

    python grafico_contribuciones.py contrib.json salida.html <sha> "<fecha>"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

datos = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["integrantes"]
sha, fecha = sys.argv[3], sys.argv[4]
quienes = ["FO", "DG", "FD"]
etiquetas = [f"{k} · {datos[k]['nombre']}" for k in quienes]
colores = {"FO": "#2a78d6", "DG": "#eb6834", "FD": "#1baf7a"}
paneles = [
    ("Commits sin merges en main", [datos[k]["commits"] for k in quienes], None),
    ("Líneas añadidas (sin lockfile, fixtures, binarios ni el commit raíz heredado)",
     [datos[k]["lineas_mas_sin_raiz"] for k in quienes], None),
    ("Pull requests mezclados (autor del PR)", [datos[k]["pr_mezclados"] for k in quienes], None),
    ("Tareas del harness en estado done (owner)", [datos[k]["tareas"].get("done", 0) for k in quienes], None),
]
html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Aporte por integrante</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
body{{margin:0;background:#ffffff;color:#1f2328;font-family:'Segoe UI',Arial,sans-serif}}
.wrap{{padding:24px 28px;width:1240px}} h1{{font-size:20px;margin:0 0 4px}}
.sub{{font-size:13px;color:#57606a;margin:0 0 16px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.card{{border:1px solid #d0d7de;border-radius:8px;padding:12px 14px}}
.card h2{{font-size:14px;margin:0 0 8px;font-weight:600}}
.leyenda{{display:flex;gap:18px;font-size:13px;margin:0 0 14px}}
.leyenda span::before{{content:'';display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px;background:var(--c)}}
footer{{font-size:12px;color:#57606a;margin-top:14px}}
</style></head><body><div class="wrap">
<h1>Aporte por integrante · origin/main</h1>
<div class="sub">Fuente: docs/evidencias/fase2/contribuciones/02-aporte-por-integrante.txt (git log, gh pr list, .harness/feature_list.json). Ver sesgos en contribuciones/README.md.</div>
<div class="leyenda">{''.join(f'<span style="--c:{colores[k]}">{e}</span>' for k, e in zip(quienes, etiquetas))}</div>
<div class="grid">{''.join(f'<div class="card"><h2>{t}</h2><canvas id="c{i}" height="210"></canvas></div>' for i, (t, _, _) in enumerate(paneles))}</div>
<footer>commit {sha} · {fecha} · Project Dossier · evidencia Fase 2</footer></div>
<script>
const valores = {{id:'valores', afterDatasetsDraw(ch){{const c=ch.ctx;c.save();c.fillStyle='#1f2328';c.font='600 13px Segoe UI';c.textAlign='center';
ch.getDatasetMeta(0).data.forEach((b,i)=>{{c.fillText(ch.data.datasets[0].data[i].toLocaleString('es-CL'), b.x, b.y-6);}});c.restore();}}}};
const paneles = {json.dumps([v for _, v, _ in paneles])};
paneles.forEach((v,i)=>new Chart(document.getElementById('c'+i), {{type:'bar',
  data:{{labels:{json.dumps(quienes)}, datasets:[{{data:v, backgroundColor:{json.dumps([colores[k] for k in quienes])}, borderRadius:4, maxBarThickness:70}}]}},
  options:{{animation:false, responsive:true, layout:{{padding:{{top:22}}}}, plugins:{{legend:{{display:false}}, tooltip:{{enabled:true}}}},
    scales:{{x:{{grid:{{display:false}}, ticks:{{color:'#57606a'}}}}, y:{{beginAtZero:true, grid:{{color:'#eaeef2'}}, ticks:{{color:'#57606a'}}, border:{{display:false}}}}}}}},
  plugins:[valores]}}));
</script></body></html>"""
Path(sys.argv[2]).write_text(html, encoding="utf-8")
