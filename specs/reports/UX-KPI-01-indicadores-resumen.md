# UX-KPI-01 · Reporte de verificación

- **Fecha:** 2026-10-04 (versión con la enmienda «Créditos para preparar»)
- **Rama:** `codex/UX-KPI-01-indicadores-resumen` (sale de `codex/UX-CAL-01-calendario-visual`, que aporta los helpers de lectura por rango de UX-CAL-02; esa rama aún no está en `main`)
- **Especificación:** [UX-KPI-01](../proposals/UX-KPI-01-indicadores-resumen.md) · **Plan:** [secuencia](../../docs/exec-plans/active/UX-KPI-01-indicadores-resumen.md) · **Decisión:** [ADR 0008](../../docs/architecture/decisions/0008-indicador-creditos-para-preparar.md)
- **Estado:** implementado y verificado por su autor. **No es `done`**: falta la revisión del segundo integrante, el PR y la evidencia en Trello.

## Las cuatro tarjetas

| Tarjeta | Qué muestra |
|---|---|
| Reuniones por preparar | Reuniones externas elegibles de los próximos 7 días sin todos sus dossiers. |
| Cobertura de próximas reuniones | `100 × preparadas / elegibles` en ese mismo periodo. |
| **Créditos para preparar** | Créditos estimados para generar lo que falta en esas reuniones; cuántas lo requieren; advertencia si supera el saldo; «Sin costo» explicado si el plan no cobra o el cobro está desactivado. |
| Créditos disponibles | Saldo y límite mensual de la organización activa. |

La primera versión tenía «Reuniones preparadas a tiempo» como tercera tarjeta. Por decisión del usuario (2026-10-04) se reemplazó para que las cuatro miren lo que viene; con ella se retiró la evidencia histórica (tablas, migración, relleno, registro en la generación). Ver ADR 0008.

## Qué se implementó

| Capa | Cambio |
|---|---|
| Calendario | La lectura por intervalo conserva `iCalUID`, correos reales y el rechazo del usuario (solo esa ruta; el shape legado no cambia). `ErrorProveedorCalendario.reautenticar` distingue «reconectar» de «el proveedor falló». |
| Reglas | `services/meeting_prep_kpi.py` (lógica pura: elegibilidad, conjunto esperado, preparación, costo de lo que falta) y `services/meeting_identity.py` (identidad de ocurrencia). |
| API | `GET /dashboard/summary` (JWT; usuario y organización de la sesión). Caché por usuario+organización (60 s; 15 s errores), una consulta en vuelo, plazo y cupo acotados, invalidación al generar o borrar dossiers. El saldo y `exceeds_balance` se calculan fuera de la caché. |
| Interfaz | `OverviewKpiCards`, `useDashboardSummary`, cliente tipado, textos en los siete idiomas. `StatCard` admite `details`, `description` y `busy` sin cambiar a sus otros consumidores. |
| Esquema | **Ninguno.** No hay migración ni tablas nuevas. |

## Pruebas

Escritas primero y comprobadas en rojo antes de implementar (también en la enmienda).

| Suite | Casos | Resultado |
|---|---:|---|
| `tests/test_meeting_prep_kpi.py` (unitaria) | 35 | verde |
| `tests/test_calendar_range_meta.py` (unitaria) | 13 | verde |
| `tests/test_summary_cache.py` (unitaria) | 7 | verde |
| `tests/integration/test_dashboard_summary.py` (endpoint completo; **Postgres real**, calendario simulado) | 36 | verde |
| `tests/stress/test_dashboard_summary_estres.py` | 8 | verde |
| `tests/security/test_dashboard_summary_seguridad.py` | 10 | verde |
| Frontend (`dossier-api.dashboard-summary`, `dashboard-kpis`, `useDashboardSummary`, `StatCard`, `OverviewKpiCards`) | 50 | verde |

Backend completo: **388 pasan, 0 fallan, 13 omitidas** (marcadores `ejemplo` de otras tareas) con `TEST_DATABASE_URL` apuntando a un Postgres 17 desechable. **Sin esa variable, las 36 pruebas de integración del resumen se omiten**: no hay CI que levante una base. `mypy` sin errores; `ruff` sin hallazgos en archivos tocados (los del resto del repositorio son preexistentes); `eslint` y `tsc` limpios; `next build` correcto. Frontend: 199 pasan; falla `TimezoneSelect.test.tsx`, preexistente (ICU de Node local) y sin relación.

Pruebas eliminadas con la enmienda (dicho también en los commits): `test_prep_evidence_postgres.py` (17) y `test_prep_evidence_recording.py` (19), los casos de historial de `test_meeting_prep_kpi.py` (23), de `test_dashboard_summary.py` (8) y de `dashboard-kpis.test.ts`. `test_dossier_entities_schema.py` vuelve a su versión original.

Defectos reales encontrados y corregidos: el plazo de lectura de proveedores no cortaba a uno lento (pruebas de estrés); la advertencia de saldo insuficiente salía en gris (verificación visual).

## Criterios de aceptación

| CA | Evidencia |
|---|---|
| **CA1** 5 futuras, 3 preparadas → 2 y 60 % | `test_ca1_*` (unitaria e integración) y verificación visual. |
| **CA2** las 2 pendientes cuestan 5 (3 + 1 + 1) | `test_ca2_*` (unitaria e integración) y verificación visual: **5**, «Reuniones con dossiers por generar: 2». |
| **CA3** solo se cobra lo que falta | `test_ca3_*`: completo no suma, fallido sí, conjunto vacío ni suma ni cuenta. |
| **CA4** Free / Enterprise / cobro desactivado | `test_el_costo_por_rol_sale_del_plan`, `test_ca4_*` (integración) y pruebas de la tarjeta («Sin costo…»). |
| **CA5** volumen y paginación | `test_ca5_*` (120 reuniones, 240 dossiers), estrés con 2 500 reuniones; lectura incompleta → `calendar_incomplete`. |
| **CA6** ids iguales no se mezclan | `test_ids_iguales_*` (unitaria e integración), aislamiento por usuario. |
| **CA7** dos esperados y uno completo → pendiente | `test_ca7_*` (unitaria e integración). |
| **CA8** borrar antes de la reunión vuelve a sumar | `test_ca8_*`, `test_borrar_un_dossier_antes_de_la_reunion_la_devuelve_a_pendiente`, `test_borrar_un_dossier_invalida_la_cache`. |
| **CA9** aviso si supera el saldo | `test_ca9_*` (integración), tarjeta en color de advertencia (prueba de componente y visual con saldo 4). |
| **CA10** límites, DST, recurrencias, duplicados | Límites cerrado-abierto, DST de Madrid en instantes UTC, recurrencias (mismo iCalUID, otro instante), unificación solo con iCalUID + instante. |
| **CA11** estados distintos | `not_connected`, `empty`, `unavailable` con causa; créditos visibles. Verificado visualmente. |
| **CA12** aislamiento | 10 pruebas de seguridad; integración con otro usuario, otra organización, admin y viewer. |
| **CA13** actualizar tras generar; respuesta antigua no pisa; leer no crea jobs | Invalidación al persistir y borrar (integración); `refreshKey` y descarte por sesión (hook); `test_ca13_consultar_el_resumen_no_crea_jobs_ni_dossiers_ni_cobra_ni_programa`. |
| **CA14** escritorio y móvil, temas, idiomas, sin acciones | Cuatro/dos/una columnas; oscuro y claro; es, en y de en el navegador; siete idiomas sin claves sin traducir (prueba); cero enlaces o botones en las tarjetas. |

## Verificación visual (datos ficticios, servidor real)

API FastAPI real sobre una base desechable, cuenta ficticia y calendario simulado; `next dev` apuntando a ella. Con saldo 4, `GET /dashboard/summary` devolvió 2 pendientes, 60 %, 5 créditos estimados para 2 reuniones con `exceeds_balance: true` y saldo 4 de 500; la interfaz lo mostró con la advertencia resaltada. Nada tocó bases ni cuentas reales.

## Limitaciones que el revisor debe conocer

1. **Sin proveedores reales.** Google y Microsoft Graph se simularon.
2. **El estimado es un máximo.** La caché puede abaratar un dossier; la profundidad corporativa es la por defecto del plan (si el usuario elige otra al generar, el costo real cambia).
3. **El parser toma cualquier asunto como empresa.** En Pro/Enterprise toda reunión externa con título «espera» un dossier corporativo (comportamiento ya existente de la generación), y eso entra en el estimado.
4. **Dossiers compartidos** por otros miembros no cuentan como disponibles: su id de evento viene de otro calendario.
5. **Clave de persona = índice del contacto** en la descripción; reordenar contactos cambia lo que se considera hecho.
6. **Caché por proceso**: con varias instancias la desactualización máxima es 60 s salvo en la que procesa la generación.
7. **El shell de `/dashboard` no es responsive** (barra lateral fija desde el commit inicial); no se tocó.
8. **`dossier_generation_jobs` no tiene DDL** en `Migracion.md` ni en Alembic (solo existe como modelo ORM). Hallazgo independiente de esta tarea; se dejó una tarea sugerida.
9. Advertencias desfasadas de `CLAUDE.md`/`AGENTS.md`: ruff y mypy sí existen; eslint está limpio.

## Cómo comprobar los cuatro indicadores

1. Reinicia la API desde esta rama (el endpoint no existe en procesos arrancados antes).
2. Con un usuario con calendario conectado, `GET /dashboard/summary` con `Authorization: Bearer <JWT>`.
3. **Por preparar / cobertura:** reuniones externas de los próximos 7 días sin o con todos sus dossiers (empresa y cada contacto) completos y propios.
4. **Créditos para preparar:** genera el dossier que falta desde Calendario y vuelve a Resumen: el estimado baja en su costo (3 por empresa en Pro, 1 por persona) sin esperar el vencimiento de caché. Con saldo menor que el estimado aparece «Supera tu saldo disponible».
5. **Créditos disponibles:** `organizations.credits_balance` y `credits_monthly_limit` de la organización activa.
6. Para las pruebas de integración: `TEST_DATABASE_URL=postgresql://…/<base_con_«test»> python scripts/qa.py`.
