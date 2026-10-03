# UX-KPI-01 · Reemplazar las tarjetas de Resumen con métricas reales

- **Fecha:** 2026-10-02.
- **Estado:** plan preparado; implementación pendiente.
- **Especificación:** [UX-KPI-01](../../../specs/proposals/UX-KPI-01-indicadores-resumen.md).
- **Responsable propuesto:** DG, soporte backend FO y revisión FD.
- **Rama propuesta para implementación:** `codex/UX-KPI-01-indicadores-resumen`.

## Resultado esperado

Las cuatro tarjetas de Resumen muestran reuniones por preparar, cobertura de próximas reuniones,
reuniones preparadas a tiempo por el usuario y créditos disponibles. El tercer indicador incluye
cuántos dossiers generó manualmente a tiempo durante los últimos 30 días. La definición distingue
reuniones de dossiers, generaciones manuales de automáticas y datos personales de saldo de organización.

El usuario amplió el alcance visual para que los indicadores funcionen con datos reales. Se incluyen
los cambios de backend, datos e integración necesarios para estas tarjetas, manteniendo toda la
interacción dentro de `/dashboard`: tarjetas informativas, sin nuevas pantallas ni módulos de detalle.

## Secuencia de implementación

### 1. Preparar la tarea y el contrato

- Releer el estado del repositorio y reclamar solo esta tarea conforme al handoff antes de código.
- Usar la spec para las fórmulas, períodos, autoría manual, elegibilidad, completitud y casos vacíos.
- Verificar las dependencias de Sprint 1 y el estado efectivo de Alembic, QA y CI; la documentación
  inicial tiene advertencias históricas que no sustituyen el código y progress actuales.
- Coordinar el helper por rango/páginas con UX-CAL-01 si ya se está implementando, sin incorporar su UI.

### 2. Completar los datos de calendario

- TDD del intervalo: próximos 7 días e historial de 30 días, paginación en Google y Microsoft,
  cancelaciones, recurrencias, zona horaria y respuestas parciales.
- Añadir lectura completa por rango a los clientes actuales manteniendo el contrato legado de listados.
- Resolver identidad por proveedor, calendario, usuario, organización y ocurrencia, incluyendo
  deduplicación verificable entre calendarios conectados.
- Hacer que el resumen funcione también para generación manual con automatización deshabilitada.
  Su consulta no debe programar trabajos ni activar cobros.

### 3. Enlazar generación, autoría e historial

- TDD de resultados parciales, actor manual, finalización antes del inicio, reintentos e idempotencia.
- Enlazar el flujo manual de calendario con el evento interno sin depender del título ni de carpetas.
- Registrar el conjunto esperado y sus resultados reales, respetando qué módulos permite el plan.
- Diseñar y aplicar en prueba una migración de evidencia estadística mínima y sus índices. Registrar
  previamente el cambio de DB en progress; leer `db/Migracion.md`, `schema_patches.py` y Alembic.
- Conservar la evidencia histórica necesaria sin cuerpos ni información de investigación. Probar
  eliminación antes/después de reunión, retención a 7/14 días y purga del propio historial estadístico.
- Recuperar datos históricos verificables de jobs/metadatos existentes. Registrar el inicio del
  historial fiable cuando falte información; no fabricar los 30 días anteriores al despliegue.

### 4. Construir la respuesta agregada

- TDD de `GET /dashboard/summary`: contrato, autenticación, cálculo, errores parciales y aislamiento.
- Usar agregación del conjunto completo, sin el límite de 80 dossiers ni el conteo de carpetas.
- Resolver usuario y organización desde la sesión; el alcance personal también se aplica al admin.
- Reutilizar el saldo de créditos existente. Una falla de calendario no oculta el saldo.
- Usar caché breve separada por usuario/organización; invalidarla al cambiar resultados o reuniones.
  Acotar llamadas simultáneas y tiempos de espera a proveedores, señalando cualquier incompletitud.

### 5. Cambiar las cuatro tarjetas de Resumen

- TDD de valores, porcentajes, conteo de dossiers, carga, ausencia de calendario y datos parciales.
- Añadir el cliente tipado para el resumen y reemplazar solo el cálculo/representación de las tarjetas.
- Conservar la consulta de dossiers que necesita la actividad reciente, sin usarla para los KPI.
- Reutilizar `StatCard`; extensiones opcionales para texto auxiliar sin cambiar sus otros consumidores.
- Mantener cuatro/dos/una columnas según ancho, textos completos, temas e idiomas configurados.
- Refrescar al entrar, recuperar foco y finalizar una generación mediante señales del proveedor actual.
  Evitar actualizaciones de una respuesta antigua tras cambiar de sesión u organización.

### 6. Verificar y entregar

- Fixtures comunes de API y UI: 5 próximas, 3 preparadas, 2 pendientes; historial de 8 reuniones,
  6 manuales a tiempo, 11 dossiers manuales a tiempo dentro de la ventana.
- Pruebas unitarias, integración, estrés y seguridad del nuevo endpoint, además de frontend/migración.
- Verificar volumen superior a 80, paginación, fallo de proveedor, manual frente a automático,
  varios dossiers por reunión, documentos borrados, ids repetidos y cambios de fecha/DST.
- Revisión visual con datos ficticios en móvil/escritorio y locales; confirmar cuatro tarjetas
  informativas y conservación del funcionamiento del calendario/actividad existentes.
- `python scripts/qa.py` antes de commit y `python scripts/qa.py --full` antes de push.
- Actualizar manual/configuración pertinente, reporte de aceptación, harness, PR y evidencia Trello.
  Solo el segundo integrante que revisa puede marcar la implementación como `done`.

## Archivos previstos

| Área | Archivos o ubicaciones |
|---|---|
| Interfaz | `frontend/src/app/dashboard/page.tsx`, `frontend/src/components/dashboard/StatCard.tsx` y pruebas asociadas |
| Datos cliente | `frontend/src/lib/dossier-api.ts`; adaptador/hook local de Resumen si hace falta |
| Traducciones | Claves propias de Resumen en los mensajes de todos los locales configurados |
| API | Router de resumen, esquema de respuesta y registro en `backend/src/dossier/api/app.py` |
| Calendario | `services/google_calendar_api.py`, `services/graph_calendar.py`, normalización e identidad compartidas |
| Generación | `services/dossier_generation_job_service.py`, `services/calendar_event_dossiers.py`, automatización solo para registrar evidencia equivalente |
| Datos históricos | `db/models.py`, migración Alembic, `db/Migracion.md`, registro mínimo y su retención |
| Borrado | Hooks acotados en borrado/retención para disponibilidad futura y evidencia histórica |
| Pruebas | `backend/tests/` y categorías integration/security/stress; pruebas de frontend junto al código |

Son ubicaciones previstas, no una instrucción de modificar todos esos archivos indiscriminadamente.
No se requiere instalar una biblioteca de gráficos ni crear un panel analítico adicional.

## Condiciones para considerar resueltas las limitaciones

- Las cifras no dependen del número de elementos cargados en una lista.
- La misma reunión no se cuenta por cada dossier ni por cada reintento.
- La generación manual se acredita a quien la inició y al momento real de finalización.
- Los borrados del documento no borran hechos históricos ya demostrados, y no se acredita
  disponibilidad a una reunión si el documento fue eliminado antes de su inicio.
- Todo porcentaje tiene un denominador completo para el intervalo declarado; una consulta
  parcial jamás aparenta exactitud. Un cero se distingue de una falla o falta de integración.
- Los datos anteriores que ya no existen se señalan como historial parcial, con período medido
  visible. Esa limitación histórica no impide registrar correctamente las nuevas generaciones.
- El resultado visible consiste únicamente en las cuatro tarjetas dentro de Resumen.

## Registro de esta pasada

2026-10-02: lectura de código y documentación; ampliación del plan para incluir backend, vinculación
y persistencia de evidencia. No se modificó código de aplicación ni esquema, no se consultaron
calendarios reales y no se ejecutaron pruebas runtime. El plan y la spec son borradores para la
pasada de implementación, conforme al flujo SDD del repositorio.
