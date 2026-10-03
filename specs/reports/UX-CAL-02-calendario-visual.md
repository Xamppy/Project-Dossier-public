# Reporte de aceptación · UX-CAL-02 — Calendario visual de reuniones

- **Fecha:** 2026-10-02
- **Implementa:** DG (agente). **Revisión pendiente:** segundo integrante (FD sugerido); no se marca `done`.
- **Rama:** `codex/UX-CAL-01-calendario-visual` · **Spec:** [UX-CAL-01](../proposals/UX-CAL-01-calendario-visual.md) ·
  **ADR:** [0007](../../docs/architecture/decisions/0007-calendario-visual.md)
- **Alcance:** implementa lo planificado en UX-CAL-01 (que solo evalúa y planifica). Se inició antes del
  cierre de Sprint 1 por instrucción expresa del usuario. No cierra B1–B5.

## Resumen

| | Resultado |
|---|---|
| Backend | Lectura por intervalo con paginación en Google y Outlook; contrato legado intacto |
| Frontend | Calendario Día/Semana/Mes (FullCalendar 7.1.0), filtros, detalle accesible, jobs por proveedor |
| Pruebas nuevas | Backend **99** (unit 49, integración 31, seguridad 12, estrés 7) · Frontend **128** |
| Suites completas | Backend 268 pasan · Frontend 148 pasan |
| Fallos preexistentes (no introducidos) | `test_llm_canonical_line::test_gemini_dir_no_existe` (backend) y `TimezoneSelect … UTC (GMT+0)` (frontend). Ya fallaban antes del primer cambio de esta tarea |
| Build | `next build` correcto; `python scripts/qa.py --full` solo falla por los dos preexistentes |

## Evidencia por criterio

Las pruebas simulan toda la red (Google, Graph y la API de Dossier). «Visual» = comprobado a mano en
el navegador integrado contra una API ficticia local con datos inventados (ver *Alcance de la verificación*).

| CA | Resultado | Evidencia |
|---|---|---|
| **1** Navegación y ventana | ✅ | `MeetingsCalendar.test.tsx` (Hoy/Anterior/Siguiente, Día/Semana/Mes, ventana en la zona del usuario, mes con días contiguos, cambio de zona re-emite la ventana, ventana vacía sigue navegable) · `useCalendarEvents.test.tsx` · `calendar-events.test.ts` (`windowFromCivilDates`, offsets con cambio horario) · `MeetingsCalendarSection.test.tsx` · visual |
| **2** >50 reuniones / carga incompleta | ✅ | `test_calendar_event_range.py` (paginación Google/Graph, límite de 10 páginas, presupuesto de 20 s) · `test_calendar_event_routes.py` (120 eventos en 6 páginas; `limite_paginas`) · `test_calendar_event_pagination.py` (2 500 eventos; truncado con aviso; caída a mitad) · UI: aviso por proveedor sin afirmar que todo está cargado (visual + `MeetingsCalendarSection.test.tsx`) |
| **3** Fechas, offsets, DST, día completo | ✅ (Google/fixtures) ⚠️ (Outlook real) | Fixtures: Santiago y Londres con cambio de horario, cruce de medianoche, día completo con fin exclusivo, Outlook con `originalStartTimeZone` en nombres de Windows e IANA. **No verificado contra Microsoft Graph real** (ver H3) |
| **4** Recurrencias, solapes, canceladas | ✅ | `test_calendar_event_range.py` (`singleEvents`, `status=cancelled`, `isCancelled`) · solapes visuales en miércoles de la API ficticia (5 reuniones simultáneas + «+N más» en mes) |
| **5** Error parcial, desconexión, vacío | ✅ | `useCalendarEvents.test.tsx`, `MeetingsCalendarSection.test.tsx`; visual de los escenarios `google_error`, `disconnected`, `incomplete`, `baddata`, `empty` |
| **6** Respuestas tardías y caché entre usuarios | ✅ | `useCalendarEvents.test.tsx` (respuesta lenta descartada, `AbortSignal`, otro usuario no reutiliza caché) · `calendar-events-cache.test.ts` (sesión, TTL, tamaño, `clearAuthSession`) |
| **7** Generación, bloqueo, errores, jobs por proveedor | ✅ | `CalendarEventDetails.test.tsx` (abrir no genera; doble clic una vez; créditos/plan; resultado solo de este evento) · `calendar-jobs.test.ts` (mismo id en dos proveedores no cruza) · `MeetingsCalendarSection.test.tsx` (el job de otra reunión no cambia la selección). **El POST real de generación no se ejercitó** (la API ficticia no lo implementa) |
| **8** Evento sin id / fecha inválida / HTML | ✅ | `calendar-events.test.ts` (descartados contados, sin id visible y sin generación, sin fin válido no se inventa hora, HTML a texto, scripts/handlers eliminados) · `CalendarEventDetails.test.tsx` (texto, nunca marcado) · visual (`baddata`) |
| **9** Contrato y 422 | ✅ | `test_calendar_event_range.py` (`parse_rango`) · `test_calendar_event_routes.py` (modo legado idéntico, pares incompletos, sin offset, inverso, >62 días, mezcla con `top`/`dias`/`incluir_pasadas` → 422 sin llamar al proveedor) |
| **10** Aislamiento y tokens | ✅ | `test_calendar_event_access.py`: dos identidades usan su propio token y ven solo sus reuniones; ninguna respuesta (éxito o error) contiene tokens ni enlaces de paginación; 401 sin llamar al proveedor; `nextLink` solo hacia `https://graph.microsoft.com` y rutas `calendarView`. Verificado por mutación (ver H5) |
| **11** Teclado, accesibilidad, locales, temas, tamaños | ⚠️ parcial | Teclado: Enter abre, Escape cierra y devuelve el foco (jsdom **y** navegador real), trampa de Tab, nombres accesibles, `aria-pressed`, título `aria-live` · Siete locales: etiquetas verificadas por prueba (`calendar-ui-labels.test.ts`); visual solo es y de · Temas: oscuro y claro, visual · Tamaños: 1440 y 375 px visuales; **768 px no se revisó**; a 375 px el calendario funciona pero el shell del dashboard no (ver H2) |

## Alcance de la verificación

**Se hizo:** suites de pruebas; `next build`; revisión visual en el navegador integrado contra una API
ficticia local (escritorio 1440 px y móvil 375 px; temas oscuro y claro; idiomas es y de; zonas
Santiago y Londres; seis escenarios de estado); medición del chunk del calendario.

**No se hizo:**
- Ninguna consulta a Google, Microsoft ni a la base de datos reales; ni cuentas reales.
- Generación real de un dossier desde el panel (POST) ni cobro de créditos reales.
- Ancho 768 px, idiomas en/en-gb/pt/it/fr visualmente, lector de pantalla, anillo de foco visible con Tab real.
- `ruff` y `mypy` (tarea S1.2 no cerrada; el `pip install` de ambos no terminó en esta sesión).
- Escenarios k6 de carga HTTP real (no bloquean el PR; la política los deja a mano).
- Medición de rendimiento más allá del tamaño del chunk.

**Medición de bundle:** el calendario vive en un chunk que solo carga `/dashboard/automation`
(≈334 KB sin comprimir, ≈97 KB gzip, medido en `next build`). Ninguna otra ruta lo incluye.

## Hallazgos

**H1 · FullCalendar 7 no es una actualización de la 6.** `npm` sigue sirviendo `@fullcalendar/daygrid`
y `timegrid` 6.1.21 como `latest`; en la 7 las vistas se importan de subrutas de `@fullcalendar/react`
(`/daygrid`, `/timegrid`) y necesita `temporal-polyfill`. Se fijó `@fullcalendar/react` y `core` en
**7.1.0** exactos. La propiedad de clase de un evento es `className` (la 6 usaba `classNames`): lo
detectó la verificación visual (los colores por proveedor no se aplicaban) y quedó cubierto por una
prueba sobre el DOM real.

**H2 · El shell del dashboard no es responsive (preexistente, bloquea la aceptación móvil real).**
`Sidebar` es `fixed w-64` y `main` lleva `ml-64` sin variante móvil: a 375 px el contenido de **cualquier**
página queda recortado. El calendario elige Día inicial y funciona a 375 px (comprobado ocultando la
barra lateral solo en el navegador), pero un usuario móvil no lo puede usar hasta que el shell sea
responsive. No se tocó: es un cambio transversal a todas las pantallas y excede esta tarea.
*Alternativa acotada:* tarea aparte que oculte la barra bajo `lg` y añada un botón de menú.

**H3 · Día completo de Outlook depende de supuestos sin validar con Graph real.** Se asume que, con
`Prefer: outlook.timezone="UTC"`, un evento de día completo llega convertido a UTC y que
`originalStartTimeZone` permite volver a su día civil. La tabla Windows→IANA cubre ~45 zonas habituales;
si la zona no se reconoce se usa la medianoche UTC más cercana (correcta para offsets entre −12 h y
+12 h). **Pendiente:** validar con una cuenta de Outlook de prueba en una zona no UTC antes de dar CA3
por cerrado para Outlook.

**H4 · Entorno.** `backend/.venv` no traía `pytest` ni `alembic` (la suite no corría); se instalaron las
versiones de `requirements-dev.txt`. Los puertos 8000 y 3000 estaban ocupados por procesos ajenos; la
verificación visual usó el 8765 (API ficticia) y el 3100 (`next start`) sin tocarlos.

**H5 · Orden RED/GREEN.** Unitarias e integración de backend y todas las de frontend se vieron en rojo
antes de implementar. Las pruebas de **seguridad y estrés** del backend se escribieron con las rutas ya
implementadas: se comprobó por mutación que detectan fugas (el error filtraba el cuerpo remoto; Graph
seguía cualquier `nextLink`) y fallan; luego se restauró el código.

**H6 · Una expectativa de prueba se cambió de forma consciente.** En `useCalendarEvents.test.tsx` el error
pasó de texto a `{ status, message }` porque el componente necesita el estado HTTP para elegir mensaje
(decidido al implementar, no para esquivar un fallo).

**H7 · Harness.** `UX-CAL-01` queda como evaluación; la implementación es `UX-CAL-02`. `next.py --check`
ya marcaba que `DG (agente)` tenía dos tareas activas; mientras UX-CAL-02 estuvo en curso fueron tres (instrucción expresa del usuario); en `review` vuelven a ser las dos previas.

**H8 · Cambios de comportamiento colaterales (acotados).**
- `getJobForEvent` ahora prefiere el job activo y, si no hay, el más reciente (antes devolvía el primero).
  Su único consumidor era el listado eliminado.
- `PreferencesProvider` expone `ready`.
- Se eliminó `CalendarMeetingsList.tsx` (solo lo usaba `AutomationCalendarPreview`; sin pruebas propias).
- `CalendarFormatGuideAnyAction` sigue haciendo sus dos consultas legadas con `top=1`; no se modificó.

## Pendientes

1. Revisión por un segundo integrante y evidencia en Trello (sin tarjeta asignada).
2. Validar H3 con una cuenta de Outlook de prueba; validar generación real de dossier desde el panel.
3. Decidir la tarea de shell responsive (H2).
4. Revisión visual de 768 px y de los idiomas restantes; prueba con lector de pantalla.
5. Cuando S1.2 cierre, pasar `ruff`/`mypy` sobre los archivos nuevos del backend.
