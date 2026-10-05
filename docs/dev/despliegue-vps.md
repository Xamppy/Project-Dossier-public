# Despliegue en un VPS con Docker Compose

Todo el sistema en un solo servidor: **Caddy** (HTTPS automático) delante del **frontend**
Next.js y de la **API** FastAPI, más **PostgreSQL** y **Redis**. Los archivos están en
[`deploy/`](../../deploy); las imágenes, en `backend/Dockerfile` y `frontend/Dockerfile`.

**¿Usas Dokploy?** Ve directo al [§7](#7-desplegar-con-dokploy-desde-github): usa otro compose,
sin Caddy, y el dominio se configura en la interfaz de Dokploy.

```
internet ──443──► Caddy ──/api/*──► backend:8000 (FastAPI + workers) ──► postgres, redis
                        └──resto───► frontend:3000 (Next.js)
```

Un solo dominio: `https://DOMAIN` sirve el dashboard y `https://DOMAIN/api` la API. Como
frontend y API comparten origen, no hay problemas de CORS.

---

## 1. Requisitos del VPS

| Recurso | Mínimo | Por qué |
|---|---|---|
| RAM | 2 GB **más 2 GB de swap**, o 4 GB | Compilar el frontend (`next build`) consume cerca de 1,5 GB |
| Disco | 20 GB | Imágenes, base de datos y respaldos |
| SO | Linux con Docker Engine 24+ y el plugin Compose v2 | — |
| Red | Puertos **80** y **443** abiertos (TCP; 443 también UDP) | Caddy los necesita para emitir y renovar el certificado |

**DNS:** crea un registro **A** del dominio (por ejemplo `dossier.midominio.com`) que apunte a
la IP del VPS **antes** del primer arranque. Si no, Caddy no puede obtener el certificado.

---

## 2. Primer despliegue

```bash
git clone https://github.com/Xamppy/Project-Dossier.git
cd Project-Dossier/deploy
cp .env.example .env
nano .env            # completa DOMAIN, ACME_EMAIL, POSTGRES_PASSWORD, JWT_SECRET y las claves
docker compose up -d --build
```

Qué ocurre al arrancar:

1. Postgres y Redis se levantan; la API espera a que respondan (healthchecks).
2. La API ejecuta `alembic upgrade head`: sobre una base nueva crea el esquema completo
   (22 tablas, 2 vistas y los triggers de cobro de créditos).
3. Caddy obtiene el certificado HTTPS de Let's Encrypt para `DOMAIN`.

Para generar los secretos:

```bash
openssl rand -base64 32   # POSTGRES_PASSWORD
openssl rand -hex 32      # JWT_SECRET
```

### Verificar

```bash
docker compose ps                         # todos "running" / "healthy"
curl https://DOMAIN/api/health            # {"status": "ok", ...}
curl -I https://DOMAIN/login              # 200
docker compose logs -f backend            # migraciones y arranque de workers
```

La documentación interactiva de la API queda en `https://DOMAIN/api/docs`.

### OAuth de calendarios

Registra estas URIs de redirección con tu dominio real:

- Google Cloud Console: `https://DOMAIN/api/callback-google`
- Azure (Microsoft Entra): `https://DOMAIN/api/callback`

Y pon las mismas en `GOOGLE_REDIRECT_URI` y `MICROSOFT_REDIRECT_URI` de `deploy/.env`.

---

## 3. Variables de entorno

Todas van en `deploy/.env` (no se sube a git). El compose fija por su cuenta, con prioridad
sobre `.env`, las que dependen de la topología:

| Variable | Valor que fija el compose |
|---|---|
| `POSTGRES_HOST` / `POSTGRES_PORT` | `postgres` / `5432` |
| `DATABASE_URL` | vacío (la API arma la conexión con los `POSTGRES_*`, así la contraseña admite cualquier carácter) |
| `DATABASE_AUTO_CREATE_TABLES` | `0` (el esquema lo maneja Alembic) |
| `REDIS_URL` | `redis://redis:6379/0` |
| `FRONTEND_URL`, `CORS_ORIGINS` | `https://DOMAIN` |

Variables de comportamiento útiles en `deploy/.env`:

| Variable | Efecto |
|---|---|
| `RUN_MIGRATIONS=0` | No ejecuta `alembic upgrade head` al arrancar (ver §6) |
| `DOSSIER_CHARGE_CREDITS=0` | Desactiva el cobro de créditos (demos) |
| `CALENDAR_AUTOMATION_ENABLED=0` | Apaga la generación automática desde calendarios |

**`NEXT_PUBLIC_API_URL` se incrusta al compilar el frontend.** El compose la arma como
`https://DOMAIN/api`. Si cambias `DOMAIN`, reconstruye: `docker compose up -d --build frontend`.

---

## 4. Operación

### Actualizar a una nueva versión

```bash
cd Project-Dossier && git pull
cd deploy && docker compose up -d --build
```

Las migraciones nuevas se aplican solas al reiniciar la API.

### Logs y estado

```bash
docker compose logs -f --tail=200 backend
docker compose logs -f caddy
docker compose restart backend
```

### Respaldo y restauración de la base

```bash
# Respaldo (programa esto con cron, por ejemplo cada noche)
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > respaldo-$(date +%F).dump

# Restauración sobre la base del compose
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
  < respaldo-AAAA-MM-DD.dump
```

Guarda los respaldos **fuera** del VPS. El volumen `pg_data` desaparece si borras el
proyecto con `docker compose down -v`.

---

## 5. Restricciones de la arquitectura

- **La API corre en un solo proceso** (`--workers 1`) a propósito. Los workers de generación,
  de calendario y de retención son hilos de ese proceso, y el bus del canal SSE vive en su
  memoria. Agregar procesos de uvicorn duplicaría los workers. Escalar exige mover el bus a
  Redis pub/sub y los workers a un servicio propio.
- **Redis es solo caché**: no persiste a disco y está limitado a 128 MB. Perderlo no pierde
  datos; solo regenera dossiers que estaban en caché.

---

## 6. Migrar los datos desde Neon (u otra base existente)

La base actual no tiene `alembic_version`. Si se restaura y luego arranca la API con las
migraciones activas, Alembic intentaría crear de nuevo tablas que ya existen y fallaría. El
orden correcto:

```bash
# 1. Volcar la base de origen (desde tu equipo)
pg_dump "postgresql://USUARIO:CLAVE@HOST_NEON/DB?sslmode=require" -Fc --no-owner > neon.dump

# 2. Levantar solo Postgres en el VPS y restaurar
docker compose up -d postgres
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < neon.dump

# 3. Marcar el esquema como al día (la app ya aplicó esos cambios con sus parches de arranque)
docker compose run --rm --entrypoint alembic backend stamp head

# 4. Levantar todo
docker compose up -d --build
```

Desde ahí, cada migración nueva se aplica sola al actualizar.

---

## 7. Desplegar con Dokploy desde GitHub

[Dokploy](https://docs.dokploy.com) trae su propio Traefik, que ya ocupa los puertos 80 y 443 y
emite los certificados. Por eso usa otro compose:
[`deploy/docker-compose.dokploy.yml`](../../deploy/docker-compose.dokploy.yml). Es el mismo
stack **sin Caddy**: los servicios usan `expose` en vez de `ports` y se unen a
`dokploy-network`.

### 7.1 Crear la aplicación

1. En Dokploy: **Projects → Create Project**, y dentro **Create Service → Compose**.
2. Pestaña **General → Provider**: **GitHub** (conecta la GitHub App de Dokploy al repositorio
   `Xamppy/Project-Dossier`) o **Git** con la URL del repositorio.
   - **Branch:** la rama que quieras desplegar (`FO`, o `main` tras fusionar).
   - **Compose Path:** `./deploy/docker-compose.dokploy.yml`
   - **Compose Type:** Docker Compose.

### 7.2 Variables de entorno

Pestaña **Environment**. Pega el contenido de [`deploy/.env.example`](../../deploy/.env.example)
con tus valores reales. `ACME_EMAIL` no hace falta: los certificados los maneja Dokploy. Dokploy
guarda esto como un `.env` junto al compose, y de ahí lo leen tanto `${DOMAIN}` como el
`env_file` de la API.

### 7.3 Dominios (los dos sobre el mismo host)

Pestaña **Domains → Add Domain**, dos veces:

| Service | Host | Path | Container Port | Strip Path | HTTPS |
|---|---|---|---|---|---|
| `frontend` | `DOMAIN` | `/` | `3000` | no | sí, Let's Encrypt |
| `backend` | `DOMAIN` | `/api` | `8000` | **sí** | sí, Let's Encrypt |

**Strip Path** quita `/api` antes de llegar a la API. Sin eso, las rutas no coinciden
(la API sirve `/health`, no `/api/health`).

### 7.4 Desplegar y verificar

**Deploy**. La primera vez compila ambas imágenes, lo que tarda unos minutos y exige la RAM del
§1 en el servidor de Dokploy. Luego:

```bash
curl https://DOMAIN/api/health   # {"status": "ok", ...}, con Postgres y Redis
curl -I https://DOMAIN/login     # 200
```

En **Logs** del servicio `backend` deben verse las migraciones aplicadas y
`Application startup complete`.

Para redesplegar en cada push, activa **Auto Deploy** (webhook de GitHub). Si cambias `DOMAIN`,
redespliega: la URL de la API se incrusta al compilar el frontend.
