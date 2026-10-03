# UX-CAL-01 · Vista de calendario para reuniones

- **Estado:** implementada en UX-CAL-02, pendiente de revisión. Evidencia por criterio en
  [specs/reports/UX-CAL-02-calendario-visual.md](../reports/UX-CAL-02-calendario-visual.md)
- **Responsable propuesto:** DG; colaboración backend FO y revisión QA FD
- **Brecha:** mejora de presentación adicional; no cierra B1–B5
- **Trello:** pendiente de priorización, sin tarjeta creada

## Evidencia del estado actual

| Archivo | Hallazgo |
|---|---|
| `frontend/src/app/dashboard/automation/page.tsx:137` | Calendario ocupa dos tercios del ancho; reglas ocupan el tercio restante |
| `frontend/src/components/dashboard/AutomationCalendarPreview.tsx:6` | Solicita `top={14}` por proveedor |
| `frontend/src/components/dashboard/CalendarMeetingsList.tsx:100` | Consulta Google y Outlook secuencialmente; mezcla y agrupa por día |
| `frontend/src/lib/dossier-api.ts:1665` | Hay id, título, descripción, participantes, inicio, fin, ubicación y día completo |
| `backend/src/dossier/api/app.py:776` | Endpoints con `top` de hasta 50, `dias` relativo a hoy y `incluir_pasadas`; no exponen un intervalo arbitrario |
| `backend/src/dossier/services/google_calendar_api.py:74` | Una página de eventos, `singleEvents=True`; no recorre `nextPageToken` |
| `backend/src/dossier/services/graph_calendar.py:119` | Ya existe lectura por intervalo con `calendarView`; no recorre `@odata.nextLink` |
| `frontend/src/providers/DossierJobsProvider.tsx:489` | Estado del job buscado solo por id de evento, sin proveedor |
| `frontend/src/i18n/types.ts:5` | Hay siete locales: es, en, en-gb, pt, it, fr y de |

Las rutas de listado pasan `skip_internal_meetings=False`; el helper tiene
`work_meetings_only=False`. Por tanto, la vista actual puede incluir eventos de día completo:
no aplicar por accidente los filtros de la automatización a la nueva vista.

## Experiencia propuesta

1. Calendario a ancho completo en la página actual. Reglas de automatización en un bloque
   plegable separado; conexiones y guía existentes accesibles en la cabecera.
2. Vista **Semana** inicial en escritorio; selector **Día / Semana / Mes**, botón **Hoy**,
   anterior/siguiente, período visible y zona horaria. Primer día de semana según locale.
3. Google y Outlook distinguibles con etiqueta y color; filtros Todos / Google / Outlook.
4. Bloques por hora, eventos simultáneos legibles y banda de día completo. En mes, exceso de
   eventos accesible con «+N más»; no se ocultan de forma definitiva.
5. Pulsar un evento abre un panel de detalle (diálogo en móvil): título, fecha/hora, proveedor,
   participantes, ubicación, descripción, guía y generación/resultado del dossier.
6. En móvil, **Día** inicial, selector de fecha compacto y posibilidad de pasar a mes.
7. Vacío, cargando, proveedor desconectado, error de proveedor y respuesta incompleta se muestran
   como estados distintos. El calendario permanece navegable aunque el período esté vacío.

Se conservan reglas de automatización, restricciones del plan y rol, créditos y vista previa
de dossiers. El panel solo muestra un resultado si corresponde al evento seleccionado; terminar
un job de otra reunión no debe cambiar la selección ni abrir su resultado automáticamente.

## Contrato propuesto de lectura por intervalo

Extender los GET existentes `/calendario/eventos-google`, `/calendario/eventos-outlook` y el alias
`/calendario/eventos`, manteniendo el comportamiento actual si no se solicita intervalo.

| Parámetro nuevo | Regla propuesta |
|---|---|
| `desde` | RFC3339 con zona/offset; inicio inclusivo |
| `hasta` | RFC3339 con zona/offset; final exclusivo |

Ambos deben enviarse juntos; `desde < hasta`; máximo 62 días por consulta, suficiente para la
cuadrícula mensual completa. Mezclar intervalo con parámetros explícitos `top`, `dias` o
`incluir_pasadas` devuelve 422: el cliente nuevo solo envía `desde` y `hasta`. Sin intervalo,
conservar defaults y respuesta legada. Rangos históricos permitidos dentro de ese límite.

Seleccionar por **solapamiento**: inicio del evento < hasta y fin del evento > desde. Incluir
reuniones que comienzan antes de la ventana y terminan dentro. Google recibe `timeMin/timeMax`
y expande recurrencias; Microsoft recibe `startDateTime/endDateTime` en `calendarView`.

El servidor recorre la paginación del proveedor. Propuesta de límites iniciales: 250 registros
por página, 10 páginas y 20 segundos de presupuesto total por proveedor. No hacer reintentos
ilimitados; ajustar timeouts al presupuesto restante. Si se alcanza un límite o falla una página
posterior, devolver los datos recuperados con `completo:false` y motivo; la UI pide reducir el
intervalo o reintentar, nunca afirma que todo está cargado. Los límites se validan con fixtures.
No aceptar URLs de paginación del navegador; validar host/ruta esperados antes de seguir nextLink.

Respuesta del modo intervalo conserva `total`, `reuniones`, `mensaje` y añade:

```json
{
  "rango": {"desde": "2026-10-01T00:00:00Z", "hasta": "2026-11-01T00:00:00Z"},
  "completo": true,
  "motivo_incompleto": null
}
```

`total` significa número devuelto, no estimación del total en el proveedor.
`motivo_incompleto`: `limite_paginas`, `tiempo_agotado` o `error_proveedor` cuando corresponde.
Si no hubo ninguna página válida, usar error tipado de proveedor; no responder «sin reuniones».
Mantener 401 para sesión inválida y 404 para integración ausente. Proponer 502 para error remoto
y 504 para timeout en este modo; preservar la semántica legada fuera de él.

Los eventos con hora usan instantes ISO con offset. Para día completo, el modo intervalo
normaliza `inicio` y `fin` como fechas civiles `YYYY-MM-DD`, con fin exclusivo. Google ya ofrece
esas fechas; en Outlook hay que preservar/recuperar la zona original del evento de día completo,
porque el normalizador actual fuerza UTC. No recortar arbitrariamente un timestamp UTC a fecha.
La prueba con fixture de Graph debe resolver este punto antes de publicar la API.

## Adaptación frontend

- Mapear `tema → title`, `inicio → start`, `fin → end`, `todo_el_dia → allDay`.
- Identidad visual compuesta por proveedor e id de ocurrencia. Conservar por separado el id
  original para la generación del dossier. No fusionar reuniones entre proveedores por título.
- Revisar `isEventGenerating/getJobForEvent` para comparar también `calendar_provider` (el
  contrato de jobs ya lo expone), conservando compatibilidad de otros consumidores.
- Cargar ambos proveedores independientemente y en paralelo; una falla no borra el otro.
  Separar conectividad OAuth del resultado de una petición.
- Consultar el rango real visible, incluidos días de meses contiguos. Ignorar respuestas tardías
  al navegar; cancelar peticiones reemplazadas. Caché en memoria por sesión/proveedor/rango/zona,
  vaciada al cerrar sesión o cambiar usuario; «Actualizar» fuerza consulta.
- Usar `effectiveTimezone`, no asumir la zona del navegador. Estado inicial estable durante SSR;
  montar el calendario cliente cuando preferencias estén listas.
- Evento sin id: visible pero generación deshabilitada. Inicio inválido: excluir del grid y
  avisar de registros no representables. Fin ausente o inválido: representación puntual con
  duración desconocida, sin inventar una hora de fin en detalle ni en el payload.

## Criterios de aceptación y pruebas

| CA | Resultado observable | Prueba prevista |
|---|---|---|
| 1 | Hoy/anterior/siguiente y cambio Día/Semana/Mes solicitan la ventana correcta, incluso vacía | Unitaria componente/hook; navegación en navegador |
| 2 | Con >50 reuniones repartidas en páginas se recuperan todas, o aparece aviso explícito de carga incompleta | Unitarias clientes, integración rutas y estrés |
| 3 | Offset, cambio horario en Santiago/Londres, cruce de medianoche, día completo de ambos proveedores y fin exclusivo no desplazan eventos | Fixtures backend y adaptador frontend |
| 4 | Ocurrencias recurrentes expandidas y solapamientos se representan; ocurrencias canceladas no aparecen | Clientes con fixtures, adaptador y QA visual |
| 5 | Google falla y Outlook responde: se ve Outlook más error de Google; desconexión y vacío son distintos | Hook/componente |
| 6 | Respuesta lenta del período anterior no reemplaza el actual; otro usuario no recibe caché previa | Hook/componente |
| 7 | Evento elegido conserva generación, bloqueo de doble clic, errores de créditos/plan y resultado correcto; ids iguales entre proveedores no cruzan jobs | Panel y DossierJobsProvider |
| 8 | Evento sin id o fecha inválida no rompe toda la vista; descripción HTML se presenta saneada como texto | Adaptador y panel |
| 9 | API sin rango conserva contrato; pares incompletos, fechas sin offset, orden inverso y >62 días dan 422 | Unitarias esquema e integración rutas |
| 10 | Cada usuario/organización solo consulta su integración; el navegador nunca recibe tokens OAuth | Seguridad de rutas con dos identidades y proveedores simulados |
| 11 | Teclado abre/cierra detalle, Escape restaura foco, controles tienen nombre; siete locales y ambos temas son usables a 360/768/1440 px | Componentes y QA visual |

TDD obligatorio: registrar fallo de cada caso antes de implementar. Cambio de contrato requiere
unitarias, integración y seguridad; modificar clientes externos requiere además estrés, con
volumen, concurrencia y degradación. Todas las pruebas automáticas simulan la red.

## Alcance y decisiones pendientes

No hay migración prevista, edición de citas ni incorporación de calendarios secundarios.
El resumen de conexiones en `/dashboard` permanece fuera del cambio visual principal.
Decidir prioridad frente a las cinco brechas y asignar implementación después de consolidar
Sprint 1, salvo instrucción expresa del usuario. Este borrador no cambia fechas del plan original.

Fuentes del contrato: [Google Events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)
y [Microsoft calendarView](https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0).
