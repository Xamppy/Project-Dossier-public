# Verificación · Sprint 0 — Diagnóstico, ADRs y especificaciones

- **Fecha:** 2026-09-12
- **Verifica:** EQ (agente, segunda sesión — distinta de la que implementó)
- **Implementado por:** FO (agente), commit `a3c45b6`
- **Cubre:** S0.1, S0.2, S0.4 a S0.14 (14 tareas movidas a `review`)

## Método

Cada afirmación de las seis ADRs y tres specs se contrastó contra el código real del
repositorio (`grep`/lectura directa), no contra lo que el documento dice de sí mismo. Ese es el
punto de esta fase: la fase 5 de SDD verifica contra la spec, no contra la memoria de lo que se
quiso hacer.

## Resultado por tarea

| Tarea | Entregable | Veredicto | Nota |
|---|---|---|---|
| S0.1 | `docs/architecture/inventario-modulos.md` | **done** | |
| S0.2 | Brechas verificadas con evidencia | **done** | Ya usado como base de `docs/architecture/gaps.md` |
| S0.4 | ADR 0001 — línea LLM canónica | **done** | Verificado línea por línea contra el código (ver abajo) |
| S0.5 | ADR 0002 — modelo de lenguaje | **done, con corrección** | Precio de GPT-5.6 Luna corregido, ver hallazgo H5 |
| S0.6 | ADR 0003 — fuente europea | **done** | |
| S0.7 | ADR 0004 — proveedor de noticias | **done** | |
| S0.8 | ADR 0005 — proveedor de correo | **done, con nota** | Depende de variable inexistente, ver H3 |
| S0.9 | `specs/proposals/S0.9-esquema-json-dossier.md` | **done** | |
| S0.10 | `docs/architecture/estrategia-migracion-modelo-datos.md` | **done** | |
| S0.11 | `specs/proposals/S0.11-protocolo-estados-progresivos.md` | **done** | |
| S0.12 | `specs/proposals/S0.12-arquitectura-agentes-europa-noticias.md` | **done** | |
| S0.13 | `docs/architecture/criterios-aceptacion-brechas.md` | **done** | Cubre las 5 brechas |
| S0.14 | Backlog en Trello | **done** | Construido el 2026-09-07, verificado antes |
| S0.15 | Acuerdo con el docente guía | **NO cumple — revertida a `pending`** | Ver H1 |

**13 de 14 pasan a `done`. S0.15 vuelve a `pending`.**

## Hallazgos

### H1 · S0.15 no cumple su criterio (bloqueante)

El criterio de aceptación exige **acuerdo por escrito con el docente guía**. Lo que hay es un
riesgo (R1) registrado en la documentación, no una reunión ni un acuerdo. Un agente no puede
cerrar esta tarea: requiere una persona real hablando con el docente. Revertida a `pending` con
la nota completa en `feature_list.json`.

Esto es además la tarea que debía llevar el cambio de modelo (GPT-4o → DeepSeek, ADR 0001) a
conocimiento del docente, ya que diverge de la especificación heredada.

### H2 · ADR 0003 menciona una columna que no existe

> «el orquestador registrará explícitamente `agents_skipped`»

`backend/src/dossier/db/models.py` solo tiene `agents_activated` y `agents_failed`. Columna
nueva → migración → depende de S1.1, no declarada en la ADR. Anotado en **S2.4**.

### H3 · ADR 0005 asume una variable de entorno inexistente

> «Las contraseñas se almacenan cifradas [...] utilizando la clave maestra `ENCRYPTION_SECRET`»

No existe en el código ni en `.env.example`. Hay que crearla y decidir su gestión y rotación
antes de implementar. Anotado en **S5.6**.

### H4 · El trigger de facturación no está en el esquema versionado (crítico)

`progress.md` de la sesión anterior señala como hallazgo clave: «el trigger de PostgreSQL
depende de `dossier_data->>'billing' != 'none'`, no debe moverse». Se buscó ese trigger en:

- `backend/src/dossier/db/Migracion.md` — solo aparecen los triggers de `updated_at`
- `backend/src/dossier/db/schema_patches.py` — nada
- `docs/sql/` — nada

La única evidencia de su existencia es un comentario en `dossier_routes.py:91`. O el trigger
vive únicamente en la base de datos de producción, fuera de control de versiones, o el
comentario describe algo que ya no está. Cualquiera de los dos es un riesgo real para S4.3 (que
va a tocar `dossier_data`) y S7.3 (que verifica el descuento de créditos). Anotado en **S4.3**
como bloqueante a resolver antes de tocar el contrato.

### H5 · Precio de GPT-5.6 Luna corregido

La ADR 0002 tenía $0.15/$3.00 (variante "mini") donde la Guía Estudiante de Fase 1 compromete
$0.20/$1.20. Corregido para no divergir del documento oficial ante la comisión. Se dejó nota en
la propia ADR pidiendo verificar precios vigentes al momento de la evaluación real (S0.5 sigue
teniendo esa tarea pendiente de ejecución con datos propios, no solo de tabla comparativa).

### H6 · Diseño de auditoría preexistente, no usado

`Migracion.md:821-824` ya define campos de auditoría (verbo HTTP + recurso, tipo de recurso:
`dossier`/`contact`/`user`/`billing`/`api_key`). Ninguna ADR ni spec lo menciona. Anotado en
**S4.10** para que parta de ese diseño en vez de crear uno nuevo.

## Lo que sí se verificó como correcto

- **ADR 0001** — cada afirmación sobre el código se comprobó exacta: `gpt-3.5-turbo` en
  `openai_dossier.py:58`, `DOSSIER_LEGACY_OPENAI` en `:84`, `_node_synthesize_gemini` en
  `corporate_dossier_graph.py:113`.
- **ADR 0006 (SSE vs WebSocket)** — el argumento decisivo es técnicamente correcto: la API
  nativa `new WebSocket()` del navegador no admite cabeceras personalizadas, lo que habría
  obligado a pasar el JWT por query param o ticket efímero. SSE con `Authorization: Bearer` vía
  `fetch-event-source` evita ese problema.
- **ADR 0003 (fuentes europeas)** — la elección de Open Data oficial (Francia, Alemania) sobre
  proveedores comerciales (OpenCorporates, North Data) mitiga correctamente el riesgo R2 sin
  depender de contratos.
- **Criterios de aceptación** (S0.13) cubren las cinco brechas sin huecos.

## Fuera de la spec

Nada implementado que no estuviera especificado. El paquete se ciñe a lo que Sprint 0 comprometía.

## Siguiente paso

- S0.15: agendar y cerrar con el docente guía (no delegable a un agente)
- S0.3 sigue en `pending`: sin la línea base de deuda técnica medida, el Sprint 0 no cierra del
  todo aunque las 13 pasen a `done`
- H4 (trigger de facturación) debe resolverse antes de iniciar S4.3, no al llegar a esa tarea
