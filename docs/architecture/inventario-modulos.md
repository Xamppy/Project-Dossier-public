# Inventario de módulos y contraste con Especificaciones v2.0

- **Fecha:** 2026-09-09
- **Estado:** completado
- **Responsable:** EQ (Equipo)
- **Tarea:** S0.1

---

## 1. Módulos del Backend (`backend/src/dossier/`)

| Módulo / Paquete | Responsabilidad actual | Estado vs Especificación v2.0 | Acción Sprint 0 / 1 / Sprints posteriores |
|---|---|---|---|
| `api/app.py` | FastAPI application, middleware CORS, ciclo de vida (workers) | Funcional; CORS excesivamente permisivo en desarrollo (`*`) | Corregir CORS en S3.8; registrar rutas SSE en S4.8. |
| `api/routes/auth_routes.py` | Registro, login, cambio de contraseña, me | Funcional; token 7 días en localStorage | Reducir expiración de access token a 15m con refresh token en S3.9. |
| `api/routes/dossier_routes.py` | CRUD de dossiers, reintento, exportación | Funcional; opera con JSONB sin validar | Conectar validador Pydantic en S4.1 y stream en S4.8. |
| `api/routes/organization_routes.py` | Gestión de orgs, miembros e invitaciones | Funcional con aislamiento multi-tenant | Mantener; agregar pruebas negativas de seguridad en S6.7. |
| `services/person_research_pipeline.py` | Pipeline de investigación de personas (PDL + LLM) | Persiste Markdown bajo clave `gemini_analysis_markdown` | Desacoplar shim Gemini (S1.6), emitir JSON estructurado (S4.2). |
| `services/calendar_automation_worker.py` | Worker en segundo plano de sincronización de eventos | Funcional; busca reuniones cada 60s | Conectar generación automática de dossiers y envío de correo (S6.1). |
| `services/dossier_generation_worker.py` | Worker asíncrono que procesa la cola de dossiers | Funcional; procesa tareas pendientes | Emitir eventos progresivos a Redis/SSE en S4.8. |
| `services/dossier_retention_worker.py` | Purga periódica según días de retención | Retención de 7-90 días (por defecto 30) | Adaptar a retención estricta de 24h con borrado verificado en S6.5. |
| `services/corporate_registry_context.py` | Generadores de Markdown para UK y US | Devuelve cadenas Markdown formateadas | Normalizar a modelo común `RegistroCorporativo` en S1.9 / S2.3. |
| `graphs/corporate_dossier_graph.py` | Orquestador LangGraph de dossiers corporativos | Solo orquesta UK (`companies_house`) y US (`sec_edgar`) | Incorporar nodo EU (S2.1) y nodo Noticias (S3.2) con tolerancia a fallos. |
| `companies_house/` | Cliente API oficial Companies House (UK) | Funcional con caché | Integrar en modelo común de registro (S1.9). |
| `sec_edgar/` | Cliente API SEC EDGAR (US) | Funcional con caché | Integrar en modelo común de registro (S1.9). |
| `llm/client.py` | Cliente DeepSeek (`deepseek-chat`) | Funcional con reintentos y timeouts | Establecido como línea canónica (ADR 0001). |
| `gemini/analyze.py` | Shim de reexportación de `dossier.llm.*` | Confuso y redundante | Marcar deprecado para eliminación en S1.6. |
| `services/openai_dossier.py` | Generación directa monolítica con GPT-3.5 | Código legado obsoleto | Marcar deprecado para retiro en S1.6. |
| `db/models.py` | Modelos SQLAlchemy (PostgreSQL) | Esquema funcional | Agregar tablas de alertas, trayectoria y prensa en S4.5. |
| `db/schema_patches.py` | Aplicación manual de parches de esquema | Deuda técnica P0 (sin Alembic) | Migrar a migraciones versionadas Alembic en S1.1. |

---

## 2. Módulos del Frontend (`frontend/src/`)

| Directorio / Módulo | Responsabilidad | Estado vs Especificación v2.0 |
|---|---|---|
| `app/dashboard/` | Vistas principales (dossiers, carpetas, personas, configuración) | Funcional; 21 errores preexistentes de linting (S1.3). |
| `providers/DossierJobsProvider.tsx` | Gestión del estado de generación de dossiers | Usa sondeo `setInterval(..., 2000)` (Brecha B4). Reemplazar por SSE en S5.1. |
| `providers/NotificationsProvider.tsx` | Polling de notificaciones de usuario | Usa `setInterval` (Brecha B4). Reemplazar por SSE en S5.2. |
| `components/CorporateDossierDetailView.tsx` | Visualización del informe corporativo | Renderiza Markdown mediante `react-markdown` (Brecha B1). Migrar a componentes estructurados en S5.5. |
| `i18n/` | Internacionalización (es, en, en-gb, fr, de) | Funcional y completo en 5 idiomas. Actualizar cadenas de mock WebSocket en S3.7. |
