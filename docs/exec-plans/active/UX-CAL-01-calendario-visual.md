# UX-CAL-01 · Sustituir lista por calendario visual

- **Estado:** planificación preparada; implementación en UX-CAL-02 (rama abierta, pendiente de revisión)
- **Fecha:** 2026-10-02
- **Responsable propuesto:** DG, con soporte FO y revisión FD
- **Rama de implementación propuesta:** `codex/UX-CAL-01-calendario-visual`
- **Especificación:** [comportamiento y aceptación](../../../specs/proposals/UX-CAL-01-calendario-visual.md)
- **Decisión propuesta:** [FullCalendar Standard](../../architecture/decisions/0007-calendario-visual.md)

## Resultado esperado

En `/dashboard/automation`, el usuario comprende su agenda en vistas semana, mes y día y abre
una reunión para generar o consultar su dossier. Las reuniones corresponden al período visible,
con advertencia cuando un proveedor entrega información incompleta.

## Secuencia de implementación

| Paso | Entregable | Esfuerzo orientativo |
|---|---|---|
| 1 | Revisar spec y ADR; priorizar trabajo, asignar tarjeta y reclamar tarea conforme a handoff; validar versión de librería con React/Next y datos ficticios | 0,5–1 día |
| 2 | TDD del contrato por rango, paginación Google/Graph, fechas y límites; mantener modo legado | 1,5–2 días |
| 3 | TDD del adaptador y hook de consulta; concurrencia, caché de sesión, errores y respuestas tardías | 0,5–1 día |
| 4 | TDD del calendario, detalle y asociación de jobs por proveedor; integrar en página y conservar acciones | 1–1,5 días |
| 5 | Temas, siete locales, teclado/móvil, verificación de aceptación, documentación y PR | 1–1,5 días |

**Estimación:** 5–7 días de desarrollo de una persona familiarizada con el repositorio;
no incluye espera de revisión o resolución de deuda preexistente. Revisar al finalizar la prueba
de biblioteca y de fechas de día completo. No representa una fecha comprometida.

## Archivos previstos

| Área | Archivos |
|---|---|
| Vista | `frontend/src/app/dashboard/automation/page.tsx`, `components/dashboard/AutomationCalendarPreview.tsx`, extracción de responsabilidades de `CalendarMeetingsList.tsx` |
| Nuevos componentes propuestos | `frontend/src/components/dashboard/MeetingsCalendar.tsx`, `CalendarEventDetails.tsx`, sus `.test.tsx` y estilos locales |
| Datos cliente | `frontend/src/lib/dossier-api.ts`, nuevo `calendar-events.ts` y `hooks/useCalendarEvents.ts`, con pruebas |
| Jobs y preferencias | Ajuste acotado de `frontend/src/providers/DossierJobsProvider.tsx` con prueba; reutilizar PreferencesProvider y CalendarDossierPreview |
| Dependencias / idioma | `frontend/package.json`, lockfile, `src/i18n/calendar-ui-labels.ts` y mensajes pertinentes |
| Backend | `backend/src/dossier/api/app.py`, `services/google_calendar_api.py`, `services/graph_calendar.py`, nuevo esquema de rango si corresponde |
| Pruebas backend | `backend/tests/test_calendar_event_range.py`, `integration/test_calendar_event_routes.py`, `security/test_calendar_event_access.py`, `stress/test_calendar_event_pagination.py` (nombres propuestos) |
| Evidencia | Manual operativo, reporte en `specs/reports/`, harness y tarjeta Trello |

No iniciar la implementación sobre el árbol compartido sin revisar de nuevo cambios y tareas
activas. En esta evaluación ya había cambios de otra sesión en `feature_list.json` y `progress.md`;
se conservan. Los nuevos documentos son borradores, no evidencia de una función implementada.

## Verificación de entrega

- [x] Revisar frontend, rutas, clientes y preferencias; comparar bibliotecas con fuentes oficiales.
- [x] Dejar especificación y decisión propuesta, con criterios verificables.
- [x] Fijar prioridad y versión, reclamar implementación y abrir su rama (UX-CAL-02, FullCalendar 7.1.0).
- [x] Ejecutar TDD de cada criterio y guardar evidencia RED → GREEN (seguridad y estrés del backend: ver H5 del reporte).
- [x] Ejecutar suite frontend/backend relevante y análisis estático (eslint y tsc sí; ruff/mypy no disponibles).
- [ ] Revisar visualmente navegador, móvil, teclado, temas y siete locales con datos ficticios. **Parcial:** 1440 y 375 px, temas, es/de; falta 768 px y resto de idiomas; el shell no es responsive (H2).
- [x] Ejecutar `python scripts/qa.py` antes de commit y `python scripts/qa.py --full` antes de push (solo fallan los dos preexistentes).
- [ ] Adjuntar capturas y resultados al PR y a Trello; obtener revisión de otro integrante.
- [x] Completar reporte contra CA1–CA11 ([reporte](../../../specs/reports/UX-CAL-02-calendario-visual.md)); solo el revisor marca la implementación `done`.

## Riesgos y decisiones prácticas

- **Calendario incompleto:** `top=14/50` no sirve para una agenda mensual. Resolver intervalo y
  paginación antes de conectar el grid con datos reales.
- **Días desplazados:** distinguir instantes de fechas civiles; fixture de Outlook de día completo
  con zona distinta de UTC y cambios horarios. Es el principal punto técnico aún por validar.
- **Módulo comprimido:** dar ancho al calendario y mover reglas a sección plegable; no añadir una
  segunda barra lateral a una página que ya tiene navegación lateral.
- **Regresión en dossiers:** extraer detalle con pruebas y conservar identidad original del evento;
  añadir proveedor al seguimiento del job sin rehacer el sistema de estados.
- **Coste de dependencias:** cargar calendario solo en esta ruta y medir el efecto del build;
  no se ha medido bundle ni rendimiento en esta sesión.
- **Prioridad:** mejora adicional al alcance firme. No acredita cierre de B4 ni cambia el plan de
  automatización. Su calendarización debe respetar la consolidación de Sprint 1.

## Registro

2026-10-02: evaluación estática y consulta de documentación oficial. No se instalaron paquetes,
no se modificó código de aplicación, no se consultaron calendarios reales y no se ejecutaron
pruebas runtime. Se prepara la siguiente pasada de implementación, separada de la planificación.

Verificación documental: `git diff --check` pasa y los enlaces locales de los tres documentos
resuelven. `.harness/next.py --check` reporta una inconsistencia preexistente: `DG (agente)` tiene
dos tareas activas (`BUG-2026-09-24-01` y `BUG-2026-09-26-01`). No se alteraron sus estados.

2026-10-02 (implementación, UX-CAL-02): backend con lectura por intervalo y paginación; frontend con
calendario, detalle y jobs por proveedor; reporte de aceptación con hallazgos H1–H8. Dos supuestos del plan
se corrigieron con evidencia: FullCalendar 7 no comparte API con la 6 (H1) y el shell del dashboard no es
responsive, lo que limita el uso móvil real (H2).
