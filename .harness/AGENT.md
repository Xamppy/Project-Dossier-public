# Cómo correr el proyecto

Comandos verificados sobre el repositorio. Si algo aquí no funciona, es un defecto de este
archivo: corrígelo en el mismo PR.

## Requisitos

- Python 3.12 (Render usa 3.12.8)
- Node.js con npm
- PostgreSQL
- Redis (opcional; se controla con `DOSSIER_REDIS_ENABLED`)

## Backend

Todo desde `backend/`.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Arranque:

```bash
python main.py
```

Equivalente explícito:

```bash
# Windows PowerShell
$env:PYTHONPATH="src"
uvicorn dossier.api.app:app --reload
```

- API: http://127.0.0.1:8000
- Documentación interactiva: http://127.0.0.1:8000/docs
- Salud: http://127.0.0.1:8000/health

### Pruebas

```bash
python -m pytest -q               # todo: 49 en verde, 13 en espera de su tarea
python -m pytest -m unit          # rápido, mientras desarrollas
python -m pytest -m "not stress"  # si tienes prisa
python -m pytest --cov=src/dossier --cov-report=term-missing
```

Las categorías se asignan solas según la carpeta (`tests/conftest.py`): la raíz de `tests/` es
`unit`, y hay `integration/`, `stress/` y `security/`.

Dos cosas que hace `conftest.py` y conviene saber:

- Fija el entorno mínimo y **apaga los tres trabajadores en segundo plano**. Una prueba no debe
  arrancar hilos que consultan calendarios.
- **Bloquea la red en todas las pruebas.** Si una prueba intenta abrir una conexión, falla con un
  mensaje que lo explica. Simula la respuesta del proveedor; hay una fixture `respuesta_fija`.

Política completa: [`docs/dev/testing-policy.md`](../docs/dev/testing-policy.md).

### Análisis estático

Todavía no existe (tarea **S1.2**). Las herramientas ya están en `requirements-dev.txt`; falta el
`pyproject.toml` que las configure:

```bash
ruff check .
mypy src
```

`scripts/qa.py` los detecta solo en cuanto exista ese archivo.

## Frontend

Todo desde `frontend/`.

```bash
npm install
npm run dev        # webpack, 8 GB de heap
npm run dev:turbo  # turbopack
```

Verificación:

```bash
npm run lint
npm test          # vitest
npm run test:cov  # con cobertura
npm run build
```

Stack: Next.js 16.2.6 · React 19.2.4 · TailwindCSS 4 · TypeScript 5 · Vitest 2

Las pruebas van junto al archivo que prueban: `src/lib/org-role.ts` → `src/lib/org-role.test.ts`.
`vitest.setup.ts` limpia el DOM entre pruebas y **bloquea `fetch`**, igual que el backend bloquea
la red.

> **Aviso.** `npm run lint` reporta hoy 21 errores preexistentes en 16 archivos. No son tuyos: se
> corrigen en **S1.3**. Ver `.harness/fix_plan.md`.

## Base de datos

**No hay migraciones versionadas todavía** (tarea **S1.1**). Hoy:

- El esquema completo está documentado en `backend/src/dossier/db/Migracion.md`
- Los parches se aplican desde `backend/src/dossier/db/schema_patches.py`
- `DATABASE_AUTO_CREATE_TABLES` controla la creación automática de tablas
- SQL suelto en `docs/sql/` y en los `.sql` de `docs/`

Antes de cambiar el esquema, lee los dos primeros y avisa en `progress.md`. Es la única área
que exige aviso previo.

## Variables de entorno

Copia `.env.example` a `.env` en `backend/`. Las que necesitas para trabajar:

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | PostgreSQL |
| `JWT_SECRET` | Firma de tokens. Mínimo 16 caracteres o la API no arranca |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Vigencia del token. Por omisión 10080 = 7 días (ver S3.9) |
| `CORS_ORIGINS` | Orígenes permitidos, separados por coma |
| `DEEPSEEK_API_KEY` · `DEEPSEEK_MODEL` · `DEEPSEEK_BASE_URL` | Síntesis |
| `COMPANIES_HOUSE_API_KEY` | Registros Reino Unido |
| `DOSSIER_REDIS_ENABLED` · `DOSSIER_REDIS_TTL_SECONDS` | Caché |
| `DOSSIER_GENERATION_WORKER_ENABLED` | Trabajador de generación |
| `DOSSIER_RETENTION_WORKER_ENABLED` | Trabajador de retención |
| `CALENDAR_AUTOMATION_ENABLED` | Automatización desde calendario |
| `DOSSIER_ENABLE_LEGACY_OPEN_ROUTES` | Rutas legadas. Debe quedar apagada (ver S1.6) |

Lista completa:

```bash
grep -rhoE 'os\.getenv\("[A-Z_]+"' backend/src --include=*.py | sed 's/os.getenv("//' | sort -u
```

**Nunca** pongas credenciales en el código ni en un commit. Solo variables de entorno.

## Trabajadores en segundo plano

`api/app.py` arranca tres hilos al iniciar y los detiene al cerrar:

| Trabajador | Módulo | Interruptor |
|---|---|---|
| Automatización de calendario | `services/calendar_automation_worker.py` | `CALENDAR_AUTOMATION_ENABLED` |
| Generación de dossiers | `services/dossier_generation_worker.py` | `DOSSIER_GENERATION_WORKER_ENABLED` |
| Retención y purga | `services/dossier_retention_worker.py` | `DOSSIER_RETENTION_WORKER_ENABLED` |

Si estás depurando una sola cosa, apaga los otros dos: reducen ruido en los registros.

## CLIs de registros corporativos

```bash
python scripts/companies_house.py   # Reino Unido
python scripts/sec_edgar.py         # Estados Unidos
```

Salida a `backend/data/`, que está en `.gitignore`.

## Despliegue

| Componente | Servicio | Configuración |
|---|---|---|
| API | Render | `render.yaml` · Blueprint · `rootDir: backend` |
| Dashboard | Vercel | `frontend/vercel.json` |
| PostgreSQL | Neon | ver `docs/render-deploy.md` |

Los secretos se definen en los paneles, nunca en los archivos de configuración.

## Verificación antes de commit y push

No hay integración continua todavía (tarea **S1.5**). Mientras tanto, un solo comando hace ese
trabajo:

```bash
python scripts/qa.py          # antes de commitear
python scripts/qa.py --full   # antes de push, añade el build del frontend
python scripts/qa.py --fast   # solo unitarias, mientras desarrollas
```

Ejecuta únicamente lo que corresponde a lo que cambiaste, y **detiene el commit si tocaste código
sin tocar pruebas**.

Para que corra solo en cada commit y push:

```bash
python scripts/install-hooks.py
```

Ojo: este directorio es un worktree y los ganchos de git se comparten entre todos. El script lo
avisa antes de escribir nada.

Cuando S1.5 esté cerrada, esto lo hará la CI y bloqueará la integración si falla.

## Pruebas de carga

Ya existen, con k6, y necesitan un servidor levantado. No forman parte de `qa.py`:

```bash
k6 run scripts/load/k6-dossier-saturation.js
```

Detalle en `scripts/load/README.md`.
