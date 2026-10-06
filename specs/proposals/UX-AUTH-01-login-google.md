# UX-AUTH-01 — Iniciar sesión con Google

## Contrato

| Ruta | Respuesta |
|---|---|
| `GET /auth/google/login` | 302 a `accounts.google.com` con `scope=openid email profile`, `prompt=select_account` y un `state` firmado. Fija la cookie `dossier_google_login` (HttpOnly, SameSite=Lax, Secure bajo HTTPS, 10 min) con el `nonce` del `state`. |
| `GET /auth/google/callback` | Valida `state` (JWT HS256, `purpose=google_login`, 10 min) y que su `nonce` coincida con la cookie. Canjea el `code`, lee `/v1/userinfo` y redirige a `${FRONTEND_URL}/auth/google#token=<JWT de la app>`. Cualquier fallo redirige a `${FRONTEND_URL}/login?error=google`. |

El token va en el fragmento (`#`), que el navegador no envía a ningún servidor ni queda en los logs.

`redirect_uri`: `GOOGLE_LOGIN_REDIRECT_URI` si está definida; si no, la URL pública de la propia ruta
(`request.url_for`, que respeta `--root-path /api` y las cabeceras del proxy). En producción:
`https://<dominio>/api/auth/google/callback`. Debe estar en las URIs autorizadas del cliente OAuth.

Sin `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` el inicio responde con la redirección de error.

## A quién se le abre sesión

1. Existe `oauth_accounts(provider='google', provider_user_id=sub)` → ese usuario.
2. Si no, existe un usuario con el mismo correo → se vincula (`oauth_accounts`) y queda `email_verified=true`.
   Si ese correo **no estaba verificado**, se anula su contraseña (`password_hash = NULL`): nadie había
   probado ser dueño del correo, y quien creó la cuenta con un correo ajeno no debe conservar acceso.
   El dueño real entra con Google o recupera la contraseña.
3. Si no, se crea: usuario sin contraseña, `email_verified=true`, espacio personal con los créditos de
   alta (`ORG_SIGNUP_CREDITS`) y membresía `admin`.

Se rechaza si Google no marca `email_verified`. La organización de la sesión se elige igual que en
`/auth/login` (`load_session_membership`).

## Fuera de alcance

- Microsoft: el botón queda deshabilitado hasta configurar su OAuth.
- No se guardan los tokens de Google del inicio de sesión (el calendario tiene su propio flujo y permisos).

## Riesgo conocido

La vinculación por correo (paso 2) confía en que Google verificó el correo. Anular la contraseña cierra
el acceso persistente de quien hubiera creado la cuenta con un correo ajeno, pero sus JWT ya emitidos
siguen vigentes hasta caducar (no hay revocación de sesiones) y lo que dejó en el espacio sigue ahí.
Se cierra del todo cuando el alta verifique correos.
