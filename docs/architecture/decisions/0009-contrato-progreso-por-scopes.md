# 0009 · Contrato de progreso por scopes y snapshot persistido en el job

- **Fecha:** 2026-10-15
- **Estado:** aceptada para S5.10; pendiente de la revisión del segundo integrante
- **Decide:** DG (responsable de S5.10)
- **Tarea:** S5.10 (prerrequisito backend de S5.4) · complementa [0006](0006-protocolo-estados-progresivos.md)

## Contexto

ADR 0006 eligió SSE y enumeró eventos (`job_status`, `agent_progress`, `partial_result`,
heartbeat) sin fijar su forma. S4.8 implementó el canal con `job_status`, `job_completed` y
`job_failed`; S4.9 añadió un `agent_progress` que solo informa fallos, al terminar el grafo y con el
job ID en un campo llamado `dossier_id`. S5.4 necesita progreso real de Calendario (agentes
corporativos y personas) y de Personas (PDL y Web pública), contenido parcial válido y un estado
que sobreviva a recargas y a la pérdida del bus en memoria.

La propuesta de contrato está en
[specs/proposals/S5.4-resultados-parciales-agentes.md](../../../specs/proposals/S5.4-resultados-parciales-agentes.md)
(sección «Dependencia backend»). Este ADR registra **la versión adoptada** y en qué se aparta
de esa propuesta y de ADR 0006.

## Alternativas evaluadas

| Opción | A favor | En contra |
|---|---|---|
| Solo eventos en el bus en memoria | Ningún cambio de esquema | Buffer de 200 eventos que se borra al terminar; una recarga o un reinicio pierde todo |
| Tabla nueva `dossier_job_progress` | Consultas por etapa | Migración, retención y aislamiento nuevos para un dato que siempre se lee junto al job |
| **Clave `_progress` dentro de `dossier_generation_jobs.result_payload` (JSONB existente)** | Sin migración; el aislamiento por usuario y organización del job ya lo cubre; GET, listado y stream lo reciben con `serialize_job` | Cada cambio reescribe el JSON del job; hay que fusionar en vez de reemplazar al terminar |

Para el observador del grafo: una variable global con el job actual mezclaría ejecuciones
concurrentes; acoplar los nodos a FastAPI rompe la ruta manual. Se elige envolver cada nodo al
construir el grafo **por invocación**, con un observador que es `None` en la ruta manual.

## Decisión

### Identidad

- `job_id`: el job autenticado. `dossier_id` solo identifica un dossier guardado; ningún evento
  nuevo lo usa como alias del job.
- `scope_id`: una ejecución dentro del job. `corporate:0` para el bloque corporativo;
  `person:N` para cada persona investigada (en Calendario, en el orden de las personas
  detectadas con nombre válido; en Personas, siempre `person:0`). No contiene correos ni IDs
  de proveedores.
- `revision`: entero creciente **persistido por job**, compartido por todos sus cambios de
  progreso. Distinto del `id` del frame SSE, que es volátil.

### Estados y motivos

Estados de agente o etapa: `pending`, `running`, `completed`, `failed`, `skipped`, `cancelled`.
Un estado terminal no cambia a otro estado; solo puede ganar metadatos (`used_in_final`,
`recovered_by`). `running` solo lo emite un callback de una ejecución real: un nodo o etapa que
no aplica pasa de `pending` a `skipped` sin pasar por `running`.

`reason_code` (opcional, estable para traducir; nunca texto de una excepción):

| Estado | Códigos |
|---|---|
| `completed` | `no_matches`, `cache_hit`, `cache_miss` |
| `skipped` | `out_of_scope`, `no_target_company`, `plan_not_included`, `cache_hit`, `cache_unavailable`, `force_refresh`, `mode_not_applicable`, `sufficient_profiles`, `no_profiles`, `configuration_missing`, `feature_disabled`, `insufficient_input`, `not_required`, `upstream_auth_failed`, `not_reached` |
| `failed` | `provider_error`, `provider_timeout`, `provider_quota`, `provider_rate_limit`, `upstream_auth_failed`, `structured_output_invalid`, `no_valid_report`, `persistence_error`, `interrupted` |

### Catálogos (los declara el servidor al crear el scope)

- **Corporativo** (`agents`, en este orden): `agent_corporate_uk`, `agent_corporate_usa`,
  `agent_corporate_eu`, `agent_news`, `synthesize_llm`. Son los IDs de los nodos de LangGraph,
  no los alias de ADR 0006 (`uk_corporate`, …), que nunca se implementaron.
- **Persona `pdl`** (`stages`): `person.cache_lookup`, `person.pdl_enrich`, `person.pdl_search`,
  `person.profile_normalization`, `person.context_analysis`, `person.profile_synthesis`,
  `person.markdown_fallback`, `person.report_finalize`, `person.persist`.
- **Persona `gemini_web`**: `person.cache_lookup`, `person.context_analysis`,
  `person.report_finalize`, `person.persist`. Es una llamada a DeepSeek sin buscador: el scope
  declara `live_web_search: false` y ninguna etapa se llama «búsqueda».

El orden del catálogo coincide con el orden real de ejecución. En `pdl` con
`DEEPSEEK_PERSON_WEB_ALWAYS`, `context_analysis` corre antes de `profile_synthesis`, como hoy.

### Snapshot `progress`

`serialize_job` (GET del job, listado y stream) añade `progress`, que es `null` si el job no tiene
progreso. `result` deja fuera la clave interna `_progress`, y es `null` mientras no haya
resultado.

```json
{
  "schema_version": 1,
  "revision": 7,
  "scopes": [
    {
      "scope_id": "corporate:0",
      "kind": "corporate",
      "label": "Acme Corp",
      "origin": "generated",
      "agents": [
        {"agent_name": "agent_corporate_uk", "status": "failed", "reason_code": "provider_error",
         "revision": 3, "timestamp": "2026-10-15T15:00:00+00:00"}
      ],
      "partial_results": [],
      "dossier": {"id": "…", "status": "complete"}
    },
    {
      "scope_id": "person:0",
      "kind": "person",
      "label": "Ana Prueba",
      "research_source": "pdl",
      "live_web_search": false,
      "origin": "generated",
      "profiles_count": 1,
      "stages": [
        {"stage_id": "person.pdl_enrich", "status": "completed", "reason_code": null,
         "revision": 4, "timestamp": "…", "attempts": {"total": 2, "failed": 0}}
      ],
      "partial_results": [],
      "dossier": null
    }
  ]
}
```

Son listas, no objetos, porque JSONB no conserva el orden de las claves. `origin` es `generated`,
`redis_cache` o `null` (aún no se sabe). `profiles_count` viene de la ejecución o de la caché;
con caché, `profiles` puede estar vacío y `profiles_count` ser mayor que cero.

### Eventos SSE nuevos

Se publican **después** de confirmar el cambio en la base. Todos llevan `schema_version: 1`,
`job_id`, `scope_id` y `revision`.

- `agent_progress` (solo scopes `corporate`): `agent_name`, `status`, `timestamp`, `reason_code`.
  **Reemplaza** al evento de S4.9, que solo informaba fallos al final y ponía el job ID en
  `dossier_id`: ese formato deja de emitirse.
- `stage_progress` (solo scopes `person`): `research_source`, `stage_id`, `status`,
  `timestamp`, `reason_code` y, si existen, `attempts`, `used_in_final`, `recovered_by`,
  `dossier_id` y `dossier_status` (en `person.persist`).
- `partial_result`: vista previa completa y reemplazable de una sección, nunca tokens.
  - Corporativo: `agent_name`, `section` (`corporate_eu`, `news`, `synthesis`),
    `format: "markdown"`, `content`, `origin`, `provisional: true`, `truncated`.
  - Persona: `research_source`, `stage_id`, `section` (`person_profiles`,
    `person_context_report`, `person_report`), `format` (`person_profiles` o `markdown`),
    `data` o `content`, `provenance` (`basis`, `sources`, `live_web_search`), `origin`,
    `provisional: true`, `truncated`.
- Al declarar scopes se publica además un `job_status` con el job completo, para que el catálogo
  llegue antes que las transiciones.

### Qué se publica como vista previa

| Sección | Cuándo | Contenido |
|---|---|---|
| `corporate_eu` | `agent_corporate_eu` completado con registros coincidentes | Las líneas de registros que ya se pasan al LLM, con su URL de registro |
| `news` | `agent_news` completado con menciones | Titular, medio, fecha, resumen y URL |
| `synthesis` | `synthesize_llm` completado | El Markdown final de la síntesis |
| `person_profiles` | `person.profile_normalization` completado | DTO con `record_key`, `full_name`, `job_title`, `company`, `profile_urls` (solo `https`, máximo 3) y `profiles_count` |
| `person_context_report` | `person.context_analysis` completado con texto válido | El texto del modelo; `basis: model_only`, `sources: []` |
| `person_report` | `person.report_finalize` completado | El informe elegido; `basis` según su origen (`provider_records`, `model_only` o `unknown` si viene de caché) |

**No se publican los bloques de UK y USA.** Mezclan los datos del registro con diagnósticos
internos («Error al analizar el documento: …», «No se pudieron cargar las series…») incluso
cuando el agente termina bien; separarlos exige una proyección pública propia, que queda
fuera de S5.10. El usuario los ve integrados en `synthesis`. Ningún parcial se publica si el
texto empieza por `# Error` o está vacío.

Límite: 32 KiB UTF-8 por sección, cortando entre bloques completos (líneas de lista o
párrafos), con `truncated: true` si se cortó. El DTO de perfiles nunca incluye `data` crudo de
PDL, parámetros de búsqueda, SQL, correos, teléfonos ni `verified_facts`.

### Persistencia y concurrencia

- Cada cambio se aplica en una transacción propia: `SELECT … FOR UPDATE` del job, aplicar,
  subir `revision`, guardar y, después del commit, publicar. Un candado por job en el proceso
  ordena además la publicación. Los nodos paralelos no comparten la `Session`.
- Si el job ya está en `completed`, `failed` o `cancelled`, el cambio se descarta: un callback
  tardío no resucita el job.
- Al terminar (worker o cancelación) se fusiona en vez de reemplazar: `result_payload` queda como
  el resultado más `_progress`, cerrado así: `pending` → `skipped` (`not_reached`) y `running`
  → `failed` (`interrupted`), o → `cancelled` si el job se canceló.
- Cada dossier guardado (persona o corporativo) copia su scope bajo
  `dossier_data["_progress"]`, también los registros `failed` con perfiles válidos, para poder
  mostrar «Ver información disponible» desde el dossier.
- La caché Redis no cambia: no guarda job ID, scope ni historial. Un acierto de caché crea
  estado nuevo (`cache_lookup` completado con `cache_hit` y el resto de etapas `skipped` con
  `cache_hit`).
- Si la escritura de progreso falla, se registra en el log y la generación sigue: el progreso
  nunca hace fallar un dossier.

### Cancelación

Cancelar cierra el progreso en la misma transacción. En Personas el worker comprueba la
cancelación **después** de investigar y guardar: si el dossier ya se guardó, queda guardado y el
progreso no vuelve a moverse. No hay cancelación dura ni reembolso.

### Transporte

El bus sigue siendo en memoria de un proceso. La latencia menor a 500 ms se garantiza solo con
API y worker en el mismo proceso, que es el despliegue actual. Con varios procesos el stream se
entera por su consulta a la base cada 10 s y recibe el snapshot completo; tiempo real entre
procesos requeriría Redis pub/sub, que no existe.

## Consecuencias

- El frontend de S5.4 consume este contrato; los clientes que ignoran `progress` y los eventos
  nuevos (S5.1) siguen funcionando igual.
- `agent_progress` cambia de forma: la prueba de S4.9 sobre el formato anterior se sustituye por
  la del nuevo contrato.
- Un `result_payload` puede existir con solo `_progress` mientras el job corre: todo lector debe
  pasar por `serialize_job` (hoy es el único).
- Si se separan API y worker en procesos distintos, este ADR no promete los 500 ms.
