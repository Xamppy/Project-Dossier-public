# AGENTS.md — Índice

Project Dossier · Continuidad hacia el MVP (Proyecto APT, Alloxentric).
Este archivo es un **índice**, no un manual. Cada enlace es la fuente de verdad de su tema.

## Antes de tocar código

| Paso | Archivo | Para qué |
|---|---|---|
| 1 | [.harness/PROMPT.md](.harness/PROMPT.md) | Qué es el proyecto y qué se está construyendo |
| 2 | [.harness/feature_list.json](.harness/feature_list.json) | Qué tareas existen y en qué estado están |
| 3 | [.harness/progress.md](.harness/progress.md) | Qué hicieron las sesiones anteriores |
| 4 | [.harness/handoff.md](.harness/handoff.md) | **Cómo tomar una tarea sin chocar con otro agente** |
| 5 | [docs/dev/testing-policy.md](docs/dev/testing-policy.md) | **Qué pruebas exige tu cambio** |
| 6 | [.harness/AGENT.md](.harness/AGENT.md) | Cómo levantar, probar y desplegar |

Regla corta: **una sesión = una tarea**. Al terminar, actualiza `progress.md` y `feature_list.json`.

## Pruebas: la regla del proyecto

> **Ningún cambio de código entra sin la prueba que lo respalda.** Agregar, modificar y eliminar
> cuentan como cambio.

Se escribe la prueba primero y se comprueba **en rojo** antes de implementar. La tabla de qué
categoría exige cada tipo de cambio está en
[docs/dev/testing-policy.md §1](docs/dev/testing-policy.md).

```bash
python scripts/qa.py          # antes de commitear
python scripts/qa.py --full   # antes de push
```

`qa.py` compara el código cambiado con las pruebas cambiadas y **detiene el commit** si tocaste
código sin tocar pruebas. Para que lo haga solo: `python scripts/install-hooks.py`.

Si la tarea define un contrato nuevo, antes va una especificación:
[docs/dev/sdd-workflow.md](docs/dev/sdd-workflow.md) y [specs/](specs/).

## Estado del proyecto

- Proyecto de **continuidad**: el sistema ya existe y funciona. No se construye desde cero.
- 77 tareas planificadas en Sprint 0 a Sprint 7 · 07-09-2026 al 10-01-2027.
- Plan completo: [docs/documentos-capstone/Plan_de_Trabajo_Detallado_Dossier.pdf](docs/documentos-capstone/Plan_de_Trabajo_Detallado_Dossier.pdf)
- Tablero: https://trello.com/b/XTSgfWKi/capstone-dossier-plan-de-sprints
- Pendientes priorizados: [.harness/fix_plan.md](.harness/fix_plan.md)

## Las cinco brechas del alcance firme

Todo el trabajo comprometido cierra una de estas cinco, o consolida la base para poder cerrarlas.

| | Brecha | Estado | Sprint |
|---|---|---|---|
| **B1** | Síntesis en Markdown sin contrato JSON validado | abierta | 4 |
| **B2** | Sin agente de registros corporativos europeos | abierta | 1-2 |
| **B3** | Sin agente de noticias | abierta | 3 |
| **B4** | Estados por sondeo, no en tiempo real | abierta | 4-5 |
| **B5** | Entrega por correo inexistente | abierta | 5-6 |

Evidencia de cada una: [docs/architecture/gaps.md](docs/architecture/gaps.md)

## Mapa del código

| Ubicación | Contenido |
|---|---|
| `backend/main.py` | Arranque uvicorn |
| `backend/src/dossier/api/` | Rutas HTTP (FastAPI) |
| `backend/src/dossier/services/` | Calendario, dossiers, personas, organizaciones |
| `backend/src/dossier/graphs/` | Orquestador LangGraph (agentes UK/US → síntesis) |
| `backend/src/dossier/db/` | Modelos y esquema PostgreSQL |
| `backend/src/dossier/llm/` | Cliente DeepSeek |
| `backend/src/dossier/companies_house/` · `sec_edgar/` | Registros UK y USA |
| `backend/src/dossier/security/` | JWT, RBAC, contraseñas |
| `backend/src/dossier/billing/` | Créditos, planes, permisos |
| `frontend/src/app/` | Rutas Next.js (dashboard, login, registro) |
| `frontend/src/providers/` | Estado global — `DossierJobsProvider` por SSE (S5.1); `NotificationsProvider` aún sondea (S5.2, B4) |
| `frontend/src/i18n/` | Cinco idiomas: es, en, en-gb, fr, de |

Detalle heredado: [docs/estructura.md](docs/estructura.md)

## Documentación por tema

| Tema | Archivo |
|---|---|
| Política de pruebas | [docs/dev/testing-policy.md](docs/dev/testing-policy.md) |
| Flujo SDD | [docs/dev/sdd-workflow.md](docs/dev/sdd-workflow.md) |
| Especificaciones | [specs/](specs/) |
| Verificación antes de commit | [scripts/README.md](scripts/README.md) |
| Arquitectura y brechas | [docs/architecture/](docs/architecture/) |
| Decisiones técnicas | [docs/architecture/decisions/](docs/architecture/decisions/) |
| Desarrollo y arranque | [.harness/AGENT.md](.harness/AGENT.md) |
| Seguridad | [docs/security/](docs/security/) |
| Planes de ejecución activos | [docs/exec-plans/active/](docs/exec-plans/active/) |
| Base de datos | [docs/postgresql.md](docs/postgresql.md) · [docs/sql/](docs/sql/) |
| Calendario OAuth | [docs/calendario-oauth-operaciones.md](docs/calendario-oauth-operaciones.md) |
| Orquestador | [docs/langgraph-dossier.md](docs/langgraph-dossier.md) |
| Despliegue | [docs/dev/despliegue-vps.md](docs/dev/despliegue-vps.md) (VPS con Docker Compose) · [docs/render-deploy.md](docs/render-deploy.md) · [docs/vercel-frontend.md](docs/vercel-frontend.md) |

## Definición de Terminado

Sin las seis, la tarea no está terminada:

1. Código integrado mediante PR revisado
2. Análisis estático sin errores (backend y frontend)
3. Pruebas asociadas escritas y en verde
4. Revisión por un segundo integrante
5. Documentación actualizada si cambia comportamiento o configuración
6. Evidencia adjunta en la tarjeta de Trello

> Ninguna función se presenta como terminada sin evidencia de implementación, validación y documentación.

## Advertencias vigentes

- **La integración continua corre en GitHub Actions** (S1.5, `.github/workflows/ci.yml`). Corre igual `python scripts/qa.py` antes de cada PR y revisa el resultado en Actions.
- **eslint da 0 errores** en el frontend (S1.3).
- **El esquema se versiona con Alembic** (S1.1, `backend/alembic/versions/`); `db/schema_patches.py` sigue aplicando parches al arrancar y `db/Migracion.md` documenta el esquema. No cambies el esquema sin leer los tres.
- **ruff y mypy están configurados** en `backend/pyproject.toml` (S1.2).
- Las tareas de Sprint 2 en adelante **dependen** de que el Sprint 1 esté cerrado.
