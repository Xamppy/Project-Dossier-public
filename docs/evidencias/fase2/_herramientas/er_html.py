import html
import sys
from pathlib import Path

mmd = Path(sys.argv[1]).read_text(encoding="utf-8")
out = Path(sys.argv[2])
sha, fecha = sys.argv[3], sys.argv[4]
doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Modelo de datos</title>
<style>body{{margin:0;background:#ffffff;font-family:Segoe UI,Arial,sans-serif;color:#1f2328}}
.wrap{{padding:20px}} h1{{font-size:18px;margin:0 0 4px}} p{{font-size:12px;color:#57606a;margin:0 0 12px}}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js"></script></head>
<body><div class="wrap"><h1>Modelo de datos ORM (Base.metadata de backend/src/dossier/db/models.py)</h1>
<p>Generado desde los metadatos de SQLAlchemy · commit {sha} · {fecha}</p>
<pre class="mermaid">{html.escape(mmd)}</pre></div>
<script>mermaid.initialize({{startOnLoad:true, theme:'default', er:{{useMaxWidth:false}}, maxTextSize:200000}});</script>
</body></html>"""
out.write_text(doc, encoding="utf-8")
