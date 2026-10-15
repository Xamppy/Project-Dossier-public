# BUG-2026-10-14-01 · Límite de contraseña en el registro

Corrección autorizada el 14-10-2026. Se conserva bcrypt y sus hashes existentes.

El formulario admite contraseñas que bcrypt 5.0.0 rechaza por superar 72 bytes
UTF-8. El endpoint termina con HTTP 500. El límite se cuenta sobre UTF-8, sin
recortar ni normalizar la contraseña.

Criterios de aceptación:

1. Registro personal y de empresa con contraseña de entre ocho caracteres y
   72 bytes: HTTP 200, hash bcrypt verificable y login correcto.
2. Más de 72 bytes: HTTP 422 con error de campo `password`, tipo estable
   `password_too_long_bytes`, contexto `max_bytes=72` y mensaje comprensible.
   No debe crearse usuario, organización ni membresía. Aplica también a invitaciones
   porque comparten RegisterRequest; su validación precede a la resolución del token.
3. Probar ASCII de 72/73/128/129 caracteres, `é` de 36/37 caracteres y
   `🔐` de 18/19 caracteres. El mínimo de ocho caracteres se conserva.
4. El formulario bloquea el envío al superar 72 bytes y muestra el error junto
   a la contraseña en los siete idiomas existentes. Acepta exactamente 72 bytes.
5. Si la API devuelve el error de bytes, el frontend lo traduce a ese mismo mensaje,
   sin ocultarlo tras el error genérico del servidor.
6. Contraseñas válidas no se modifican y los duplicados siguen devolviendo 409.

Pruebas: esquema unitario, endpoint con PostgreSQL temporal y verificaciones de
persistencia/aislamiento, componente del formulario y traducción de la API.
No se cambia el esquema de base, el mecanismo de hash, el login, los demás flujos
de credenciales ni los estilos visuales.
