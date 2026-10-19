# Fixtures de progreso · S5.10 para S5.4

Frames SSE que **publicó el backend real** (worker, grafo corporativo, investigación de
personas y guardado) con todos los proveedores simulados: PDL, DeepSeek, Companies House,
SEC, registros europeos y prensa. Contrato: [ADR 0009](../../../docs/architecture/decisions/0009-contrato-progreso-por-scopes.md).

| Archivo | Qué muestra |
|---|---|
| `calendario-agente-caido.json` | Calendario: UK falla y el resto completa; un asistente encontrado en PDL y otro sin coincidencias (su dossier queda `failed`) |
| `personas-pdl.json` | Registros PDL: enrich encuentra el perfil, parcial de perfiles antes de la síntesis, informe |
| `personas-pdl-respaldo.json` | El JSON no valida y el respaldo Markdown recupera el informe (`recovered_by`) |
| `personas-pdl-informe-fallido.json` | Perfiles válidos sin informe: job `failed` con el parcial `person_profiles` conservado |
| `personas-web-publica.json` | Web pública: una llamada a DeepSeek sin buscador; el texto llega cuando vuelve |
| `personas-web-publica-fallida.json` | Web pública con el modelo caído: `context_analysis` falla y no hay parciales |
| `personas-cache.json` | Caché antigua (`profiles_count` 2, sin perfiles): nada se ejecuta de nuevo |
| `personas-cancelada.json` | Cancelación durante la investigación: lo posterior ya no se publica |

Cada archivo trae `frames` (en el orden y con el `id` en que los entregaría el stream a un
cliente conectado desde el inicio) y `snapshot_final` (lo que devuelve `GET` del job al
terminar). Los UUID y las fechas están normalizados. En Calendario, los agentes corren en
paralelo: su orden entre sí puede variar de una ejecución a otra.

Para regenerarlas (borra el esquema de esa base, que debe llamarse `…test…`):

```bash
TEST_DATABASE_URL=postgresql://usuario@127.0.0.1:5432/dossier_test backend/.venv/bin/python backend/scripts/generar_fixtures_progreso.py
```

`backend/tests/test_progress_fixtures.py` las valida contra el contrato en cada corrida de la
suite, sin base de datos.

`snapshot_final.result` es el resultado de siempre (sin cambios en S5.10) y, como hoy, incluye
los perfiles de PDL completos; el canal de progreso solo publica la proyección permitida.
