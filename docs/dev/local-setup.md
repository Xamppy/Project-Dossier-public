# Arranque local del proyecto

Tarea **S1.7**. Guía completa de cero a tener backend + frontend corriendo en tu máquina.
El resumen que ya estaba en [`README.md`](../../README.md) sigue siendo válido; esta guía
lo desarrolla, corrige una referencia rota (ver §3) y agrega los pasos que faltaban:
variables de entorno del frontend, alternativa con Alembic, y verificación de que quedó
todo bien antes de dar por terminado el arranque.

---

## 1. Prerrequisitos

| Herramienta | Versión mínima | Por qué |
|---|---|---|
| Python | **3.12** | El backend usa `typing.Self` (requiere ≥3.11); `pyproject.toml` (S1.2) fija `target-version = "py312"` |
| Node.js | 20+ | Next.js 16 / React 19 |
| PostgreSQL | 14+ | Usa `uuid-ossp`, `pgcrypto`, triggers en PL/pgSQL — extensiones estándar de cualquier instalación completa de Postgres (no funcionan en builds minimalistas/embebidos) |
| git | — | — |

---

## 2. Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pytest, ruff, mypy, pip-audit (S1.2 / S0.3)
copy .env.example .env
```

Completa `backend/.env` — como mínimo:

- `DATABASE_URL` (o los `POSTGRES_*` sueltos) — ver §4.
- `JWT_SECRET` — cualquier cadena de 16+ caracteres para desarrollo local.

El resto de variables (`DEEPSEEK_API_KEY`, `PDL_API_KEY`, `MICROSOFT_*`, `GOOGLE_*`, etc.)
son opcionales para levantar la API: cada integración se apaga sola si falta su clave.
Detalle de cada variable: [`backend/.env.example`](../../backend/.env.example).

---

## 3. Base de datos

Hay dos caminos. **El recomendado es Alembic** (S1.1) — es un solo comando y deja el
esquema con el número de revisión aplicado, en vez de tener que llevar la cuenta a mano.

### 3.1 Con Alembic (recomendado)

```powershell
cd backend
$env:DATABASE_URL="postgresql://usuario:clave@localhost:5432/sistemadossier"
alembic upgrade head
```

Esto crea el esquema completo (22 tablas: las 19 de `Migracion.md` más `dossier_shares`,
`org_invites` y la cola `dossier_generation_jobs`; 2 vistas y 9 triggers/funciones, incluido el
trigger real de cobro de créditos) **y** aplica los parches de `db/schema_patches.py`
(columnas agregadas después). Es idempotente: si ya
aplicaste el SQL a mano antes (opción 3.2), correr esto después no debería fallar ni
duplicar nada — pero si tu base ya tiene el esquema completo, no hace falta correrlo.

Con `DATABASE_AUTO_CREATE_TABLES=0` en `.env` (recomendado si usas Alembic), la app no
intenta crear tablas por su cuenta al arrancar.

### 3.2 A mano, con el SQL crudo

Si prefieres no usar Alembic, o necesitas inspeccionar/adaptar el DDL antes de aplicarlo:

```powershell
psql -U postgres -d sistemadossier -f docs/sql/schema_project_dossier.sql
```

> **Corregido en S1.7:** este archivo estaba vacío (0 bytes) — un hallazgo que ya traía
> el informe de auditoría anterior y que Alembic (S1.1) dejó en evidencia otra vez al
> tener que reconstruir el esquema desde cero. Ahora tiene el mismo contenido que
> [`backend/src/dossier/db/Migracion.md`](../../backend/src/dossier/db/Migracion.md), que
> es la fuente real. Si sigues este camino, **corre también** los parches de
> `backend/src/dossier/db/schema_patches.py` justo después — si no, te van a faltar
> `dossier_shares`, `org_invites`, la cola `dossier_generation_jobs` y varias columnas nuevas. La app los aplica sola en
> cada arranque (`api/app.py:lifespan()`), así que basta con levantar la API una vez.

### 3.3 Verificar que quedó bien

```sql
-- Deberían ser 22 tablas + 2 vistas (23 tablas si usaste 3.1, por alembic_version)
SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';
SELECT count(*) FROM information_schema.views WHERE table_schema='public';
```

---

## 4. Arranque de la API

```powershell
cd backend
python main.py
```

O, equivalente:

```powershell
$env:PYTHONPATH="src"
uvicorn dossier.api.app:app --reload
```

Prueba rápida: `http://127.0.0.1:8000/` debería responder (expone `config_check`, útil
para confirmar qué integraciones quedaron activas según tu `.env`).

---

## 5. Frontend

```powershell
cd frontend
npm install
copy .env.local.example .env.local
```

Ajusta `NEXT_PUBLIC_API_URL` en `.env.local` si el backend no está en
`http://127.0.0.1:8000`.

```powershell
npm run dev
```

`http://localhost:3000` debería cargar el dashboard. Registro/login llaman al backend
(`/auth/register`, `/auth/login`) y guardan el token en el navegador — necesitas el
backend corriendo y la base de datos con el esquema aplicado (§3) antes de probar esto.

---

## 6. Verificación rápida de que todo quedó funcionando

```powershell
# Backend: pruebas + analisis estatico (S1.2/S1.3)
cd backend
pytest
ruff check src/dossier
mypy src/dossier

# Frontend: lint + build
cd ../frontend
npm run lint
npm run build
```

`python scripts/qa.py` (desde la raíz) corre el subconjunto relevante a lo que cambiaste;
`--full` agrega el build del frontend. Ver [`.harness/handoff.md`](../../.harness/handoff.md) §6.

---

## 7. Problemas conocidos

- **`docs/sql/schema_project_dossier.sql` vacío** — corregido en S1.7 (§3.2). Si tu copia
  local es de antes de este cambio, actualízala.
- **Modelos ORM incompletos.** `backend/src/dossier/db/models.py` declara menos tablas que
  el esquema real (ver hallazgo en `.harness/fix_plan.md`). No afecta el arranque, pero si
  vas a correr `alembic revision --autogenerate` más adelante, lee esa nota primero —
  puede proponer borrar tablas reales que el ORM no conoce.
- **Windows + red/OneDrive.** Si tu carpeta del proyecto está en una unidad de red o
  sincronizada (OneDrive, etc.), `npm install` puede fallar de forma intermitente con
  `ENOTEMPTY` al instalar paquetes con binarios nativos (p. ej. `sharp`). Reintentar
  `npm install` una vez suele resolverlo; si persiste, mueve el proyecto a un disco local.
