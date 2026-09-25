# 0005 · Proveedor de correo transaccional y entrega de dossiers

- **Fecha:** 2026-09-09
- **Estado:** aceptada
- **Decide:** DG / FO
- **Tarea:** S0.8 (Brecha B5)

## Contexto

La brecha **B5** documenta que el modelo de base de datos incluye desde su origen columnas para control de entrega por correo (`email_sent`, `email_sent_at`, `email_recipients` en `models.py:350-354`), pero el backend carece totalmente de dependencias y servicios de despacho de correo.

En `backend/src/dossier/db/Migracion.md:969-980` existía un diseño previo no implementado que contemplaba la configuración de correo por organización con la cláusula `provider IN ('gmail', 'outlook', 'smtp')` y campos cifrados para servidor SMTP (`smtp_host`, `smtp_port`, `smtp_username`, `smtp_password_encrypted`).

## Alternativas evaluadas

| Alternativa | Ventajas | Desventajas |
|---|---|---|
| **A. Proveedor SaaS exclusivo (Resend / SendGrid / Postmark)** | APIs REST modernas, templates HTML listos, alta entregabilidad. | Exige dominio verificado con registros DNS (SPF/DKIM/DMARC) propiedad del equipo; costes recurrentes; fricción para despliegues locales y ambientes de prueba. |
| **B. SMTP estándar con `aiosmtplib` respetando diseño de `Migracion.md`** | Universal, funciona con cualquier servidor de correo corporativo; no ata el proyecto a un proveedor comercial; compatible con servidores locales de test (MailHog/Inbucket). | Requiere almacenar credenciales cifradas y gestionar reintentos de conexión. |
| **C. Despacho delegado vía OAuth existente (Microsoft Graph / Google Workspace)** | Aprovecha las credenciales que el usuario ya autorizó para el calendario; el correo llega desde la cuenta real del ejecutivo; sin contraseñas adicionales. | Requiere scopes adicionales (`Mail.Send` en Graph, `gmail.send` en Google) que precisan re-consentimiento del usuario. |

## Decisión

Se adopta una **solución dual basada en el diseño original de `Migracion.md`**:

1. **Motor Base de Despacho (S5.6, S6.1):**
   - Se incorpora `aiosmtplib` en `backend/requirements.txt`.
   - Se implementa el servicio `EmailService` soportando configuración SMTP estándar con cifrado TLS/STARTTLS.
   - Las contraseñas se almacenan cifradas en la base de datos utilizando la clave maestra `ENCRYPTION_SECRET` del entorno.
2. **Canal Alternativo OAuth (S6.2):**
   - Para organizaciones con integración de Microsoft Outlook activa y scope extendido, se permite el despacho directo a través del endpoint `/v1.0/me/sendMail` de Microsoft Graph API.
3. **Ambientes de Prueba y CI:**
   - En pruebas automatizadas se utiliza un mock que intercepta llamadas sin salida a red (cumpliendo `testing-policy.md`), registrando `email_sent = True` y `email_sent_at`.

## Consecuencias

- **Cierre de B5:** Se satisfacen las columnas huérfanas en `dossiers` y la automatización programada en `calendar_automation_worker.py`.
- **Plantilla Ejecutiva:** Se diseñará una plantilla HTML/Texto plano responsive para el resumen ejecutivo previo a la reunión (S5.7).
