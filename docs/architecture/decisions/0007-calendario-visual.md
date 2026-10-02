# 0007 · Calendario visual para reuniones

- **Fecha:** 2026-10-02
- **Estado:** propuesta, sin dependencias instaladas
- **Propone:** DG (agente), a solicitud de Darío
- **Tarea:** UX-CAL-01 · evaluación y planificación adicional al plan original

## Contexto

La página `/dashboard/automation` presenta eventos con `CalendarMeetingsList`, a través de
`AutomationCalendarPreview`. Se desea una experiencia similar a Apple Calendar: distribución
temporal, navegación por fechas y detalle de la reunión. El frontend usa Next.js 16.3.6,
React 19.2.4, TypeScript y Tailwind 4; todavía no tiene librería de calendario.

## Alternativas evaluadas

| Opción | A favor | Coste de adaptación / limitación |
|---|---|---|
| **FullCalendar Standard** | Integración React y Next.js documentada, vistas de calendario y personalización de contenido; licencia MIT para componentes estándar | Requiere diseñar el aspecto Dossier y comprobar la versión elegida con el build real |
| **Schedule-X** | Componente React, vistas de día/semana/mes y temas; núcleo abierto MIT | Alternativa viable; algunos complementos son premium y la integración utiliza Temporal. No se ha validado en este repositorio |
| **React Big Calendar** | Calendario de eventos con vistas habituales y licencia MIT | Requiere configurar un localizador de fechas; hay que comprobar zonas horarias y React 19 en una prueba local |
| Componente propio | Control completo del aspecto | Mantener solapamientos, recurrencias, fechas, navegación y accesibilidad añade trabajo sin valor diferencial para el MVP |

La comparación es documental, no un benchmark ni una prueba de integración. Un selector de fecha
por sí solo no cubre la distribución de reuniones por horas.

## Recomendación

Usar **FullCalendar Standard**, encapsulado en un componente de presentación de Dossier.
La apariencia se inspirará en Apple Calendar y respetará los colores, tipografía y temas de la
aplicación. La biblioteca organiza eventos; las conexiones OAuth y consultas permanecen en el
backend existente. No hace falta conectar FullCalendar directamente con Google.

La documentación consultada sirve v7 e indica compatibilidad React 17–19. Antes de instalar,
verificar la versión estable publicada, sus dependencias y la documentación de esa misma versión.
No mezclar recetas v6 (`@fullcalendar/daygrid`, adaptadores de zona) con imports v7. La versión
exacta quedará fijada en el lockfile tras la prueba local; no se declara compatibilidad runtime
verificada en esta evaluación.

## Consecuencias

- Día, semana y mes, con detalle de evento y generación de dossier, constituyen la primera entrega.
- La navegación requiere lectura por intervalo y paginación en los dos proveedores.
- Se mantiene el calendario principal de Google y el predeterminado de Outlook.
- Crear, editar, arrastrar, redimensionar o borrar citas, calendarios secundarios y SSE quedan
  fuera de esta propuesta. La consulta y la generación de dossiers conservan sus permisos.
- No se prevén cambios de base de datos ni nuevas credenciales para la biblioteca.
- Adoptar la recomendación depende de verificar build, accesibilidad y zonas horarias en el proyecto.

## Fuentes oficiales consultadas

- [FullCalendar React y Next.js](https://fullcalendar.io/docs/react).
- [FullCalendar Standard y Premium: licencias](https://fullcalendar.io/license).
- [FullCalendar: zonas horarias](https://fullcalendar.io/docs/timeZone).
- [Schedule-X: React](https://schedule-x.dev/docs/frameworks/react) y [repositorio](https://github.com/schedule-x/schedule-x).
- [React Big Calendar: integración, localizadores y licencia](https://github.com/bigcalendar/react-big-calendar).

Diseño y criterios: [especificación](../../../specs/proposals/UX-CAL-01-calendario-visual.md).
Secuencia: [plan](../../exec-plans/active/UX-CAL-01-calendario-visual.md).
