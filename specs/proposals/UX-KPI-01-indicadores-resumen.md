# UX-KPI-01 · Indicadores reales en Resumen

- **Tarea:** UX-KPI-01, ampliación solicitada por el usuario el 2026-10-02.
- **Responsable propuesto:** DG, con soporte backend FO y revisión FD.
- **Estado:** implementada y verificada por su autor; pendiente de revisión del segundo integrante.
  Evidencia por criterio: [reporte](../reports/UX-KPI-01-indicadores-resumen.md). Decisión: [ADR 0008](../../docs/architecture/decisions/0008-indicador-creditos-para-preparar.md).
- **Plan:** [secuencia de implementación](../../docs/exec-plans/active/UX-KPI-01-indicadores-resumen.md).

> **Enmienda 2026-10-04 (decisión del usuario).** La tercera tarjeta deja de ser «Reuniones
> preparadas a tiempo» (últimos 30 días, solo generación manual) y pasa a ser **«Créditos para
> preparar»**: los créditos estimados para generar lo que falta en las mismas reuniones de los
> próximos 7 días. Motivo: las otras tres tarjetas miran lo que viene y el saldo actual; la de
> puntualidad miraba hacia atrás, con otro periodo y otro ámbito. Con la enmienda desaparece la
> evidencia histórica (tabla de hechos, migración y relleno), que solo existía para ese indicador.

## Problema y evidencia

La pantalla `frontend/src/app/dashboard/page.tsx` solicitaba `fetchDossiersFromApi(80)` y calculaba
los contadores con `countListEntries`. El endpoint de `api/dossier_routes.py` limita filas antes
de agrupar carpetas; esas entradas no representan ni todos los dossiers ni todas las reuniones.
La ausencia de dossier tampoco permite descubrir una reunión pendiente.

Los listados heredados de `services/google_calendar_api.py` y `services/graph_calendar.py` limitan
eventos con `top` y no completan la paginación. La automatización consulta solo tres días hacia
adelante: `CalendarEvent` por sí solo no garantiza siete días completos.

## Alcance

Reemplazar las cuatro tarjetas de `/dashboard` con una consulta de resumen autenticada que lee los
calendarios completos por intervalo. Los cálculos no dependen de las listas paginadas de la interfaz.

La interfaz conserva su navegación, calendario, actividad y acciones. Las tarjetas son
informativas: no abren rutas, modales, tablas de detalle ni nuevos módulos. No se implementa la
vista de calendario de UX-CAL-01; se reutilizan sus helpers de lectura por rango (UX-CAL-02).

## Definiciones

Se captura una única hora `as_of` del servidor por cálculo. Periodo: `[as_of, as_of + 7 días)`,
móvil. Comparaciones entre instantes UTC; presentación en la zona del usuario.

El ámbito de las reuniones es el usuario autenticado y su organización activa, incluso para
administradores. El saldo de créditos pertenece a la organización.

Una reunión elegible es una ocurrencia con hora de inicio válida, no cancelada ni rechazada por el
usuario, que cumple las reglas existentes de reunión de trabajo y tiene participantes externos. Los
filtros que habilitan la automatización no excluyen una reunión que se puede preparar a mano.

La identidad incluye proveedor, calendario y ocurrencia. Dos proveedores con el mismo id de evento
no se mezclan. Una ocurrencia duplicada entre calendarios se unifica solo con iCalUID **y** el mismo
instante de inicio, nunca por título o cercanía horaria.

Una reunión está preparada cuando dispone del conjunto completo de dossiers que su solicitud
produce con el parser de generación y el plan aplicable (empresa si el plan la incluye, más uno por
contacto). Un resultado parcial no basta. Un conjunto esperado vacío nunca es «preparada». Cuentan
los dossiers completos, vigentes y propios del usuario, manuales o automáticos, asociados por
proveedor e id de evento.

| Tarjeta | Regla |
|---|---|
| Reuniones por preparar | Elegibles menos preparadas. Cada reunión cuenta una vez. |
| Cobertura de próximas reuniones | `100 × preparadas / elegibles`. |
| Créditos para preparar | Suma, sobre las reuniones elegibles no preparadas, del costo de cada dossier esperado que falta: empresa = créditos de la profundidad por defecto del plan; persona = créditos de identidad. Estimación máxima (un dossier recuperado de caché puede costar menos). |
| Créditos disponibles | Saldo real y límite mensual de la organización activa. |

«Créditos para preparar» informa además cuántas reuniones necesitan generar algo y si el estimado
supera el saldo. En plan Enterprise (sin bloqueo por saldo) o con el cobro desactivado
(`DOSSIER_CHARGE_CREDITS=0`) el estimado es 0 y se declara el motivo (`unlimited` / `disabled`).

## Contrato

`GET /dashboard/summary`, autenticado, sin `user_id` u `organization_id` elegibles por el cliente.
No devuelve datos personales, cuerpos de dossiers ni listas para vistas de detalle.

```typescript
type MetricState = "ok" | "empty" | "partial" | "unavailable" | "not_connected";
type MetricContext = {
  state: MetricState;
  reason: string | null; // código estable traducido por el frontend
  measured_from: string | null;
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
  preparation_cost: MetricContext & {
    from: string; to: string;
    estimated_credits: number | null;
    meetings_to_generate: number | null;
    billing: "charged" | "unlimited" | "disabled";
    exceeds_balance: boolean | null;
  };
  credits: MetricContext & {
    balance: number | null;
    monthly_limit: number | null;
  };
};
```

Los porcentajes conservan precisión en backend y se presentan con hasta un decimal localizado.
Denominador cero: `percent=null`, estado `empty`, «Sin reuniones en este período». Sin calendarios
conectados no se afirma que existen cero reuniones. Una lectura de calendario incompleta o un
proveedor fallido deja los derivados en `null` con causa explícita (`unavailable`); no se calcula
con una selección arbitraria de páginas o proveedores. Un fallo de calendario no oculta el saldo.

Refrescar al cargar Resumen, al volver a la pestaña, al cambiar de sesión u organización y al
terminar una generación del usuario. Caché breve por usuario y organización, invalidada al generar o
borrar dossiers. Una sola petición en vuelo; sin sondeo nuevo. Consultar no genera dossiers, no
programa trabajos y no consume créditos.

## Criterios de aceptación

- [x] **CA1** — 5 reuniones futuras elegibles, 3 preparadas: 2 pendientes y 60 %.
- [x] **CA2** — Las 2 pendientes, una sin nada (empresa + 1 contacto) y otra con la empresa hecha y
      1 contacto faltante, en plan Pro (estándar = 3, persona = 1): estimado 5 créditos para 2 reuniones.
- [x] **CA3** — Solo se cobra lo que falta: un dossier ya completo no suma; uno fallido sí; una
      reunión con conjunto esperado vacío no suma ni cuenta como «a generar».
- [x] **CA4** — Plan Free sin módulo de empresa: el corporativo no se exige ni se cobra. Enterprise o
      cobro desactivado: estimado 0 con `billing` explícito.
- [x] **CA5** — Más de 80 dossiers y múltiples páginas de calendario producen totales completos; un
      fallo en una página no entrega cifras aparentemente definitivas.
- [x] **CA6** — Ids iguales de Google/Microsoft o de otros usuarios no se mezclan.
- [x] **CA7** — Dos dossiers esperados y solo uno completo mantienen la reunión pendiente.
- [x] **CA8** — Borrar un dossier antes de la reunión la devuelve a pendiente y vuelve a sumar su costo.
- [x] **CA9** — `exceeds_balance` es verdadero cuando el estimado supera el saldo con cobro activo.
- [x] **CA10** — Límites del periodo, DST, recurrencias y duplicados entre calendarios se evalúan por
      ocurrencia con instantes UTC.
- [x] **CA11** — Sin reuniones, sin integración y error de consulta son estados distintos; créditos
      siguen visibles si su fuente responde. No se muestran números ficticios ni ceros por error.
- [x] **CA12** — Usuario y organización salen de la sesión: ni admin ni viewer acceden a datos de
      otro miembro mediante parámetros o caché compartida.
- [x] **CA13** — Completar una generación actualiza las tarjetas; una respuesta antigua no
      sobrescribe datos de otra sesión u organización. Leer el resumen no crea jobs.
- [x] **CA14** — Las cuatro tarjetas funcionan en escritorio y móvil, temas e idiomas configurados;
      no introducen acciones ni vistas de detalle. Actividad y calendario siguen operativos.

## Pruebas y entrega

El endpoint nuevo exige pruebas unitarias, integración, estrés y seguridad
(`docs/dev/testing-policy.md`), más pruebas de frontend. Calendarios simulados y cuentas ficticias.
Estrés: varias páginas, consultas simultáneas y proveedor lento o fallido. QA antes de commit y QA
completo antes de push. PR, segunda revisión y evidencia Trello forman parte de la entrega.
