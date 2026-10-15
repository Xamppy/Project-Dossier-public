# Autenticación del dashboard (app)

Cuentas con **email y contraseña** guardadas en **PostgreSQL**, sesión con **JWT** (HS256). Es independiente del flujo **Microsoft** (`/login-microsoft`) usado para el calendario Graph.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/auth/register` | Crea `organizations` + `users` + `org_memberships`, devuelve JWT y perfil. |
| `POST` | `/auth/login` | Valida credenciales; JWT incluye `org_id` de la organización primaria. |
| `GET` | `/auth/me` | Cabecera `Authorization: Bearer <token>`; devuelve perfil + `organization_id` + `role`. |
| `GET` | `/dossiers` | Lista dossiers de la org del JWT (tabla `dossiers`). |
| `GET` | `/dossiers/{id}` | Detalle de un dossier de tu organización. |
| `DELETE` | `/dossiers/{id}` | Elimina un dossier de tu organización (respuesta `204 No Content`). |

Cuerpos JSON esperados:

- **register:** `{ "email", "password", "full_name", "company_name" }`
- **login:** `{ "email", "password" }`

### Límite de contraseña al registrarse

El registro conserva bcrypt y requiere al menos ocho caracteres y como máximo
**72 bytes en UTF-8**. Las letras acentuadas y los emojis pueden ocupar varios bytes:
36 caracteres `é` ocupan 72 bytes; 37 ocupan 74 y se rechazan. La contraseña nunca
se recorta ni se normaliza.

El formulario muestra el error junto a la contraseña antes de enviarla, en el idioma
de la interfaz. La API también valida el límite (incluido el registro por invitación)
y devuelve **HTTP 422** con `loc: ["body", "password"]`,
`type: "password_too_long_bytes"` y `ctx: {"max_bytes": 72}`. El mensaje explica
que debe usarse una contraseña más corta. El intento inválido no crea cuenta,
organización ni membresía. Este cambio no modifica los hashes existentes ni el login.

## Variables de entorno

- **`JWT_SECRET`**: obligatoria para firmar tokens (mínimo 16 caracteres; en producción, 32+ aleatorios).
- **`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`**: opcional (por defecto `10080` = 7 días).
- **`ORG_SIGNUP_CREDITS`**: opcional — créditos iniciales de la **organización** al completar `POST /auth/register` (entero ≥ 0; por defecto `500` en código si no está en `.env`).
- **`ORG_SIGNUP_CREDITS_MONTHLY_LIMIT`**: opcional — tope mensual de la org al registrarse; si no se define, coincide con `ORG_SIGNUP_CREDITS`.
- **`CORS_ORIGINS`**: orígenes del frontend (coma). Por defecto incluye `http://localhost:3000` y `http://127.0.0.1:3000`.
- PostgreSQL: **`DATABASE_URL`** o **`POSTGRES_*`** como en [postgresql.md](postgresql.md).

## Tablas y migración

El DDL oficial está en **`docs/sql/schema_project_dossier.sql`** (copia del archivo `backend/src/dossier/db/Migracion.md`). Ejecútalo en tu instancia PostgreSQL antes de usar registro/login y dossiers.

Si en `.env` pones **`DATABASE_AUTO_CREATE_TABLES=0`**, la API **no** ejecutará `create_all` al arrancar (solo usará lo que ya creaste con el SQL).

Para producción se recomienda **Alembic** u otro sistema de migraciones versionadas.

## Frontend

En `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

El cliente guarda el JWT en `localStorage` (login con “recuérdame” o tras registro) o `sessionStorage` (login sin recordar).

## Si “no se guarda” en la base pero ves “email ya existe”

Ese mensaje (**HTTP 409**) solo puede salir si el backend **sí** consultó PostgreSQL y encontró el email en la tabla **`users`** (no `app_users`). Es decir: la petición del navegador **llegó** a la API y la API **vio** ese correo en la BD que tiene configurada en su `.env`.

Causas habituales de confusión:

1. **Primera petición ya creó el usuario** (respuesta 200) y la UI pareció fallar (redirección, pestaña de red, etc.); al reintentar obtienes 409.
2. **pgAdmin u otra herramienta** está conectada a **otro servidor o otra base** que la API. Compara con `GET /db/health`: si `postgresql` es `ok`, el JSON incluye `connection` (`host`, `port`, `database`) **sin contraseña**. Debe coincidir con la conexión donde miras las tablas.
3. **`NEXT_PUBLIC_API_URL`** del frontend no apunta al mismo backend que crees (otro puerto, contenedor, etc.). Tras cambiar `.env.local` hay que **reiniciar** `npm run dev`.

Errores **422** suelen ser validación (campos vacíos, contraseña corta, etc.); el mensaje en pantalla ahora incluye el nombre del campo cuando FastAPI lo devuelve en `loc`.
