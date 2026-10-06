# Calendario Google / Outlook — definición BD y operaciones

Resumen alineado con vuestro producto: **solo lectura** de eventos futuros para que los agentes vean participantes, asunto y metadatos y generen el dossier. El usuario **elige Google o Microsoft** en la UI; la regla “un proveedor por usuario” se refleja en `UNIQUE (user_id, provider)` en `docs/calendar_integrations_oauth.sql`.

## 1. Base de datos

- Script recomendado: **`docs/calendar_integrations_oauth.sql`**.
- Columnas OAuth:
  - **`refresh_token_encrypted`** / **`access_token_encrypted`**: guardar cifrados con una clave de servidor (p. ej. variable `CALENDAR_TOKEN_ENCRYPTION_KEY`); en MVP algunos equipos guardan en claro — no recomendable en producción.
  - **`access_token_expires_at`**, **`granted_scopes`**: renovación y auditoría.
  - **`provider_subject`** / **`provider_email`**: quién autorizó (útil en soporte y desconexión).
  - **`revoked_at`**: desconectar sin borrar historial.

Si ya aplicaste la tabla desde `Migracion.md` **sin** estas columnas, usa el bloque `ALTER TABLE` comentado al final del `.sql`.

## 2. Microsoft Azure (Outlook) — qué configurar

1. **Azure Portal** → Microsoft Entra ID → **App registrations** → New registration.
2. **Redirect URI**: tipo **Web**, URL exacta de vuestro callback, p. ej.  
   `https://<tu-api-railway>/callback`  
   Debe coincidir **carácter a carácter** con `MICROSOFT_REDIRECT_URI`.
3. **Certificates & secrets** → New client secret → copiar a Railway como `MICROSOFT_CLIENT_SECRET`.
4. **API permissions** → Add → Microsoft Graph → **Delegated**: `Calendars.Read` y **`User.Read`** (perfil `/me`; ver `SCOPES` en `app.py`).
5. Grant admin consent solo si tu tenant lo exige (cuentas corporativas).
6. Railway (u otro host):
   - `MICROSOFT_CLIENT_ID`
   - `MICROSOFT_CLIENT_SECRET`
   - `MICROSOFT_TENANT_ID` → `common` si aceptáis cuentas personales y work/school.
   - `MICROSOFT_REDIRECT_URI` → la misma URL registrada en Azure.
   - **`FRONTEND_URL`** (o `MICROSOFT_OAUTH_SUCCESS_URL`): base del front **sin** barra final, p. ej. `https://tu-app.vercel.app`. Tras OAuth con `state`, `/callback` redirige a  
     `{FRONTEND_URL}?calendar_microsoft=ok` o `...?calendar_microsoft=error&reason=...`.

**Flujo integrado (implementado):** `GET /integrations/microsoft/start` con JWT de la app (cabecera `Authorization: Bearer`). Parámetro **`as_json=true`** devuelve `{"authorize_url": "..."}` para SPAs; sin él, responde **302** a Microsoft. El `state` lleva `user_id` y `org_id`; en `/callback` se persisten tokens en **`calendar_integrations`** y se redirige al front.

**Pruebas sin usuario de la app:** `GET /login-microsoft` (sin `state`) sigue devolviendo JSON con `access_token` en `/callback` (legado).

**Lectura de eventos (Outlook) con JWT:** `GET /calendario/eventos`, `GET /calendario/diagnostico-microsoft` y `GET /calendario/generar-dossiers` usan **`Authorization: Bearer <JWT de la app>`**; el backend obtiene o renueva el token de Microsoft Graph desde **`calendar_integrations`** (refresh vía MSAL). El query **`?access_token=`** con un token de Graph sigue admitido solo como atajo de pruebas.

**Generar dossier desde una reunión:** `GET /calendario/generar-dossiers?event_id=<id Graph>` procesa solo ese evento; sin `event_id` usa las próximas reuniones hasta `top` (ver OpenAPI). El frontend (Resumen) puede llamar a este endpoint tras listar eventos.

## 3. Google Cloud (Calendar) — qué configurar

1. **Google Cloud Console** → proyecto → **APIs & Services** → Enable **Google Calendar API**.
2. **OAuth consent screen** (externo o interno según usuarios).
3. **Credentials** → OAuth 2.0 Client ID:
   - Tipo **Web application**.
   - **Authorized redirect URIs**: URL exacta del callback de la API, p. ej.  
     `https://<tu-api-railway>/callback-google`  
     Debe coincidir con **`GOOGLE_REDIRECT_URI`**.
4. Scopes usados por la API (solo lectura + email): `openid`, `userinfo.email`, `calendar.readonly` (ver `GOOGLE_OAUTH_SCOPES` en `app.py`).
5. Variables en Railway (o `.env` local):
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
   - **`FRONTEND_URL`**: igual que Microsoft; tras OAuth la API redirige a  
     `{FRONTEND_URL}?calendar_google=ok` o `...?calendar_google=error&reason=...`

**Inicio de sesión (otro flujo, mismo cliente OAuth):** `GET /auth/google/login` → Google →
`GET /auth/google/callback`. Pide solo `openid email profile`, no guarda tokens de Google y necesita
su propia URI autorizada: `https://<api>/auth/google/callback` (detrás del proxy, `.../api/auth/google/callback`).
Ver `specs/proposals/UX-AUTH-01-login-google.md`.

**Flujo integrado (implementado):** `GET /integrations/google/start` con JWT (`Authorization: Bearer`). **`as_json=true`** devuelve `{"authorize_url": "..."}` para el SPA. El `state` lleva `user_id` y `org_id`; en **`GET /callback-google`** se intercambia el `code` por tokens y se persisten en **`calendar_integrations`** (`provider='google'`).

**Lectura y dossiers con JWT:** `GET /calendario/eventos-google` y `GET /calendario/generar-dossiers-google` (mismo patrón que Outlook; query opcional `?access_token=` solo para pruebas).

**Legado:** `POST /calendario/generar-dossier-google` con `access_token` en query sigue disponible para pruebas manuales.

## 4. Frontend (decisión Google vs Outlook)

- Tras registro/login con JWT: en el **Resumen** del dashboard hay tarjetas **Microsoft Outlook** y **Google Calendar**.
- **Outlook:** `GET /integrations/microsoft/start?as_json=true` con Bearer → `authorize_url` → vuelta con `?calendar_microsoft=ok|error`.
- **Google:** `GET /integrations/google/start?as_json=true` con Bearer → `authorize_url` → vuelta con `?calendar_google=ok|error`.

## 4 bis. Lectura de eventos por intervalo (calendario visual)

`GET /calendario/eventos-google`, `/calendario/eventos-outlook` y `/calendario/eventos` aceptan, además del
modo legado, `desde` y `hasta` (RFC3339 **con offset**, `desde` inclusivo, `hasta` exclusivo, máximo 62 días).

- Se devuelven los eventos que **se solapan** con el intervalo, con recurrencias expandidas y sin ocurrencias
  canceladas. Sin `desde`/`hasta` el comportamiento y la respuesta no cambian.
- Mezclar el intervalo con `top`, `dias` o `incluir_pasadas`, enviar solo uno de los extremos, fechas sin
  offset, orden inverso o más de 62 días devuelve **422**.
- El servidor recorre la paginación del proveedor (`nextPageToken` en Google, `@odata.nextLink` en Graph) con
  tope de **10 páginas de 250** y **20 s** por proveedor. Si se alcanza un límite o falla una página posterior,
  responde 200 con lo recuperado y `completo: false` + `motivo_incompleto`
  (`limite_paginas`, `tiempo_agotado` o `error_proveedor`). Si no hay ninguna página válida: **502** (error
  remoto) o **504** (timeout); nunca «sin reuniones». 401 y 404 conservan su significado.
- Respuesta: `total`, `reuniones`, `mensaje`, `rango`, `completo`, `motivo_incompleto`. `total` es el número
  devuelto, no una estimación del proveedor.
- Los eventos con hora usan instantes ISO con offset (Outlook, en UTC con `Z`). Los de **día completo** usan
  fechas `YYYY-MM-DD` con fin exclusivo; en Outlook se resuelven con `originalStartTimeZone` (nombres de
  Windows o IANA) y, si la zona no se reconoce, con la medianoche UTC más cercana.
- Los tokens OAuth no salen del servidor; `nextLink` solo se sigue hacia `https://graph.microsoft.com` y rutas
  `calendarView`.

Código: `backend/src/dossier/services/calendar_range.py`, `google_calendar_api.py`, `graph_calendar.py`. En el
cliente, `frontend/src/hooks/useCalendarEvents.ts` consulta ambos proveedores en paralelo para el intervalo
visible. Evidencia: [reporte UX-CAL-02](../specs/reports/UX-CAL-02-calendario-visual.md).

## 5. Despliegue “cuando esté todo listo”

- Misma API en Railway: actualizar redirect URIs en Google y Azure con la URL **de producción**.
- Rotar secrets si alguna vez se filtraron en logs o en el front.
- Probar con un usuario de prueba: conectar → listar eventos → job de dossier.
