# Log de sesiones

Orden cronológico inverso: lo más reciente arriba.

Cada sesión que toca el repositorio deja una entrada. El formato está en
[handoff.md](handoff.md), sección 5. Las cuatro secciones importan, pero **«Lo que hay que
saber»** es la que ahorra horas: es lo que descubriste y no está escrito en ningún otro lado.

---

### 2026-09-12 · Revisión del Sprint 0 · EQ (agente, segunda sesión)

**Hecho.** Revisión de las 14 tareas de Sprint 0 en `review` (commit `a3c45b6`), contra el
código real, no contra lo que las ADRs dicen de sí mismas. Reporte completo en
`specs/reports/sprint0-verificacion.md`.

- **13 tareas → `done`**: S0.1, S0.2, S0.4 a S0.14. ADR 0001 verificada línea por línea contra
  el código y exacta. Argumento de SSE (ADR 0006) correcto: `new WebSocket()` no admite headers,
  por eso SSE con `Authorization: Bearer` es la elección sensata.
- **S0.15 → vuelve a `pending`**: su criterio exige acuerdo POR ESCRITO con el docente guía.
  Registrar el riesgo R1 no es acordarlo. No delegable a un agente.
- **ADR 0002 corregida**: precio de GPT-5.6 Luna no coincidía con la Guía de Fase 1 (0,20/1,20
  USD por millón). Se corrigió para no divergir del documento comprometido ante la comisión.
- **Cuatro hallazgos anotados** en las tareas que los heredan (no bloquean Sprint 0, pero hay
  que resolverlos al llegar a esas tareas):
  - **S2.4**: ADR 0003 menciona `agents_skipped`, columna que no existe en `models.py`
  - **S5.6**: ADR 0005 asume `ENCRYPTION_SECRET`, variable que no existe en el proyecto
  - **S4.10**: `Migracion.md:821-824` ya diseña campos de auditoría, nadie lo usó como base
  - **S4.3**: el más importante — el trigger de facturación (`dossier_data->>'billing'`) que
    `dossier_routes.py:91` menciona en un comentario **no aparece en ningún esquema
    versionado** (`Migracion.md`, `schema_patches.py`, `docs/sql/`). O vive solo en la base de
    producción fuera de control de versiones, o el comentario está obsoleto. Debe resolverse
    ANTES de empezar S4.3, no al llegar a ella: si se migra el contrato de `dossier_data` sin
    saber dónde vive ese trigger, el descuento de créditos puede romperse en silencio.

**Sin terminar.** S0.15 sigue pendiente de una reunión real con el docente guía. S0.3 (línea
base de deuda técnica) sigue en `pending`: sin ella, Sprint 0 no cierra del todo aunque el resto
esté en verde.

**Lo que hay que saber.** El patrón de esta sesión es el que vale para todo el proyecto: una
ADR bien escrita y bien argumentada puede aun así citar algo que no existe en el código. Verificar
contra el repositorio, no contra la prosa del documento, es lo que la fase 5 de SDD existe para
hacer. Ninguno de los cuatro hallazgos invalida las decisiones tomadas; todos son "falta
conectar esto antes de construir sobre ello".

**Siguiente paso concreto.** Agendar la reunión de S0.15. En paralelo, Sprint 1 ya puede
arrancar: S1.1 (migraciones Alembic) y S1.8 (cliente HTTP de la fuente europea, que no depende
de S0.15).

**Rama.** `FO` · **Estado.** listo para commit

### 2026-09-09 · Sprint 0 Diagnóstico, ADRs y Especificaciones · FO (agente)

**Hecho.** Completado el paquete completo de decisiones arquitectónicas y especificaciones del Sprint 0:
- Seis decisiones obligatorias del Sprint 0 (ADR 0001 a 0006) en `docs/architecture/decisions/`:
  * ADR 0001: Línea canónica DeepSeek; deprecación del shim Gemini y ruta monolítica OpenAI (S0.4).
  * ADR 0002: Modelo DeepSeek-V3 para síntesis con validación Pydantic estricta (S0.5).
  * ADR 0003: Fuente europea oficial abierta (Francia API Recherche d'entreprises y Alemania Handelsregister) cerrando el riesgo R2 (S0.6).
  * ADR 0004: Proveedor de noticias GDELT DOC 2.0 con filtro de homónimos y fallback NewsAPI (S0.7).
  * ADR 0005: Despacho de correo SMTP aiosmtplib + delegación OAuth Microsoft/Google (S0.8).
  * ADR 0006: Protocolo Server-Sent Events (SSE) para estados progresivos en tiempo real (S0.11).
- Especificaciones de arquitectura y propuestas SDD en `specs/proposals/`:
  * S0.9: Esquema JSON estricto del dossier ejecutivo con citas de fuente por afirmación.
  * S0.11: Contrato de eventos progresivos SSE y reanudación por `Last-Event-ID`.
  * S0.12: Arquitectura del orquestador LangGraph con ramas paralelas UK, US, EU y Noticias.
- Estrategia de migración de datos (`docs/architecture/estrategia-migracion-modelo-datos.md`, S0.10) preservando la clave `billing` para el trigger de créditos en PostgreSQL.
- Inventario completo de módulos (`docs/architecture/inventario-modulos.md`, S0.1) y criterios de aceptación formales por brecha (`docs/architecture/criterios-aceptacion-brechas.md`, S0.13).
- Creada la rama de desarrollo `FO`.

**Sin terminar.** Revisión por un segundo integrante del equipo (DG o FD) para pasar tareas a `done`. Quedan pendientes en Sprint 0 las mediciones de calidad de S0.3 (FD).

**Lo que hay que saber.**
- **Preservación del trigger de facturación:** Al migrar `dossier_data` a JSON estructurado (S4.3), la clave `'billing'` en la raíz del objeto JSONB no debe moverse; el trigger de PostgreSQL depende de `dossier_data->>'billing' != 'none'`.
- **Mitigación del riesgo R2:** La API francesa de `data.gouv.fr` no exige API key obligatoria y entrega JSON limpio con directores y SIREN/SIRET, lo que permite implementar el cliente en S1.8 inmediatamente sin barreras contractuales.
- **SSE vs WebSockets:** SSE evita la complejidad de mantener sockets stateful en Render y simplifica el paso del JWT en la cabecera `Authorization`.

**Siguiente paso concreto.** Revisión por segundo integrante. En Sprint 1: implementar S1.1 (migraciones Alembic) y S1.8 (cliente HTTP de la fuente europea).

**Rama.** `FO` · **Estado.** review

---

### 2026-09-07 · SDD y TDD · EQ (agente)

**Hecho.** Infraestructura de pruebas en las tres capas y la política que la gobierna.

- `docs/dev/testing-policy.md` — qué prueba exige cada tipo de cambio, incluida la eliminación
- `docs/dev/sdd-workflow.md` y `specs/` — especificación antes de codificar
- Backend: categorías automáticas por carpeta, `conftest.py` que apaga los trabajadores y
  bloquea la red, carpetas `stress/` y `security/` con plantillas vivas
- Frontend: Vitest configurado desde cero. **No había ningún runner de pruebas**
- `scripts/qa.py` — un comando antes de commit y push, que bloquea si cambias código sin pruebas
- `scripts/install-hooks.py` — ganchos pre-commit y pre-push

Verificado ejecutando: backend 49 en verde y 13 en espera de su tarea; frontend 14 en verde.

**Sin terminar.** Los ganchos **no están instalados**: el repositorio es un worktree y los ganchos
se comparten con los demás. Se dejó la decisión al equipo. Instalar con
`python scripts/install-hooks.py`.

**Lo que hay que saber.**
- **`npm run lint` da 21 errores y 6 avisos en 16 archivos**, todos preexistentes. Nadie los veía
  porque no hay CI. El más repetido es `react-hooks/set-state-in-effect`. Está en
  `PreferencesProvider.tsx:100`, que es **justo el archivo que S5.1 y S5.2 van a reescribir**:
  conviene corregirlo antes de esa migración, no después. Detalle en `fix_plan.md`.
- **Las pruebas de estrés no necesitan laboratorio.** Volumen, concurrencia y degradación se
  responden con pytest normal y corren en cada PR. La carga HTTP real ya existía en
  `scripts/load/` con k6 y sigue siendo manual.
- **k6 ya estaba en el repositorio** con dos escenarios reales (dedup async, límite de créditos).
  Se descartó añadir Locust por eso. Si escribes una prueba de estrés, mira primero si su
  escenario ya está en k6.
- **Cuidado al fijar variables de entorno en `conftest.py`.** Poner `DOSSIER_CHARGE_CREDITS=0`
  dejó en verde cuatro pruebas de `test_credit_policy.py` que precisamente verifican el cobro.
  Apagar una funcionalidad en el conftest puede volver verdes pruebas que no prueban nada.
- **Las pruebas con `skip` no son relleno.** Cada una nombra su tarea (S2.4, S5.8, S6.5…) y ya
  dice qué criterio debe cumplir. Al implementar esa tarea, se quita el `skip` y la prueba está
  escrita. Es TDD a escala de sprint.

**Siguiente paso concreto.** Decidir si se instalan los ganchos. Después, **S0.3** ya es más
barata: el entorno está montado en `backend/.venv` y la suite corre; falta medir cobertura y
ejecutar `pip-audit` y `npm audit`.

**Rama.** —  · **Estado.** pendiente de revisión

---

### 2026-09-07 · Harness inicial · EQ (agente)

**Hecho.** Estructura de harness creada: `AGENTS.md` como índice, `.harness/` con contexto,
protocolo de coordinación, plan de correcciones, log y `feature_list.json` con las 77 tareas
del plan enlazadas a sus tarjetas de Trello. Añadido `next.py` para consultar qué está
disponible. Creada la estructura `docs/architecture/`, `docs/security/` y
`docs/exec-plans/`.

**Sin terminar.** Nada de esta sesión. El harness está completo y usable.

**Lo que hay que saber.**
- Los documentos heredados de `docs/` (estructura, postgresql, sec_edgar, render-deploy,
  vercel-frontend, langgraph-dossier, auth-app, calendario-oauth-operaciones) **no se movieron**.
  `AGENTS.md` los indexa donde están. Si alguien reorganiza `docs/`, hay que actualizar el índice.
- `feature_list.json` es la fuente de verdad del estado. Trello es el espejo para las personas.
  Si divergen, gana el JSON: es el que los agentes leen.
- El tablero Trello vive en el espacio de trabajo personal de Felipe Orellana, no en el del
  equipo. El tablero original `Bc70DcAL` está en un espacio ajeno y el conector no lo alcanza.

**Siguiente paso concreto.** Arrancar **S0.6** (evaluación de la fuente europea). Es la
dependencia externa de plazo menos controlable y su fecha ya está adelantada a la semana 3.
En paralelo, **S0.3** para tener por fin números reales de deuda técnica.

**Rama.** —  · **Estado.** done

---

### 2026-09-07 · Auditoría y plan de trabajo · EQ (agente)

**Hecho.** Auditoría estática del repositorio contra la Guía de Fase 1. Confirmadas las cinco
brechas del alcance firme, ninguna implementada. Cuantificada la deuda técnica. Producido el
Plan de Trabajo Detallado (23 páginas) y cargado el backlog completo en Trello: 14 listas,
86 tarjetas.

**Sin terminar.** La migración del backlog al tablero del equipo `Bc70DcAL` quedó pendiente:
está en un espacio de trabajo ajeno y el conector de Trello no lo alcanza. Se creó un tablero
nuevo en el espacio personal como alternativa.

**Lo que hay que saber.**
- **La suite de pruebas nunca se ejecutó.** El entorno virtual del backend no estaba instalado
  (`No module named pytest`). Todos los conteos del plan son estáticos: 40 pruebas *declaradas*,
  no en verde. Cobertura y vulnerabilidades siguen sin medir. Es la tarea S0.3.
- **El avance ponderado da 45-50 %, no 55-60 %** como estima la Guía. La diferencia está en
  calidad e infraestructura de entrega, no en capacidades funcionales. No cambia el alcance,
  sí el énfasis: por eso el Sprint 1 se trata como bloqueante.
- **Las semanas 16 y 17 caen sobre el receso de fin de año** (21-12 al 03-01). Es el Sprint 6
  completo y el arranque del Sprint 7. Las tareas de seguridad ya se adelantaron a la semana 15,
  pero el calendario debe acordarse con el docente guía (S0.15).
- **El Sprint 4 concentra nueve de sus diez tareas en un solo responsable**, y el Sprint 5
  depende entero de él. Es el punto más frágil de la planificación.

**Siguiente paso concreto.** Sprint 0, tareas S0.1 a S0.15. Prioridad de arranque: S0.6 y S0.3.

**Rama.** —  · **Estado.** done

---

## Convención

Un identificador de sesión útil distingue quién trabajó: `FO`, `DG`, `FD` para personas;
`FO (agente)` cuando fue un agente actuando sobre ese frente. Si dos agentes trabajan a la vez,
añade una letra: `FO (agente A)`.
