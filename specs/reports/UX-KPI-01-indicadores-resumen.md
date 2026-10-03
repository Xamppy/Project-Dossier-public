# UX-KPI-01 · Reporte de verificación

- **Fecha:** 2026-10-03
- **Rama:** `codex/UX-KPI-01-indicadores-resumen` (sale de `codex/UX-CAL-01-calendario-visual`, que aporta los helpers de lectura por rango de UX-CAL-02; esa rama aún no está en `main`)
- **Especificación:** [UX-KPI-01](../proposals/UX-KPI-01-indicadores-resumen.md) · **Plan:** [secuencia](../../docs/exec-plans/active/UX-KPI-01-indicadores-resumen.md) · **Decisión:** [ADR 0008](../../docs/architecture/decisions/0008-evidencia-de-preparacion-de-reuniones.md)
- **Estado:** implementado y verificado por su autor. **No es `done`**: falta la revisión del segundo integrante, el PR y la evidencia en Trello.

## Qué se implementó

| Capa | Cambio |
|---|---|
| Calendario | La lectura por intervalo conserva `iCalUID`, correos reales y el rechazo del usuario (solo esa ruta; el shape legado no cambia). `ErrorProveedorCalendario.reautenticar` distingue «reconectar» de «el proveedor falló». |
| Reglas | `services/meeting_prep_kpi.py` (lógica pura: elegibilidad, conjunto esperado, preparación futura, puntualidad manual) y `services/meeting_identity.py` (identidad de ocurrencia y hechos). |
| Datos | Migración `c5a9e3b7d1f2`: `dossier_generation_facts` y `prep_evidence_meta`, con relleno desde dossiers vigentes. DDL en `schema_patches.PREP_EVIDENCE_PATCHES`; documentado en `db/Migracion.md` §17. |
| Registro | `persist_calendar_dossiers` escribe un hecho por resultado exitoso (origen, corrida, esperado, inicio, finalización real). El job manual enlaza el evento interno del propio usuario; la ruta síncrona antigua queda marcada como manual; la automatización como automática. Borrar un dossier anota `dossier_deleted_at`; el worker de retención purga hechos fuera de ventana. |
| API | `GET /dashboard/summary` (JWT; usuario y organización de la sesión). Caché por usuario+organización (60 s; 15 s errores), una consulta en vuelo, plazo y cupo acotados, invalidación al generar o borrar. |
| Interfaz | Las cuatro tarjetas de Resumen (`OverviewKpiCards`), `useDashboardSummary`, cliente tipado, textos en los siete idiomas. `StatCard` admite `details`, `description` y `busy` sin cambiar a sus otros consumidores. |

## Pruebas

Escritas primero y comprobadas en rojo (módulo o comportamiento ausente) antes de implementar.

| Suite | Casos nuevos | Resultado |
|---|---:|---|
| `tests/test_meeting_prep_kpi.py` (unitaria) | 46 | verde |
| `tests/test_calendar_range_meta.py` (unitaria) | 13 | verde |
| `tests/test_summary_cache.py` (unitaria) | 7 | verde |
| `tests/integration/test_prep_evidence_postgres.py` (migración, relleno, servicio; **Postgres real**) | 17 | verde |
| `tests/integration/test_prep_evidence_recording.py` (registro, borrado, retención, job, automatización; **Postgres real**) | 19 | verde |
| `tests/integration/test_dashboard_summary.py` (endpoint completo; **Postgres real**, calendario simulado) | 35 | verde |
| `tests/stress/test_dashboard_summary_estres.py` | 8 | verde |
| `tests/security/test_dashboard_summary_seguridad.py` | 10 | verde |
| Frontend (`dossier-api.dashboard-summary`, `dashboard-kpis`, `useDashboardSummary`, `StatCard`, `OverviewKpiCards`) | 47 | verde |

Backend completo: **434 pasan, 0 fallan, 13 omitidas** (marcadores `ejemplo` de otras tareas) con `TEST_DATABASE_URL` apuntando a un Postgres 17 desechable. **Sin esa variable, las 71 pruebas de Postgres se omiten**: no hay CI que levante una base. `mypy`: sin errores en 114 archivos. `ruff`: 0 hallazgos en archivos tocados; los 26 restantes del repositorio (`main.py`, `scripts/`, pruebas heredadas) son preexistentes.

Prueba modificada a conciencia: `test_dossier_entities_schema.py::test_migracion_s45_es_la_unica_cabeza…` afirmaba que la cabeza de Alembic era S4.5. Con la migración 0003 la cabeza cambia por diseño; ahora comprueba la cadena lineal línea base → S4.5 → 0003 con una sola cabeza.

Defecto real destapado por las pruebas de estrés y corregido: el plazo de lectura de proveedores no cortaba a uno lento (el `with ThreadPoolExecutor` esperaba a los hilos al salir).

## Criterios de aceptación

| CA | Evidencia |
|---|---|
| **CA1** 5 futuras, 3 preparadas → 2 y 60 % | `test_ca1_*` (unitaria e integración) y verificación visual con datos ficticios: tarjetas **2** y **60 %**. |
| **CA2** 8 pasadas, 6 a tiempo, 11 dossiers → 75 % | `test_ca2_*` (unitaria e integración) y verificación visual: **75 %**, «Reuniones: 6 de 8», «Dossiers generados por ti a tiempo: 11». |
| **CA3** automático / otro usuario / fallido / en proceso / tarde no acreditan | `test_ca3_*` (unitaria e integración), `test_los_resultados_fallidos_no_dejan_hecho`, `test_un_job_que_falla_no_registra_hechos`. Un dossier compartido por otro no se asocia a la reunión (ADR 0008 §5). |
| **CA4** dos dossiers = dos dossiers y una reunión; reintentos no duplican | `test_ca4_*` (unitaria, `UNIQUE(result_key)` y registro con la misma corrida). |
| **CA5** más de 80 dossiers y varias páginas; un fallo no da un porcentaje definitivo | `test_ca5_*` (120 reuniones/240 dossiers), estrés con 3 000 reuniones y 6 000 hechos, `calendar_incomplete`. |
| **CA6** manual legado se asocia sin mezclar ids | `test_el_relleno_recupera_solo_asociaciones_inequivocas`, `test_ids_iguales_de_proveedores_o_usuarios_distintos_quedan_separados`, `test_ca6_el_enlace_no_cruza_proveedores_ni_usuarios`. |
| **CA7** esperado 2 y completo 1 → pendiente; módulo no incluido no se exige | `test_ca7_*`, `test_en_plan_free_*` (unitaria, integración y registro). |
| **CA8** retención y borrado antes/después | `test_ca8_*`, `test_la_retencion_borra_el_documento_pero_conserva_el_hecho`, `test_borrar_un_dossier_antes_de_la_reunion_la_devuelve_a_pendiente`. |
| **CA9** historia purgada: intervalo verificable, sin inventar | `test_ca9_historial_parcial_*` (`partial`, `measured_from`), `test_ca9_la_finalizacion_registrada_nunca_es_updated_at`, inicio ilegible → NULL, sin `generation_completed_at` no hay hecho. |
| **CA10** límites, DST, reprogramación, recurrencias, cancelaciones | Límites cerrado-abierto, DST de Madrid (instantes UTC), reprogramación (manda el inicio vigente), recurrencias (mismo iCalUID, otro instante = otra reunión), unificación solo con iCalUID + instante, no por título ni cercanía. Las canceladas ya las excluyen los clientes de UX-CAL-02. |
| **CA11** estados distintos | `not_connected`, `empty`, `partial`, `unavailable` con causa (`calendar_reauth_required`, `calendar_unavailable`, `calendar_incomplete`, `calendar_busy`, `evidence_unavailable`); créditos siguen visibles. Verificado visualmente: sin calendario y proveedor caído muestran guion + causa, nunca ceros. |
| **CA12** aislamiento | 10 pruebas de seguridad (401, token manipulado/expirado/usuario inexistente, identidad de la sesión, respuesta sin campos fuera de contrato, solo lectura) y `test_ca12_*`, admin y viewer en integración. |
| **CA13** actualizar tras generar; respuesta antigua no pisa; leer no crea jobs | Invalidación al persistir y al borrar (integración); `refreshKey` y descarte de respuestas de otra sesión (hook); `test_ca13_consultar_el_resumen_no_crea_jobs_ni_dossiers_ni_cobra_ni_programa`. |
| **CA14** escritorio y móvil, temas, idiomas, sin acciones | Cuatro/dos/una columnas verificadas (1 columna a 375 px, 2 a 800 px) sin desbordamiento; tema oscuro y claro; es y de en el navegador; siete idiomas sin claves sin traducir (prueba); cero enlaces/botones en las tarjetas (prueba). Actividad y calendario de Resumen intactos. |

## Verificación visual (datos ficticios, servidor real)

Servidor FastAPI real sobre una base desechable con cuenta ficticia y calendario simulado, y `next dev` apuntando a él. `GET /dashboard/summary` devolvió exactamente el fixture de CA1 y CA2 (2 / 60 % / 75 % / 6 de 8 / 11 / 42 de 500) y la interfaz lo mostró. También se vieron los estados sin calendario conectado y proveedor caído. Nada tocó bases ni cuentas reales.

## Limitaciones y decisiones que el revisor debe conocer

1. **Sin proveedores reales.** Google y Microsoft Graph se simularon; `iCalUID`, `responseStatus` y los correos de Graph se validaron contra la forma documentada, no contra una cuenta.
2. **Historial parcial al inicio.** Con retención numérica (el valor por defecto es 30 días) el intervalo medido empieza en `recording_started_at`: «Historial parcial» durante los primeros 30 días tras el despliegue. El relleno mejora la exactitud, no extiende ese intervalo. Si se aplica solo el arranque por parches, sin Alembic, no hay relleno.
3. **Relleno optimista en un caso.** Un corporativo que falló no se guardaba como fila, así que el conjunto esperado rellenado puede quedar corto.
4. **Dossiers compartidos** de otros no cuentan para la cobertura futura (no hay forma verificable de asociar su id de evento a *mi* calendario).
5. **El parser toma cualquier asunto como empresa.** Para Pro/Enterprise toda reunión externa con título «espera» un dossier corporativo (comportamiento ya existente de generación). El conjunto esperado vacío solo ocurre en Free sin «Contacto:».
6. **Clave de persona = índice de contacto.** Reordenar los contactos del evento cambia las claves.
7. **Efecto colateral del enlace:** al borrar todos los dossiers de una reunión cuyo evento interno existe, la automatización no la regenerará (`suppress_calendar_event_if_no_dossiers_remain`).
8. **Caché por proceso**; con varias instancias, la desactualización máxima es 60 s salvo en la que procesa la generación.
9. **`dossier_generation_jobs` no tiene DDL** en `Migracion.md` ni en Alembic (solo existe como modelo ORM y la crea `create_all`). Descubierto al probar; no se corrigió aquí. Mi tabla no depende de ella.
10. **El shell de `/dashboard` no es responsive** (barra lateral `w-64` fija con `ml-64`, desde el commit inicial): a 375 px las tarjetas quedan recortadas por el contenedor, no por ellas. Se verificó la distribución de las tarjetas ocultando la barra; no se tocó el shell.
11. `docs/sql/schema_project_dossier.sql` es una copia antigua de `Migracion.md` (sin secciones incrementales); no se actualizó.
12. Advertencias de `CLAUDE.md`/`AGENTS.md` desfasadas: ruff y mypy sí existen y mypy pasa; eslint está limpio (0 errores). Las fallas medidas al inicio fueron un residuo local (`src/dossier/gemini/__pycache__`, ignorado por git, eliminado) y `TimezoneSelect.test.tsx` (ICU de Node local, preexistente y sin relación).

## Cómo comprobar los cuatro indicadores

1. `alembic upgrade head` en una base de pruebas y arrancar la API con `DATABASE_URL` hacia ella.
2. Con la sesión de un usuario con calendario conectado, `GET /dashboard/summary` con `Authorization: Bearer <JWT>`.
3. **Reuniones por preparar / cobertura:** reuniones externas de los próximos 7 días sin/ con todos sus dossiers (empresa y cada contacto) completos y propios. Generar el dossier que falta desde Calendario y volver a Resumen: el valor baja y el porcentaje sube sin esperar el vencimiento de caché.
4. **Preparadas a tiempo:** solo cuentan dossiers que el usuario pidió a mano y terminaron antes del inicio; los automáticos y los de otros miembros no. El conteo de dossiers es aparte.
5. **Créditos:** `organizations.credits_balance` y `credits_monthly_limit` de la organización activa.
6. Para la suite de Postgres: `TEST_DATABASE_URL=postgresql://…/<base_con_«test»_en_el_nombre> python scripts/qa.py`.
