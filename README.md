# Sistema Dossier

Backend **FastAPI**, consultas **Companies House** y **SEC EDGAR**, síntesis con **DeepSeek**, enriquecimiento de personas con **People Data Labs (PDL)**, calendario **Microsoft Graph / Google** y **PostgreSQL**.

## Estructura (resumen)

| Ubicación | Contenido |
|-----------|-----------|
| **`backend/main.py`** | Arranque del servidor (`uvicorn`) |
| **`backend/src/dossier/api/app.py`** | Rutas HTTP (FastAPI) |
| **`backend/src/dossier/services/`** | Calendario, dossiers, personas (PDL + DeepSeek), organizaciones |
| **`backend/src/dossier/graphs/`** | Grafo LangGraph (agentes UK/US en paralelo → síntesis) |
| **`backend/src/dossier/db/`** | PostgreSQL |
| **`backend/src/dossier/gemini/`** | Shim de compatibilidad → `llm/` (DeepSeek) |
| **`backend/src/dossier/llm/`** | Cliente DeepSeek y utilidades de informes |
| **`backend/src/dossier/companies_house/`** | CLI Reino Unido |
| **`backend/src/dossier/sec_edgar/`** | CLI Estados Unidos |
| **`backend/scripts/`** | Entradas `companies_house.py`, `sec_edgar.py` |
| **`backend/data/`** | JSON y textos generados |
| **`docs/`** | Guías (`estructura.md`, `postgresql.md`, `sec_edgar.md`) |
| **`frontend/`** | Dashboard Next.js (npm; ver su `README.md`) |

Detalle: [docs/estructura.md](docs/estructura.md).

## Configuración

```powershell
cd SistemaDossier/backend
python -m venv .venv
.venv\Scripts\activate
(opcional en linux)source .venv/bin/activate 
pip install -r requirements.txt
copy .env.example .env
```

Los comandos Python siguientes se ejecutan desde `backend/`. El frontend se ejecuta desde `frontend/`.

Guía completa de arranque local (prerrequisitos, base de datos con Alembic, frontend,
verificación y problemas conocidos): [docs/dev/local-setup.md](docs/dev/local-setup.md).

## Arranque de la API

```powershell
python main.py
```

O:

```powershell
$env:PYTHONPATH="src"
uvicorn dossier.api.app:app --reload
```

## CLIs (registros UK / USA)

```powershell
python scripts/companies_house.py
python scripts/sec_edgar.py
```

## Variables de entorno (`.env`)

| Variable | Uso |
|----------|-----|
| `COMPANIES_HOUSE_API_KEY` | API Companies House |
| `SEC_USER_AGENT` | User-Agent «nombre correo» para la SEC (por defecto `Project Dossier contacto@example.com`) |
| `DEEPSEEK_API_KEY` | Síntesis del dossier corporativo e informes de persona |
| `PDL_API_KEY` | Enriquecimiento de personas (People Data Labs) |
| `GEMINI_API_KEY` | Análisis de archivos en CLIs SEC / Companies House |
| `OPENAI_API_KEY` | Solo si activas `DOSSIER_LEGACY_OPENAI=1` (dossier sin LangGraph) |
| `MICROSOFT_*` | Login Outlook / Graph |
| `DATABASE_URL` o `POSTGRES_*` | Base de datos (opcional) |
| `JWT_SECRET` | Firma de JWT para `/auth/*` (necesario para registro/login del dashboard) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Caducidad del token (por defecto 7 días) |
| `CORS_ORIGINS` | Orígenes permitidos para el Next.js (lista separada por comas) |
| `DATABASE_AUTO_CREATE_TABLES` | `0` para no ejecutar `create_all` al arrancar (si ya aplicaste el SQL de migración) |
| `ORG_SIGNUP_CREDITS` / `ORG_SIGNUP_CREDITS_MONTHLY_LIMIT` | Saldo y tope al registrar una org (por defecto **10**; informe tier Free) |
| `DOSSIER_CHARGE_CREDITS` | `true` (defecto): descuenta 1/3/5 créditos por dossier corporativo según profundidad (trigger en PostgreSQL). `0`/`false` desactiva el cobro en demos |

Más: [backend/.env.example](backend/.env.example) y [docs/postgresql.md](docs/postgresql.md).

## Auth del dashboard (email + contraseña) y frontend

El backend usa las tablas del **schema migrado** (`organizations`, `users`, `org_memberships`, `dossiers`, …). Aplica primero el esquema en PostgreSQL — la forma recomendada es `alembic upgrade head` desde `backend/` (S1.1); la alternativa con SQL crudo (**[docs/sql/schema_project_dossier.sql](docs/sql/schema_project_dossier.sql)**, mismo contenido que `backend/src/dossier/db/Migracion.md`) también sirve. Detalle de ambos caminos: [docs/dev/local-setup.md](docs/dev/local-setup.md#3-base-de-datos).

Endpoints principales: **`POST /auth/register`**, **`POST /auth/login`**, **`GET /auth/me`**, **`GET /dossiers`**, **`GET /dossiers/{id}`** (los dossiers requieren JWT con `org_id`).

1. En `backend/.env`: `POSTGRES_*` o `DATABASE_URL`, **`JWT_SECRET`**, y opcionalmente **`DATABASE_AUTO_CREATE_TABLES=0`** si ya creaste el esquema con el SQL.
2. Opcional: **`CORS_ORIGINS`** con la URL del Next.js (por defecto `http://localhost:3000` y `http://127.0.0.1:3000`).
3. En `frontend/`: copia [frontend/.env.local.example](frontend/.env.local.example) a **`frontend/.env.local`** y ajusta `NEXT_PUBLIC_API_URL` si el API no está en `127.0.0.1:8000`.
4. Arranca API (`python main.py`) y el frontend (`npm run dev`); registro e inicio de sesión llaman al backend y guardan el token en `localStorage` o `sessionStorage`.

Detalle: [docs/auth-app.md](docs/auth-app.md).

## Licencia

Sin licencia de uso: todos los derechos reservados por los autores; consultar al equipo.
