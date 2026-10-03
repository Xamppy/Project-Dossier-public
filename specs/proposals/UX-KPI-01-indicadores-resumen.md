# UX-KPI-01 · Indicadores reales en Resumen

- **Tarea:** UX-KPI-01, ampliación solicitada por el usuario el 2026-10-02.
- **Responsable propuesto:** DG, con soporte backend FO y revisión FD.
- **Estado:** implementada y verificada por su autor (2026-10-03); pendiente de revisión del segundo integrante. Evidencia por criterio: [reporte](../reports/UX-KPI-01-indicadores-resumen.md). Decisiones de datos: [ADR 0008](../../docs/architecture/decisions/0008-evidencia-de-preparacion-de-reuniones.md).
- **Plan:** [secuencia de implementación](../../docs/exec-plans/active/UX-KPI-01-indicadores-resumen.md).

## Problema y evidencia

La pantalla `frontend/src/app/dashboard/page.tsx` solicita `fetchDossiersFromApi(80)` y calcula
los contadores con `countListEntries`. El endpoint de `api/dossier_routes.py` limita filas antes
de agrupar carpetas; estas entradas no representan ni todos los dossiers ni todas las reuniones.
La ausencia de dossier tampoco permite descubrir una reunión pendiente.

Los clientes `services/google_calendar_api.py` y `services/graph_calendar.py` limitan eventos
con `top` y no completan la paginación en los listados actuales. La automatización consulta
solo tres días hacia adelante: `CalendarEvent` por sí solo tampoco garantiza siete días completos.

`_process_calendar_manual_job` registra usuario, proveedor, evento externo y `trigger_source="manual"`,
pero llama a `persist_calendar_dossiers` sin `calendar_event_id`. El JSON `calendar` conserva
`provider` y `external_event_id`: se puede recuperar parte de las asociaciones de forma verificable.
La generación automática usa `trigger_source="calendar"` y sí pasa el evento interno.

La lista de dossiers no expone quién los solicitó ni `generation_completed_at`. `updated_at`
no representa la finalización de una generación. La retención puede borrar dossiers a los
7 o 14 días, afectando cualquier estadística de 30 días calculada únicamente sobre filas vigentes.

## Alcance

Incluye reemplazar las cuatro tarjetas de `/dashboard`, su consulta de resumen autenticada,
lectura completa de eventos por intervalo, asociación de generación con reunión, evidencia
mínima para el historial y pruebas. La ampliación de backend resuelve los datos necesarios
para esas tarjetas. Los cálculos no dependen de las listas paginadas de la interfaz.

La interfaz conserva su navegación, calendario, actividad y acciones actuales. Las tarjetas
son informativas: no abren rutas, modales, tablas de detalle ni nuevos módulos. No se implementa
la vista de calendario propuesta en UX-CAL-01. Los helpers de rango y paginación se comparten
si ya existen al comenzar la implementación, evitando dos soluciones incompatibles.

## Definiciones

Se captura una única hora `as_of` del servidor por cálculo. Futuro: `[as_of, as_of + 7 días)`.
Historial: `[as_of - 30 días, as_of)`. Son períodos móviles; la etiqueta será «Últimos 30 días»,
no «Este mes». Comparaciones entre instantes UTC y presentación en la zona del usuario.

El ámbito de las reuniones es el usuario autenticado y su organización activa, incluso para
administradores. El saldo de créditos pertenece a la organización. Nunca se atribuye al usuario
la actividad de otro miembro por el solo hecho de tener permisos para verla.

Una reunión elegible es una ocurrencia con hora de inicio válida, no cancelada ni rechazada
por el usuario, que cumple las reglas existentes de reunión de trabajo y tiene participantes
externos. Los filtros específicos que habilitan la automatización no excluyen por sí solos una
reunión que se puede preparar manualmente. Se conservan las reglas actuales de generación y planes.

La identidad incluye organización, usuario, proveedor, calendario y ocurrencia. Dos proveedores
con el mismo id de evento no se mezclan. Una ocurrencia duplicada entre calendarios se unifica
solo con identidad interoperable verificable y su ocurrencia, nunca por título o cercanía horaria.

Una reunión está preparada cuando dispone del conjunto completo de dossiers requeridos por
la solicitud y el plan aplicable. Un resultado parcial no basta. Se reutiliza el parser actual
para identificar el conjunto esperado; nunca se deduce completitud solo de las filas guardadas.
Un conjunto esperado vacío o desconocido no produce una reunión preparada.

| Tarjeta | Regla |
|---|---|
| Reuniones por preparar | Reuniones elegibles futuras menos reuniones preparadas futuras. Cada reunión cuenta una vez. |
| Cobertura de próximas reuniones | `100 × futuras preparadas / futuras elegibles`. Se admiten dossiers manuales o automáticos accesibles al usuario y asociados a su reunión. |
| Reuniones preparadas a tiempo | `100 × reuniones pasadas preparadas manualmente por el usuario antes de su inicio / reuniones pasadas elegibles`. Debe haberse completado todo el conjunto requerido antes del inicio. |
| Créditos disponibles | Saldo real y límite del plan de la organización activa, reutilizando la lógica existente. |

La tercera tarjeta añade el conteo de dossiers que el usuario generó manualmente durante los
últimos 30 días y que finalizaron antes de su reunión asociada. Cada resultado exitoso persistido
cuenta una vez, independientemente de cuántas veces se consulte. Una carpeta no cuenta como dossier.
Una regeneración que crea un resultado nuevo sí cuenta; un reintento técnico de la misma persistencia
no. Un resultado recuperado de caché cuenta si la solicitud manual genera un dossier nuevo disponible.
No se infiere generación a partir del crédito descontado, porque la caché puede no consumir créditos.

El período del porcentaje se aplica al inicio de la reunión; el período del conteo de dossiers,
a la finalización de la generación. Un dossier preparado antes del período puede acreditar una
reunión ocurrida dentro del período, pero no es una generación realizada durante esos 30 días.
Se explica esta diferencia en el texto accesible de la tarjeta. Un dossier sin reunión asociada
no permite afirmar «a tiempo» y queda fuera de este indicador.

## Datos y conservación de evidencia

1. Leer completamente los intervalos de calendario requeridos, recorriendo páginas de Google y
   Microsoft y aplicando límites de tiempo. Una consulta truncada o un proveedor fallido nunca
   se declara completa. La lectura no genera dossiers, no programa automatizaciones ni cobra créditos.
2. Normalizar y enlazar los resultados manuales con su evento. Usar la identidad compuesta,
   `requested_by_user_id`, `trigger_source` y finalización real. Recuperar asociaciones antiguas
   únicamente cuando JSON/job/evento permiten una relación inequívoca.
3. Registrar evidencia estadística mínima de generación y preparación: claves de ámbito/evento,
   identidad idempotente del resultado, origen manual/automático, timestamps, conjunto esperado
   y éxito/completitud. No conservar cuerpos de dossiers, nombres, correos, descripciones ni
   contenido de investigación para contar. Persistir junto al resultado exitoso, sin duplicados.
4. Mantener disponibles esos hechos durante la ventana necesaria del indicador, sin depender
   de la existencia posterior del documento. Antes de la reunión, borrar un dossier hace que
   deje de estar disponible para la cobertura futura. Después de la reunión, borrar el documento
   no reescribe si estuvo disponible y preparado a tiempo. Una eliminación anterior al inicio
   debe quedar reflejada para no acreditar preparación histórica inexistente.
5. Tratar cancelaciones, reprogramaciones y cambios del conjunto requerido explícitamente. Para
   el historial se guarda el inicio y la completitud efectivos de la ocurrencia, sin reinterpretar
   hechos pasados a partir del plan actual. Purga de metadatos según ventana y eliminación del
   usuario/organización; sin conservar información adicional del dossier por esta funcionalidad.
6. Reconstruir el pasado con evidencia existente. Datos ya purgados sin evidencia no son recuperables:
   registrar desde qué fecha el historial es fiable. En ese caso se muestra el intervalo realmente
   medido y «Historial parcial», sin presentar un porcentaje incompleto como si cubriera 30 días.

La implementación debe definir una migración Alembic para la evidencia adicional y documentarla
en `db/Migracion.md`, coordinada con la política de retención existente. Leer también
`schema_patches.py`; la migración base importa constantes vivas, por lo que no se cambia su
significado retroactivamente. No se aplica ninguna migración durante esta planificación.

## Contrato propuesto

`GET /dashboard/summary`, autenticado, sin `user_id` u `organization_id` elegibles por el cliente.
No devuelve datos personales, cuerpos de dossiers ni listas para vistas de detalle.

```typescript
type MetricState = "ok" | "empty" | "partial" | "unavailable" | "not_connected";
type MetricContext = {
  state: MetricState;
  reason: string | null; // código estable traducido por el frontend
  measured_from: string | null; // ISO 8601; evidencia fiable desde esta fecha
  measured_to: string | null;
};
type DashboardSummary = {
  as_of: string;
  timezone: string;
  upcoming: MetricContext & {
    from: string; to: string;
    eligible_meetings: number | null;
    prepared_meetings: number | null;
    pending_meetings: number | null;
    coverage_percent: number | null;
  };
  history: MetricContext & {
    from: string; to: string;
    eligible_meetings: number | null;
    manually_prepared_on_time_meetings: number | null;
    on_time_percent: number | null;
    manual_on_time_dossiers: number | null;
  };
  credits: MetricContext & {
    balance: number | null;
    monthly_limit: number | null;
  };
};
```

Los porcentajes conservan precisión en backend y se presentan con hasta un decimal localizado.
Denominador cero significa `percent=null`, estado `empty` y «Sin reuniones en este período»;
un porcentaje real de cero requiere un denominador positivo. Sin calendarios conectados no se
afirma que existen cero reuniones. Un fallo parcial de calendario no invalida el saldo disponible.
`partial` permite un intervalo fiable menor, declarado; no permite calcular un porcentaje con
una selección arbitraria de páginas o proveedores. Si no hay intervalo completo verificable,
los campos derivados son `null` con causa explícita.

Refrescar al cargar Resumen, al regresar a la pestaña y después de completar una generación del
usuario, reutilizando el proveedor de jobs existente. Invalidar caché con cambios relevantes
y usar vencimiento breve para cambios de calendario externos. Deduplicar peticiones concurrentes;
no sumar un nuevo canal SSE ni otro sondeo continuo a este alcance.

## Criterios de aceptación

- [x] **CA1** — 5 reuniones futuras elegibles, 3 preparadas: tarjetas muestran 2 pendientes y 60 %.
- [x] **CA2** — 8 reuniones pasadas elegibles, 6 preparadas manualmente a tiempo y 11 resultados
      manuales dentro del período: 75 %, 6/8 y 11 dossiers, usando fixtures con evidencia completa.
- [x] **CA3** — Un dossier automático, compartido por otro usuario, fallido, cancelado, aún en
      proceso o completado en/después del inicio no acredita preparación manual a tiempo.
- [x] **CA4** — Dos dossiers en una carpeta cuentan como dos dossiers y una reunión. Solicitudes
      repetidas y reintentos de persistencia no duplican resultados ya registrados.
- [x] **CA5** — Más de 80 dossiers y múltiples páginas de calendario producen los totales completos;
      un fallo en una página no entrega un porcentaje aparentemente definitivo.
- [x] **CA6** — Un resultado manual legado con metadatos inequívocos se asocia al evento correcto;
      ids iguales de Google/Microsoft o de otros usuarios no se mezclan.
- [x] **CA7** — Dos dossiers esperados y solo uno completo mantienen la reunión pendiente;
      un módulo no incluido en el plan no se exige para darla por preparada.
- [x] **CA8** — Retención a 7 días no reduce hechos históricos demostrados de hace 20 días. Borrar
      antes de la reunión elimina disponibilidad futura y evita acreditar preparación inexistente.
- [x] **CA9** — Historia ya purgada sin evidencia indica el período verificable. No se fabrican
      generaciones ni timestamps, ni se sustituye `generation_completed_at` por `updated_at`.
- [x] **CA10** — Límites de períodos, DST, reprogramaciones, recurrencias y cancelaciones se evalúan
      por ocurrencia, con instantes coherentes y sin duplicación entre calendarios verificablemente iguales.
- [x] **CA11** — Sin reuniones, sin integración y error de consulta son estados distintos; créditos
      siguen visibles si su fuente responde. No se muestran números ficticios ni ceros por error.
- [x] **CA12** — Usuario/organización se resuelven de la sesión: ni admin ni viewer acceden a los
      calendarios o actividad personal de otro miembro mediante parámetros o caché compartida.
- [x] **CA13** — Completar una generación actualiza las tarjetas al volver a Resumen; una respuesta
      antigua no sobrescribe datos de una sesión/organización nueva. Leer el resumen no crea jobs.
- [x] **CA14** — Las cuatro tarjetas funcionan en escritorio y móvil, temas e idiomas configurados;
      no introducen acciones, navegación o vistas de detalle. Actividad y calendario siguen operativos.

## Pruebas y entrega

El endpoint nuevo exige pruebas unitarias, integración, estrés y seguridad según
`docs/dev/testing-policy.md`. Agregar pruebas de frontend, migración y persistencia idempotente;
verificar rojo antes de implementar cada criterio. Calendarios simulados y cuentas ficticias.

Casos de estrés: varias páginas, consultas simultáneas y proveedor lento/fallido, con resultados
acotados y señales de incompletitud. Contrastar resultados de API y tarjetas con el mismo fixture.
Ejecutar QA antes de commit y QA completo antes de push. PR, segunda revisión y evidencia Trello
forman parte de la entrega; la planificación no acredita implementación ni validación runtime.
