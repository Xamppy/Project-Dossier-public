# 0008 · Evidencia mínima de generación para los indicadores de Resumen

- **Fecha:** 2026-10-03
- **Estado:** aceptada (pendiente de la revisión del segundo integrante)
- **Decide:** DG (agente), a partir de la especificación UX-KPI-01
- **Tarea:** UX-KPI-01

## Contexto

Las tarjetas de Resumen calculaban sus cifras sobre `fetchDossiersFromApi(80)` y contaban
carpetas. Para medir «reuniones preparadas a tiempo por el usuario» hace falta saber quién
inició cada generación, cuándo terminó realmente y con qué reunión se asocia, y los dossiers
se purgan a los 7, 14, 30 o 90 días según el usuario: con solo filas vigentes un historial de
30 días es imposible. `updated_at` cambia con cualquier edición y no sirve como finalización.

## Decisión

1. **Tabla de hechos `dossier_generation_facts`**: un registro por resultado exitoso, escrito
   en la misma transacción que el dossier. Guarda claves, no contenido: usuario, organización,
   proveedor, calendario, id de evento externo, rol (`corporate` / `person:N`), origen
   (`manual` / `automatic`), finalización real, inicio de la reunión, conjunto esperado y la
   marca `dossier_deleted_at`. `dossier_id` no es FK: borrar el documento no borra el hecho.
2. **Idempotencia** por `result_key` = corrida + rol. La corrida es el id del job manual (un
   reintento de persistencia no duplica) o la carpeta generada (automática). Una regeneración
   es otra corrida y cuenta de nuevo; un resultado de caché cuenta aunque no cobre créditos.
3. **Borrar antes o después de la reunión** se resuelve con `dossier_deleted_at`: si es
   anterior al inicio, el hecho no acredita preparación; si es posterior, no se reescribe.
4. **Conjunto esperado**: lo deduce el parser de generación (empresa si el plan la incluye +
   un dossier por contacto). Para el futuro se calcula con el plan actual; para el pasado se usa
   el registrado en el hecho. Vacío nunca es «preparada».
5. **Futuro = dossiers vigentes del propio usuario** asociados por proveedor + id de evento
   (metadatos `dossier_data.calendar`). Los compartidos por otros no se asocian: su id de evento
   viene de otro calendario y no es verificable.
6. **Historial fiable**: `prep_evidence_meta.recording_started_at` marca desde cuándo se
   registra. Quien tiene retención numérica puede haber perdido evidencia anterior sin rastro,
   así que su intervalo medido empieza ahí (`partial`); quien conserva sus dossiers sin límite
   se mide completo. El relleno desde dossiers vigentes mejora la exactitud pero no extiende
   este intervalo.
7. **Relleno** (migración 0003) solo con asociaciones inequívocas: `manual` con metadatos de
   calendario, `automatic` con `calendar_event_id`. El disparador `calendar` sin evento interno
   (ruta síncrona antigua) no prueba acción manual y no se rellena. Sin `generation_completed_at`
   no hay hecho; un inicio ilegible queda NULL.
8. **Purga**: los hechos viven 90 días desde el inicio de su reunión y se borran con la cuenta
   (FK en cascada). El worker de retención los purga junto con los dossiers.
9. **Sin calendarios arbitrarios**: si un proveedor falla o una lectura queda incompleta, los
   derivados son `null` con causa explícita; no hay porcentaje de «algunos» calendarios.

## Alternativas descartadas

- Calcular sobre `dossiers` con `generation_completed_at`: la retención destruye el historial.
- Guardar solo contadores agregados: no admite reprogramaciones, borrados ni corrección.
- Crear `CalendarEvent` desde la lectura del resumen: leer programaría automatizaciones.
- Contar créditos como proxy de generación: la caché genera dossiers sin cobrar.

## Consecuencias

- Una migración (`c5a9e3b7d1f2`) y dos tablas nuevas; un cambio pequeño en `persist_calendar_dossiers`.
- El job manual ahora enlaza `calendar_event_id` cuando existe el evento interno del propio
  usuario. Efecto colateral: si el usuario borra todos los dossiers de esa reunión,
  `suppress_calendar_event_if_no_dossiers_remain` marca el evento como `skipped` y la
  automatización no lo regenera (antes un dossier manual sin enlace no producía ese efecto).
- Los usuarios con retención numérica ven «Historial parcial» hasta acumular 30 días de registro.
- Caché del resumen en el proceso (60 s; 15 s para errores), invalidada al generar o borrar.
