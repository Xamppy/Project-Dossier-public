# 0006 · Protocolo de estados progresivos (SSE vs WebSockets)

- **Fecha:** 2026-09-09
- **Estado:** aceptada
- **Decide:** FO
- **Tarea:** S0.11 (Brecha B4, Riesgo R5)

## Contexto

La brecha **B4** evidencia que el frontend hoy obtiene el avance de generación de dossiers y notificaciones mediante sondeo (`setInterval` de 2 a 3 segundos en `DossierJobsProvider.tsx:285` y `NotificationsProvider.tsx:177`). El backend carece de cualquier mecanismo de emisión push. Las cadenas de internacionalización (`phase.8`) declaran abiertamente esta deuda pendiente.

El objetivo OE4 exige retroalimentación progresiva en tiempo real sobre el estado de cada agente (UK, US, EU, noticias, síntesis).

## Alternativas evaluadas

| Criterio | Server-Sent Events (SSE) | WebSockets (WS) |
|---|---|---|
| **Direccionalidad** | Unidireccional (Servidor → Cliente), ajustado al caso de uso exacto | Bidireccional (innecesario; el cliente no envía comandos continuos por el canal) |
| **Infraestructura (Render / Vercel)** | Excelente: funciona sobre HTTP/1.1 y HTTP/2 estándar sin túneles especiales | Requiere soporte de sockets de larga duración; riesgo de desconexión en balanceadores y proxies |
| **Autenticación con JWT** | Soporta encabezado estándar `Authorization: Bearer <token>` mediante `fetch` / `fetch-event-source` | La API nativa `new WebSocket()` de navegadores no permite enviar headers personalizados (obliga a pasar token por Query Param o ticket efímero) |
| **Reconexión y tolerancia a fallos** | Integrada nativamente con IDs de evento y `retry`; trivial de pausar y reanudar | Requiere lógica manual compleja de heartbeat (ping/pong) y renegociación de sesión |
| **Complejidad de implementación** | Baja: `StreamingResponse` con generador asíncrono en FastAPI (`asyncio.Queue` / Redis PubSub) | Media-Alta: Gestión de pool de conexiones WebSocket y eventos asíncronos |

## Decisión

Se adopta **Server-Sent Events (SSE)** como el protocolo canónico para estados progresivos:

1. **Endpoint en Backend (S4.8):**
   - `GET /dossiers/{id}/stream` (y canal global de organización `GET /events/live`).
   - Retorna `Content-Type: text/event-stream` con `StreamingResponse`.
   - Eventos estandarizados en JSON:
     * `job_status`: estado general (`pending`, `running`, `complete`, `failed`).
     * `agent_progress`: qué agente inició, finalizó o falló (`uk_corporate`, `us_corporate`, `eu_corporate`, `news_agent`, `synthesis`).
     * `partial_result`: datos intermedios listos para renderizar (S4.9).
     * `heartbeat`: pulso cada 15s para evitar timeout de proxies en Render.
2. **Cliente Frontend (S5.1, S5.2, S5.3):**
   - Se adopta `@microsoft/fetch-event-source` para consumir SSE con encabezados JWT `Authorization: Bearer`.
   - Reemplazo secuencial obligatorio (Riesgo R5): primero `DossierJobsProvider`, verificación de estabilidad, y posteriormente `NotificationsProvider`.
   - Implementación de reconexión automática con backoff exponencial y fallback a sondeo degradado si el canal se interrumpe permanentemente.

## Consecuencias

- **Cierre de B4:** Se eliminan los intervalos rígidos de sondeo reduciendo la carga inútil sobre la base de datos PostgreSQL.
- **Experiencia de usuario fluida:** El usuario observa cómo se activan y completan los agentes en tiempo real sin latencias de 3 segundos por refresco.
