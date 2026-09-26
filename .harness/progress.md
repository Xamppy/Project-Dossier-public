# Log de sesiones

Orden cronológico inverso: lo más reciente arriba.

Cada sesión que toca el repositorio deja una entrada. El formato está en
[handoff.md](handoff.md), sección 5. Las cuatro secciones importan, pero **«Lo que hay que
saber»** es la que ahorra horas: es lo que descubriste y no está escrito en ningún otro lado.

---

### 2026-09-26 · S4.3 (recomendación y confianza) · FO (agente)

**Hecho.** A pedido del usuario, el informe vuelve a traer las secciones 7 («Conclusión y
recomendación») y 8 («Nivel de confianza») del Markdown anterior. Se agregaron al contrato
(`FinalRecommendation` y `ConfidenceAssessment`) con la spec S0.9 ampliada (CA5 y CA6), y se
renderizan en los 6 idiomas. Suite: 180 passed con Postgres. Con DeepSeek real: 1 llamada
(19 s) y ambas secciones completas.

**Lo que hay que saber.**
- **Opcionales en el contrato, obligatorios al sintetizar.** Los payloads ya guardados siguen
  validando (CA5). La síntesis valida contra `_PayloadSintetizado`, una subclase con los dos
  campos obligatorios: si el modelo los omite, el reintento asistido los pide (CA6).
- **Cambia qué cuenta como respuesta válida del LLM.** Por eso se actualizaron, a propósito,
  los helpers `_payload_json` y `_respuesta_valida` de las pruebas de S4.2 y S4.3. Las pruebas
  de S4.1 no se tocaron y siguen en verde.
- **El modelo real escribió «Datos proporcionados» como fuente**, en vez de «People Data
  Labs». Exigir fuentes precisas corresponde a S4.7.
- Ojo al generar código con `\n` desde un heredoc de bash en esta máquina: aparece como salto
  de línea real y rompe las cadenas. Usa el editor.

**Rama.** `FO` · **Estado.** review

---

### 2026-09-26 · S4.3 · FO (agente)

**Hecho.** Los dossiers de persona (vía PDL) ahora se generan con **una sola llamada JSON**
(S4.2). El Markdown que ve el dashboard se renderiza por código desde ese JSON
(`services/executive_markdown.py`, títulos en los 6 idiomas). `dossier_data` suma
`executive_payload` (el contrato validado) y conserva `format: "markdown"`, `body` y
`billing`. El frontend no cambió. La caché de Redis y el camino del calendario conservan el
payload, porque todo pasa por `run_person_research`.

12 pruebas nuevas; la suite da 168 passed con Postgres y 158 sin él. De punta a punta, con
DeepSeek real, un perfil ficticio y `dossier_test`: 1 llamada (30 s), status `complete`,
`billing: charged` y el trigger descontó el crédito (10 → 9).

**Sin terminar.**
- El dashboard todavía no **aprovecha** el JSON: muestra el Markdown derivado. Una vista
  estructurada (tarjetas de alertas, línea de tiempo) sería trabajo de frontend nuevo.
- La búsqueda por IA (`gemini_web`) y el grafo corporativo siguen generando Markdown directo,
  sin payload.
- No verifiqué el dashboard en el navegador con un dossier nuevo: habría requerido una
  búsqueda PDL de una persona real o sembrar datos en la base de desarrollo.

**Lo que hay que saber.**
- **Se apartó de §3 del diseño (con acuerdo del usuario: lo más económico y simple).** No hay
  `format: "structured_json"` ni `legacy_markdown_body`; el payload va **al lado** del
  Markdown. Está documentado en `estrategia-migracion-modelo-datos.md` §3. Consecuencia para
  S4.4 (compatibilidad de lectura): un dossier nuevo **sigue siendo** `format == "markdown"`,
  así que `parse_dossier_payload` lo trata como histórico. Quien quiera el contrato debe leer
  `dossier_data["executive_payload"]` cuando exista.
- **Respaldo a Markdown solo ante JSON inválido** (`StructuredSynthesisError`), con un aviso en
  `warnings`. Si el proveedor está caído no hay respaldo: la segunda llamada fallaría igual y
  solo sumaría espera.
- **El informe se volvió más corto y estructurado** que el Markdown de 8 secciones anterior:
  ya no hay "nivel de confianza" ni recomendación final. Si el equipo extraña algo, el lugar
  para agregarlo es el contrato de S4.1 más el renderizado, no el prompt.
- El pipeline devuelve el dossier guardado en `result["saved_dossier"]`, no en `"saved"`.

**Siguiente paso concreto.** Revisar S4.1 → S4.2 → S4.3 en ese orden (se tomaron
encadenadas, con la anterior en `review`). Luego, en un navegador, generar un dossier de
prueba y confirmar cómo se ve el Markdown derivado.

**Rama.** `FO` · **Estado.** review

---

### 2026-09-26 · S4.2 · FO (agente)

**Hecho.** La síntesis puede emitir el contrato de S4.1 validado.
`llm/structured_synthesis.py:synthesize_executive_payload()` hace cuatro cosas:
- pide a DeepSeek modo `json_object` (nuevo parámetro `json_mode` en `chat_completion`);
- inyecta un **ejemplo de instancia** más el JSON Schema;
- valida con Pydantic;
- si no valida, hace un reintento asistido que le devuelve al modelo los errores concretos
  (acotados a 20 errores y 8.000 caracteres de eco).

Si aun así falla, lanza `StructuredSynthesisError`. Para persona está
`analyze_person_profile_bundle_structured()`. Hay 18 pruebas nuevas (unitarias, integración y
estrés) y la suite da 147 passed. Validado contra DeepSeek real con datos ficticios, en español
y en inglés: 1 llamada cada uno y payload válido.

**Sin terminar.** No está conectado al pipeline: `person_research_pipeline.py` sigue
persistiendo `{"format": "markdown"}`. Hacer ese cambio es S4.3. Tampoco cubre el grafo
corporativo (`graphs/corporate_dossier_graph.py`), que tiene su propia síntesis.

**Lo que hay que saber.**
- **Se tomó con S4.1 todavía en `review`**, por decisión del usuario (ruta crítica del MVP).
  `next.py --claim` la rechazaba; se marcó con `--set` y quedó anotado. Si la revisión de S4.1
  cambia el contrato, hay que ajustar el ejemplo de `executive_payload_example()`. Ese ejemplo
  se construye con los propios modelos, así que una prueba lo detecta.
- **Las pruebas con el doble del LLM no bastan aquí; hay que probar contra el proveedor.** El
  primer diseño reutilizaba los prompts del informe Markdown, más el esquema crudo. Pasaba las
  15 pruebas, pero con DeepSeek real devolvía el **JSON Schema copiado seguido del informe en
  Markdown**, incluso en modo `json_object`. Hubo dos correcciones, cada una con su prueba de
  regresión:
  1. Prompts propios, sin las instrucciones de secciones `##` (`person_structured_system_prompt`).
  2. Un ejemplo de instancia además del esquema, con la advertencia de no copiarlo.
- **El idioma tiene que ir también en el mensaje de usuario.** Con la directiva solo en el
  sistema, una corrida en inglés salió en español.
- **Una corrida en inglés tardó 143 s y no se repitió** (la siguiente tardó 14 s, con una sola
  llamada). No quedó claro si fue latencia de DeepSeek o los reintentos internos de
  `chat_completion`. Conviene medir esto en S4.3 con datos reales de volumen.
- **Una prueba de integración se reescribió a conciencia**, según la política §2, regla 1.
  Exigía reutilizar el prompt de sistema Markdown, y el proveedor real demostró que ese
  requisito estaba mal. Además, el doble del SDK de OpenAI ahora descarta los argumentos `omit`,
  igual que el SDK real. Así se envía `response_format` solo cuando se pide, sin romper mypy.
- **Una prueba sobre el proveedor real no puede quedar en la suite**, porque `sin_red` lo
  bloquea y costaría tokens en cada PR. El script del smoke test está en la conversación de
  esta sesión, no en el repositorio; si se quiere repetir, conviene que viva en `scripts/`.

**Siguiente paso concreto.** S4.3: en `person_research_pipeline.py:189`, usar
`analyze_person_profile_bundle_structured` y guardar el payload con la estructura v2.0 de
`estrategia-migracion-modelo-datos.md` §3. Hay que conservar `"billing"` en la raíz, porque de
eso depende el trigger de cobro, y mantener `legacy_markdown_body` mientras el frontend lea
Markdown.

**Rama.** `FO` · **Estado.** review

---

### 2026-09-26 · S4.5 · FO (agente)

**Hecho.** Las entidades de alertas, trayectoria y menciones de prensa cubren el contrato de
S4.1 (`schemas/dossier_executive_payload.py`). DDL idempotente en
`db/schema_patches.py:DOSSIER_ENTITIES_PATCHES`, migración Alembic `b7e2d4f1a9c3` (reutiliza
esa tupla, igual que la línea base con `_PATCHES`) y modelos ORM `DossierAlert`,
`DossierMediaMention` y `DossierCareerEntry`. 21 pruebas nuevas (unitarias, integración y
seguridad); suite completa 138 passed con Postgres. Verificado también contra la base local
de desarrollo: al reiniciar la API aparecen las columnas y el CHECK ampliado.

Antes, en la misma sesión: se trajo `docmac` a `FO` por fast-forward, se reinstalaron las
dependencias y se commiteó un fix de hidratación en el selector de zona horaria
(`lib/timezones.ts`: Node y Chrome formatean distinto el offset de UTC).

**Sin terminar.** Nada de S4.5. Falta quien **escriba** en estas tablas: hoy ningún código
persiste el payload estructurado en ellas. Eso cae en el pipeline de S4.x/S3.x, no en S4.5.

**Lo que hay que saber.**
- **Se desvió del diseño aprobado de S0.10, con acuerdo del usuario.** El documento proponía
  crear `dossier_risk_alerts`, `dossier_career_positions` y `dossier_press_mentions`, pero la
  línea base ya trae `dossier_alerts`, `dossier_career_entries` y `dossier_media_mentions`
  con el mismo propósito, cascada hacia `dossiers` y cero uso en el código. Se extendieron
  esas. La tabla de correspondencia contrato → columnas está en
  `docs/architecture/estrategia-migracion-modelo-datos.md` §2. FD revisó ese diseño: conviene
  que lo vea.
- **`dossier_alerts.level` mezcla dos vocabularios a propósito**: `critical/warning`
  (heredado) y `low/medium/high` (contrato). El CHECK acepta los cinco. El `downgrade` de
  `b7e2d4f1a9c3` **borra** las alertas con niveles del contrato antes de restaurar el CHECK
  original; no hay equivalencia honesta entre ambos.
- **El esquema tiene dos caminos y S4.5 cubre ambos.** Tu base local no tiene
  `alembic_version`: la extiende `apply_schema_patches` al arrancar (ahora aplica
  `_PATCHES + DOSSIER_ENTITIES_PATCHES`). Una base nueva la extiende `alembic upgrade head`.
  **No metas parches nuevos en `_PATCHES`**: la migración de línea base la itera en vivo y
  dejaría de ser una foto fija. Cada tarea que toque el esquema debería tener su propia tupla
  y su propia migración, como aquí.
- **Nuevos fixtures en `tests/conftest.py`: `pg_vacia`, `alembic_cfg` y `sembrar_dossier`.**
  Corren contra el Postgres de `TEST_DATABASE_URL`, que se define en la terminal y no en
  `.env`. Recrean el esquema `public` en cada prueba, así que se niegan a correr si el nombre
  de la base no contiene «test». En esta máquina existe `dossier_test`. S6.5 y S6.7 pueden
  reutilizarlos tal cual.
- **La CI no levanta Postgres**, así que ahí esas 9 pruebas se saltan. Es un hueco real en S1.5:
  la integración de base de datos solo corre en local.
- **`db/Migracion.md` no se tocó**, siguiendo la convención de los parches anteriores
  (`dossier_shares`, `org_invites` tampoco están ahí). Hoy la fuente de verdad del esquema es
  Migracion.md, más `schema_patches.py`, más las migraciones.
- **Ruff marca 26 errores preexistentes** (scripts, `alembic/env.py`, pruebas antiguas). No
  se corrigieron para no mezclar análisis estático con un cambio funcional. Detalle: como existe
  `backend/alembic/`, ruff trata `alembic` como paquete local y exige importarlo después de
  `sqlalchemy`.

**Siguiente paso concreto.** Revisión de S4.5 por otro integrante (FD, por el cambio de
diseño). Después, S6.5 (retención de 24 h) y S6.7 (aislamiento entre organizaciones) quedan
desbloqueadas y pueden apoyarse en la cascada ya probada en
`tests/security/test_dossier_entities_seguridad.py`.

**Rama.** `FO` · **Estado.** review

---

### 2026-09-23 · S1.3 (frontend, omision cerrada) · FD (agente)

**Hecho.** El commit `af49943` (S1.3) solo corrigio el backend; los 21 errores y 6 avisos de
`npm run lint` en el frontend, documentados desde la auditoria del 07-09-2026 y con la nota
explicita "se corrigen en S1.3" en `fix_plan.md`, habian quedado sin tocar. Detectado al
preguntar si "los cientos de errores del principio" ya estaban en el informe de cierre de A3.
Corregido en 17 archivos:

- **21 errores `react-hooks/set-state-in-effect`** (regla nueva de eslint-plugin-react-hooks
  que marca cualquier `setState` sincrono dentro del cuerpo de un `useEffect`). Todos son
  patrones legitimos y repetidos en el codebase (cargar datos al montar, sincronizar con
  localStorage, reflejar el estado de un job rastreado por un provider, recortar un valor
  fuera de rango). Sin suite de pruebas E2E que cubra estos componentes, refactorizarlos de
  verdad (mover a estado derivado, `useSyncExternalStore`, etc.) es riesgo de romper
  comportamiento sin forma de verificarlo en esta sesion -- mismo criterio que los 23 BLE001
  del backend en S1.3: se documentaron con `eslint-disable-next-line` y una razon puntual por
  linea, no se suprimio la regla globalmente.
- **2 `no-unused-vars` reales**: `enEntries` en `scripts/sync-i18n-keys.mjs` (variable y
  funcion `extractEntries` sin ningun uso, eliminadas) y `handleRegeneratePerson` en
  `CorporateDossierDetailView.tsx` (funcion completa sin conectar a ningun boton -- el flujo
  de "regenerar" para personas navega a `/person-research` con precarga, no reenvia el job
  desde esta vista; eliminada junto con los 4 imports que quedaron huerfanos).
- **2 `react-hooks/exhaustive-deps`**: en `CorporateDossierGenerateView.tsx` se agrego `t` a
  las dependencias (fix real: sin esto, el mensaje de error traducido podia quedar en el
  idioma anterior si el usuario cambiaba de idioma con un job activo). En
  `PreferencesProvider.tsx` se dejo `eslint-disable-next-line` justificado: la lista de
  dependencias es parcial a proposito (solo los campos que viajan al backend), agregar el
  objeto `preferences` completo dispararia el debounce en cada cambio de UI que no le importa
  al servidor.
- **2 `jsx-a11y/alt-text`** en `BrandLogo.tsx`: falso positivo -- el `alt` ya se pasaba via
  `{...shared}` pero eslint no lo rastrea a traves de un spread. Se agrego `alt={shared.alt}`
  explicito en cada `<Image>`, mismo valor, cero cambio de comportamiento.

**Sin terminar.** Nada -- `npm run build` corrio en la maquina de FD el mismo dia y
confirmo: 0/0, compilo, paso TypeScript, genero las 14 rutas. El primer intento fallo por una
razon aparte: el `node_modules` de `frontend/` habia quedado con una instalacion a medias
(`@next/swc` seguia en 16.2.6 mientras `next` ya estaba en 16.3.6 desde S1.4) -- mismo tipo de
corrupcion en carpeta de red que ya se habia visto con `sharp-win32-x64`. Se resolvio con
`Remove-Item -Recurse -Force node_modules` + `npm install` limpio.

**Lo que hay que saber.** `npm run lint` y `npm test` (14/14) si se pudieron correr completos
y quedaron en verde. El patron de "solo el primer `setState` de un `useEffect` se reporta,
los siguientes en el mismo efecto no" costo una vuelta extra: un `eslint-disable-next-line`
en la segunda ocurrencia del mismo efecto queda como "unused eslint-disable directive"
(warning), hay que quitarlo. Tambien: `eslint-disable-next-line` solo desactiva la linea
inmediatamente siguiente -- un comentario de justificacion envuelto en dos lineas hace que la
directiva "salte" a la segunda linea del comentario en vez de a la linea de codigo real; hay
que escribir la razon completa en una sola linea.

**Siguiente paso concreto.** Ninguno para S1.3. Correr `npm run build` como verificacion final
antes de comitear.

**Rama.** `main` (sin comitear aun -- a peticion de FD, que hace los commits el mismo).
**Estado.** done.

---

### 2026-09-23 · Hallazgo sin tarea S · FD (agente)

**Hecho.** Investigadas y corregidas las 4 pruebas rojas preexistentes en
`test_credit_policy.py` (listadas en `fix_plan.md` como hallazgo sin tarea asignada, no
tocadas en S1.3 a propósito por ser corrección funcional y no análisis estático). Causa
raíz: `dossier/api/app.py` llama `load_env()` a nivel de módulo (línea de import, no dentro
de una función), y pruebas como `tests/integration/test_dossier_stream_route.py` y
`tests/security/test_dossier_stream_seguridad.py` importan ese módulo durante la
*recolección* de pytest — antes de que corra el fixture `autouse` de `conftest.py`. Eso
cargaba el `backend/.env` real del desarrollador (con `DOSSIER_CHARGE_CREDITS=false`,
legítimo para demos locales) directo a `os.environ`, y ahí quedaba para el resto de la
sesión de pytest. Por eso las 4 pruebas pasaban solas (`pytest tests/test_credit_policy.py`)
pero fallaban dentro de la suite completa — dependía de qué otro archivo se hubiera
importado antes en esa ejecución. Fix de una línea en `tests/conftest.py`:
`os.environ.pop("DOSSIER_CHARGE_CREDITS", None)` al inicio del fixture, para garantizar el
"sin fijar" que el docstring del fixture ya prometía, sin importar quién la haya fijado
antes. Ningún cambio en código de producción (`config.py`, `credit_policy.py` intactos).
Verificado con la suite completa: **117 passed, 0 failed, 13 skipped** (antes: 113 passed,
4 failed, 13 skipped). Commit `b3455dc`.

De paso, se detectó y corrigió que el contenido real de **S1.4** (`requirements.txt`/
`requirements-dev.txt` fijados con `==`, `next.js` 16.2.6→16.3.6) y de **S1.7**
(`docs/sql/schema_project_dossier.sql` repoblado, `docs/dev/local-setup.md`, `README.md`)
se había documentado como evidencia en el commit `e4b3347` pero nunca se había comiteado de
verdad — quedaba como cambios sin confirmar en el árbol de trabajo. Comiteados ahora por
separado: `b90ae4a` (S1.4) y `168e9c1` (S1.7). El estado `review` de esas dos tareas en
`feature_list.json` seguía siendo correcto (el trabajo estaba hecho y probado), pero no
estaba realmente en el historial de git hasta esta sesión.

**Sin terminar.** Nada de esto específicamente.

**Lo que hay que saber.** Vale la pena revisar `git log` vs. `git status` después de cerrar
evidencia en `feature_list.json`/`progress.md`: el commit de harness (`e4b3347`) documentaba
trabajo que técnicamente seguía sin comitear. No volvió a pasar aquí, pero es un paso fácil
de saltarse cuando se cierran varias tareas seguidas.

**Siguiente paso concreto.** Ninguna tarea `S` pendiente de Sprint 1 para `FD`. Quedan
abiertos, sin tarea asignada: la actualización de `vitest`/`@vitest/coverage-v8` (2 críticas
+ 6 altas, solo dev, necesita disco local no montado por red para probar con seguridad) y
`db/models.py` desincronizado de `db/Migracion.md` (ver `fix_plan.md`).

**Rama.** `main` (commits locales directos, sin rama, sin push). **Estado.** done.

---

### 2026-09-23 · S1.7 · FD (agente)

**Hecho.** `docs/dev/local-setup.md`: guía completa de arranque (prerrequisitos, backend,
base de datos —con Alembic o SQL a mano—, frontend, verificación y problemas conocidos).
De paso, corregido un hallazgo que arrastraba el proyecto desde la auditoría del
07-09-2026: `docs/sql/schema_project_dossier.sql` estaba vacío (0 bytes) pese a que el
README lo cita como el SQL a aplicar — repoblado con el DDL completo de `Migracion.md`.
README.md actualizado para enlazar la guía nueva y no apuntar a un archivo vacío.

**Sin terminar.** Nada de esta tarea específicamente.

**Lo que hay que saber.** El SQL vacío era exactamente el tipo de cosa que solo se nota al
intentar seguir la guía al pie de la letra — si alguien vuelve a tocar `docs/sql/` o
`Migracion.md`, hay que mantener ambos sincronizados a mano (no hay generación automática
entre ellos).

**Siguiente paso concreto.** Ninguno pendiente de esta tarea.

**Rama.** `main` (commit local directo, sin rama). **Estado.** review.

---

### 2026-09-23 · S1.5 · FD (agente)

**Hecho.** `.github/workflows/ci.yml`: job `backend` (ruff + mypy + pytest --cov) y job
`frontend` (eslint + vitest + next build), en `push`/`pull_request` a `main`, sin
`continue-on-error` en ningún paso. Posible recién ahora porque S1.3 dejó ruff y mypy en 0
errores — antes, la CI habría nacido fallando en cada commit.

**Sin terminar.** No se pudo probar corriendo de verdad en GitHub Actions (sesión local, sin
push, pedido explícito del dueño del repo). Tampoco se configuró la regla de protección de
rama en GitHub (Settings → Branches → Require status checks) que es la que de verdad
impide el merge con el check en rojo — eso requiere push y permisos de administrador en
GitHub, fuera del alcance de esta sesión.

**Lo que hay que saber.** El archivo es válido (verificado con PyYAML) pero nunca se ejecutó
contra runners reales de GitHub — quien haga el primer push debería revisar el primer run
completo por si algo del entorno de CI (versiones exactas de Python/Node en `ubuntu-latest`,
por ejemplo) se comporta distinto al venv local usado en esta sesión.

**Siguiente paso concreto.** Tras el primer push: revisar que el workflow corra en verde, y
configurar la regla de protección de rama en `main`.

**Rama.** `main` (commit local directo, sin rama). **Estado.** review.

---

### 2026-09-23 · S1.4 · FD (agente)

**Hecho.** `backend/requirements.txt` y `requirements-dev.txt` fijados a versiones exactas
(`==`), resueltas y ya probadas en el venv de S0.3. `frontend/package.json`: `next`
16.2.6 → 16.3.6, cerrando las 3 CVEs críticas medidas en S0.3 (confirmado con `npm audit`:
0 vulnerabilidades de `next` después del cambio).

**Sin terminar.** Quedan 2 críticas + 6 altas en `vitest`/`@vitest/coverage-v8` — pero son
dependencias de **testing**, no van a producción. No se forzó el upgrade (a vitest 5,
versión mayor) porque `npm install` sobre esta carpeta —montada en red desde Windows—
falla de forma intermitente (`ENOTEMPTY` al instalar paquetes con binarios nativos, p. ej.
`sharp`), y sin poder correr la suite de tests de forma confiable no había manera segura de
verificar que un cambio mayor de vitest no rompiera algo.

**Lo que hay que saber.** `frontend/package.json` ya usaba versiones exactas para
`next`/`react`/`react-dom`; el resto de dependencias sigue con `^`, pero el proyecto ya
tiene `package-lock.json`, que es el mecanismo real de reproducibilidad de npm — equivalente
a lo que a `requirements.txt` le faltaba (no tenía ningún lock file).

**Siguiente paso concreto.** Desde una máquina con el proyecto en disco local (no en red):
intentar `npm audit fix --force` (sube vitest a 5) y correr `npm test` para confirmar que
nada se rompió antes de aceptar el cambio.

**Rama.** `main` (commit local directo, sin rama). **Estado.** review.

---

### 2026-09-23 · S1.3 · FD (agente)

**Hecho.** `ruff check src/dossier`: 169 → 0 errores (167 automáticos con `--fix`; 23×
`BLE001` marcados `# noqa: BLE001` con una razón corta cada uno — son límites de
resiliencia deliberados: caché Redis que se degrada sin caer, llamadas a SEC/Companies
House/DeepSeek que no deben tumbar el flujo, parsers tolerantes de respuestas OAuth;
ninguno se reescribió a una excepción más específica porque angostarlo sí habría sido un
cambio de comportamiento). `mypy src/dossier`: 45 → 0 errores — se agregó el plugin
`pydantic.mypy` a `pyproject.toml` (resolvió 8 de un tiro: sin él, mypy no entiende los
defaults de `BaseModel` y marca argumentos opcionales como "faltantes"); el resto, firmas
corregidas donde el tipo declarado no reflejaba lo que la función realmente acepta/devuelve,
o `# type: ignore` puntual y justificado donde la librería externa es más estricta de lo
que el uso real requiere. `pytest` antes y después: idéntico, 113/4/13 — sin regresiones.

**Sin terminar.** Los 4 tests en rojo de `test_credit_policy.py` (ya estaban así desde
S0.3) quedan fuera a propósito — corregirlos junto con el análisis estático habría
mezclado análisis estático con cambio funcional en el mismo commit (regla de
`handoff.md` §8).

**Lo que hay que saber.** Quien toque de nuevo alguno de los archivos con `# noqa: BLE001`
o `# type: ignore` debería leer la razón en el propio comentario antes de "limpiarlo" — cada
uno está ahí porque el catch genérico o la imprecisión de tipo es deliberada, no un
descuido.

**Siguiente paso concreto.** Investigar y corregir los 4 tests en rojo de
`test_credit_policy.py` — no tiene tarea `S` asignada todavía en `feature_list.json`.

**Rama.** `main` (commit local directo, sin rama). **Estado.** review.

---

### 2026-09-23 · S1.1 · FD (agente)

**Hecho.** Alembic adoptado (`backend/alembic/`, `alembic.ini`, `env.py`) y migración de línea
base (`versions/a3f1c9e2b7d4_baseline_migracion_md.py`) escrita a mano desde el DDL completo de
`db/Migracion.md`: 19 tablas, 2 vistas, 9 triggers/funciones (incluye el trigger real de cobro de
créditos sobre `dossiers`), más los parches ya vigentes de `db/schema_patches.py` (reutilizando
ese módulo, no duplicando su texto). Probada de punta a punta contra un Postgres temporal
(`pgserver`, venv aislado 3.12 en `/tmp/audit-venv`): `upgrade` crea el esquema completo, un
insert de organización/usuario/dossier confirma que el trigger descuenta créditos y escribe el
ledger correctamente, `downgrade` limpia todo sin dejar tablas. Commit local `f5b3bf4`.

**Sin terminar.** No se generó por `alembic revision --autogenerate` — ver "Lo que hay que saber".
Falta correr la migración contra la base Postgres real del proyecto (no se pudo desde esta sesión:
el puente al dispositivo llega a un contenedor Linux separado, sin acceso al `localhost:5432` de
Windows donde corre la Postgres real). Alguien con acceso directo a esa base debe correr
`alembic upgrade head` y confirmar que coincide con el esquema ya existente (debería ser un no-op
si la base ya tiene el esquema de `Migracion.md` + `schema_patches.py` aplicado a mano).

**Lo que hay que saber.** Los modelos ORM (`db/models.py`) solo declaran ~10 de las 19 tablas
reales y cero triggers — confirmado cruzando con el SQL crudo que `account_service.py` ya hace
contra `credit_ledger`/`dossier_alerts` porque no hay modelo para esas tablas. `alembic/env.py`
usa `Base.metadata` (los modelos) como `target_metadata`. Mientras ese desfase no se corrija, un
futuro `alembic revision --autogenerate` comparará contra metadata incompleta y puede proponer
*borrar* las ~9 tablas y los 9 triggers que el ORM no conoce — **no correr `--autogenerate` a
ciegas**. Hallazgo completo en `fix_plan.md` → Hallazgos sin tarea asignada.

**Siguiente paso concreto.** Asignar tarea para sincronizar `db/models.py` con `Migracion.md`
(agregar las ~9 tablas y mapear los triggers, al menos como comentario/documentación ya que
SQLAlchemy no modela triggers de DB). Después de eso, correr `alembic upgrade head` contra la base
real para confirmarla como no-op.

**Rama.** `main` (commits locales directos, sin rama por tarea — sesión en modo simplificado
pedido por el dueño del repo, sin push). **Estado.** review.

---

### 2026-09-23 · S1.2 · FD (agente)

**Hecho.** `backend/pyproject.toml` con `[tool.ruff]` (select E,F,I,UP,B,BLE,SIM,C4,PIE,RUF;
ignore B008/E501/RUF001-003) y `[tool.mypy]` (`explicit_package_bases`, `check_untyped_defs`,
`ignore_missing_imports`, `warn_unused_ignores`, `warn_redundant_casts`). Corre limpio: `ruff
check` y `mypy src/dossier` ejecutan con esta config sin errores de configuración. Commit local
`664edc4`.

**Sin terminar.** Corregir lo que la config reporta (192 errores de ruff, ~44-45 de mypy) es
**S1.3**, deliberadamente fuera de esta tarea — no mezclar análisis estático con cambio funcional
en el mismo PR (regla del `handoff.md`, riesgo R4 de `fix_plan.md`).

**Lo que hay que saber.** Las cifras de ruff/mypy con esta config ya están medidas y quedaron como
evidencia de **S0.3**, así que S1.3 puede arrancar directo sobre la lista en vez de tener que
remedirla.

**Siguiente paso concreto.** S1.3: corregir los 192 errores de ruff y ~44-45 de mypy, en un commit
separado de cualquier cambio funcional.

**Rama.** `main` (commit local directo, sin rama). **Estado.** review.

---

### 2026-09-23 · S0.3 · FD (agente)

**Hecho.** Línea base de deuda técnica medida en sesión local (venv aislado Python 3.12, ya que
el backend requiere ≥3.11 y el entorno de la sesión traía 3.10): `pytest` → 130 pruebas (113 en
verde, 4 en rojo, 13 en espera), cobertura 33%; `mypy src/dossier` → ~44-45 errores en 14
archivos; `ruff check src/dossier` (con la config de S1.2) → 192 errores; `pip-audit --local` →
sin vulnerabilidades conocidas en las dependencias de Python resueltas; `npm audit` (frontend) →
**3 vulnerabilidades críticas** en `next@16.2.6` (variantes de RCE no autenticado / bypass de
middleware), fix disponible en `next@16.3.6`.

**Sin terminar.** Las cifras de pytest/mypy no cambiaron respecto a la auditoría del 07-09-2026
(misma base de código, sirve de validación cruzada). El hallazgo nuevo es la severidad *crítica*
de las CVEs de Next.js, que la auditoría anterior no había caracterizado así. No se actualizó
Next.js en esta sesión — queda como hallazgo urgente sin tarea propia (ver `fix_plan.md`).

**Lo que hay que saber.** Los 4 tests en rojo y el resto de esta línea base no se investigaron a
fondo (estaba fuera del alcance de "medir", no "arreglar"); quien tome una tarea que dependa de
S0.3 (**S1.4**, **S7.5**) debería revisar cuáles son los 4 antes de asumir que no le tocan.

**Siguiente paso concreto.** Decidir si la actualización de Next.js se hace como parte de **S1.4**
(fijar versiones) o se abre como tarea de seguridad aparte — es más urgente que el resto de esa
tarea.

**Rama.** `main` (commit local directo, sin rama). **Estado.** review.

---

### 2026-09-12 · S3.1 · FO (agente)

**Hecho.** Cliente HTTP del proveedor de noticias (ADR 0004): `backend/src/dossier/news/client.py`
con `search_gdelt_articles` (GDELT DOC 2.0, fuente base, sin API key, ventana de 30 días) y
`search_newsapi_articles` (conector secundario, requiere `NEWS_API_KEY`). Mismo patrón y misma
responsabilidad acotada que `eu_registry/client.py` (S1.8): solo fetch + parseo del JSON crudo,
sin normalizar. Deduplicar entre proveedores es S3.2, filtrar homónimos S3.3, registrar
procedencia completa S3.4 — ninguno de los tres toca este módulo.

9 pruebas nuevas (`tests/test_news_client.py`) siguiendo el estilo de
`test_eu_registry_client.py`: query vacía no llama a la red, error HTTP se traduce a
`ProveedorNoticiasError`, forma de respuesta inesperada es error, y NewsAPI sin
`NEWS_API_KEY` configurada es error explícito (no lista vacía silenciosa). Suite completa:
117 en verde, 13 en espera.

**Sin terminar.** Nada de esta tarea — el alcance es solo el cliente. Sin verificar en vivo
contra la red real (igual que S1.8 con Alemania): las pruebas mockean `requests.get`.

**Lo que hay que saber.**
- El query que exige el ADR (`'"Nombre" AND "Empresa"'`) se compone en el llamador, no en el
  cliente — mismo criterio que `eu_registry` (funciones toman `query: str` ya armado) y que
  `companies_house`/`sec_edgar`. Quien construya S3.2 arma esa cadena antes de llamar.
- `search_newsapi_articles` lanza error si falta `NEWS_API_KEY` en vez de devolver `[]`:
  deliberado, para que S3.2 pueda distinguir "no hay suscripción configurada" de "no hay
  resultados" y decidir si cae solo a GDELT o marca la fuente como no disponible.

**Siguiente paso concreto.** S3.2 (agente de noticias con deduplicación) — combina
`search_gdelt_articles` y `search_newsapi_articles`, dedup por URL/título.

**Rama.** `FO` · **Estado.** review

---

### 2026-09-12 · S4.8 · FO (agente)

**Hecho.** Canal SSE de estados progresivos, `GET
/dossier-generation-jobs/{id}/stream`, siguiendo `specs/proposals/S0.11-protocolo-estados-progresivos.md`
pero sobre la arquitectura real de hoy (worker en background thread, mismo proceso que la API,
sondeo de Postgres cada 2s — no hay Redis pub/sub ni cola de eventos):

- `services/dossier_progress_events.py`: bus de eventos en memoria por job (deque acotado a
  200, dedup por contenido). Documentado como válido para un solo proceso; si el servicio pasa
  a varios dynos hace falta Redis.
- `services/dossier_progress_stream.py`: generador de frames SSE puro, sin FastAPI ni DB
  (`fetch_job` es cualquier callable). Traduce cambios de `status` a `job_status` /
  `job_completed` / `job_failed`, heartbeat cada 15s (CA4), resincronización por
  `Last-Event-ID` sin duplicar el estado ya visto (CA3).
- `api/dossier_stream_routes.py`: reutiliza `get_current_user_and_org` y el mismo aislamiento
  404 (no 403) que `api/dossier_job_routes.py` ya usaba — desviación deliberada del "403" que
  dibujaba la spec, a favor de la convención real del repo (no revela que el job existe en otra
  organización).

**Infra nueva para todo el repo, no solo esta tarea:** arreglé `tests/conftest.py` — el fixture
`sin_red` bloqueaba también el socketpair de loopback que `asyncio` abre internamente en
Windows, así que **ninguna prueba con `TestClient` podía correr en este entorno**, con o sin
esta tarea. Ahora permite loopback (127.0.0.1/::1/localhost) y sigue bloqueando todo lo demás
(prueba propia: `test_sin_red_permite_loopback.py`). Esto habilita
`tests/integration/` (ya prevista en `docs/dev/testing-policy.md §3`, nadie la había usado) con
`TestClient` + `dependency_overrides`, sin necesitar Postgres real.

19 pruebas nuevas: unitarias del bus de eventos y del generador, integración (200 +
`text/event-stream` real), seguridad (401 sin token, 404 por organización ajena, 404 por
usuario ajeno en la misma organización, 404 por job inexistente), y estrés (buffer acotado con
10 000 eventos, 50 jobs publicando concurrentemente sin cruzarse, 20 streams concurrentes hasta
estado terminal). Suite completa: 108 en verde, 13 en espera.

**Sin terminar — brecha documentada, no resuelta.** **CA2 de la spec (`agent_progress`
por-agente, <500ms) no está implementado.** El pipeline LangGraph
(`corporate_dossier_graph.py`, `calendar_event_dossiers.py`, `person_research_pipeline.py`) no
publica progreso interno hoy: solo hay una fila de Postgres con `status` de
queued/running/completed/failed. Dar granularidad por agente exige instrumentar esos nodos para
llamar a `publish_if_changed`, que es un cambio bastante más grande que "el canal en sí" y toca
código que S4.9 ("emitir resultados parciales cuando un agente falla") también va a tocar.
Quien retome S4.9 o S5.1 debería decidir si instrumenta ahí o abre una tarea aparte.

**Lo que hay que saber.**
- **`db.expire_all()` antes de cada `db.get()` en el poll loop es obligatorio.** Sin eso,
  SQLAlchemy devuelve el objeto cacheado en el identity map y el stream nunca ve cambios de
  estado reales — un bug silencioso fácil de no notar porque los tests con `_FakeSession` no lo
  habrían detectado (no usan SQLAlchemy real). Si alguien reescribe `fetch_job`, no quitar esa
  línea.
- **El fix de `sin_red` es genérico, no específico de SSE**: cualquier tarea futura que necesite
  `TestClient` (probablemente S5.x de frontend/backend integrado, o S6.8 pruebas de seguridad
  en CI) ya lo tiene disponible.
- **La numeración de eventos se reinicia si el job llega a estado terminal y luego alguien
  vuelve a publicar para ese mismo `job_id`** (`forget()` limpia el contador). No pasa en la
  práctica porque un job terminal no debería volver a cambiar de estado, pero si algo lo
  reutiliza, un cliente con un `Last-Event-ID` viejo no notará el reinicio (ver
  `test_termina_en_estado_terminal_y_limpia_el_bus`).

**Siguiente paso concreto.** S3.1 (cliente del proveedor de noticias) — última tarea del orden
acordado para esta sesión.

**Rama.** `FO` · **Estado.** review

---

### 2026-09-12 · S4.1 · FO (agente)

**Hecho.** Implementado `DossierExecutivePayload` en
`backend/src/dossier/schemas/dossier_executive_payload.py`, siguiendo la spec ya aprobada
`specs/proposals/S0.9-esquema-json-dossier.md` (no hizo falta escribir spec nueva). Incluye
`SourceCitation`, `RiskAlert`, `ConversationStarter`, `CareerPosition`, `PressMention`, y el
envoltorio de compatibilidad `LegacyMarkdownDossier` + `parse_dossier_payload()` para dossiers
históricos `{"format": "markdown", "body": "..."}`.

**Desviación deliberada del diseño original:** en vez de duplicar el `CorporateRegistryRecord`
que la spec dibujaba, los registros corporativos reutilizan `RegistroCorporativo` (S1.9)
envuelto en `CorporateRecordCitation` (agrega la cita de origen obligatoria que CA3 exige;
`RegistroCorporativo` deja esa cita opcional a propósito porque también se usa suelto en otros
contextos, como el cliente `eu_registry`).

9 pruebas nuevas cubren las cuatro CA de la spec: payload completo válido, campos requeridos
faltantes (`executive_summary`, `conversation_starters`), tope de 3 rompehielos, 0 alertas
válido, `PressMention`/`CorporateRecordCitation` sin `source` fallan, y el dossier histórico se
normaliza sin error. Suite completa: 85 en verde, 13 en espera.

**Sin terminar.** Nada de S4.1. **No** se tocó el prompt de síntesis (S4.2) ni las columnas de
Postgres (S4.5): el pipeline sigue guardando `{"format": "markdown", ...}` como antes, este
esquema todavía no se usa en ningún lado del código de producción.

**Lo que hay que saber.**
- **Pydantic v2, no v1.** La spec S0.9 estaba escrita con `regex=` y `max_items=` (sintaxis v1);
  el proyecto ya usa Pydantic 2.13. Se tradujo a `pattern=` y `max_length=`. Si alguien copia
  código de esa spec literalmente para otra tarea, va a fallar igual.
- **`parse_dossier_payload()` es solo el detector de formato**, no un migrador. No convierte
  Markdown a la estructura nueva; eso seguiría siendo trabajo de S4.4 ("compatibilidad de
  lectura para dossiers históricos") si hace falta más que "no explotar al leerlo".

**Siguiente paso concreto.** S4.8 (canal de estados progresivos SSE).

**Rama.** `FO` · **Estado.** review

---

### 2026-09-12 · S1.8 · FO (agente)

**Hecho.** Cliente HTTP europeo en `backend/src/dossier/eu_registry/client.py`, mismo patrón
que `companies_house/cli.py` y `sec_edgar/cli.py`: solo fetch + parseo del JSON crudo, sin
normalizar a `RegistroCorporativo` (eso es S2.1/S2.3).

- `search_france_companies()` contra `recherche-entreprises.api.gouv.fr/search` — endpoint y
  forma de respuesta verificados en vivo (`results`, `siren`, `nom_complet`, `siege`,
  `dirigeants`, `etat_administratif`, `nature_juridique`, `date_creation`).
- `search_germany_companies()` contra la API SQL estilo Datasette de OffeneRegister.de.
- 7 pruebas nuevas (`tests/test_eu_registry_client.py`) con `respuesta_fija` + `monkeypatch`
  sobre `requests.get`, sin red real. Suite completa: 76 en verde, 13 en espera.

**Sin terminar.** Nada de S1.8 en sí, pero **Alemania queda con un riesgo documentado, no
resuelto**: el esquema exacto (nombre de base de datos/tabla, columnas) no se pudo verificar
en vivo porque `db.offeneregister.de` devolvió 502 al intentarlo. El cliente usa la convención
estándar de Datasette (`/<db>/<tabla>.json?columna__contains=...`) con nombres configurables
por `EU_REGISTRY_DE_API_BASE` / `_DATABASE` / `_TABLE`, pero son un valor por defecto
razonable, no un hecho confirmado.

**Lo que hay que saber.**
- **Quien retome S2.1 (agente europeo) debe reverificar Alemania antes de escribir el
  adaptador.** Si `db.offeneregister.de` sigue caído o cambió de esquema, hay alternativas
  comerciales (OpenRegister, handelsregister.ai) que ADR 0003 descartó por costo — repasar esa
  decisión si el Open Data gratuito ya no es viable.
- **Francia sí está verificado y es estable**: sin API key, JSON limpio, campos ya mapeados en
  la tabla de `specs/proposals/S1.9-modelo-comun-registro-corporativo.md`.

**Siguiente paso concreto.** S4.1 (esquema JSON estricto del dossier como modelos Pydantic).

**Rama.** `FO` · **Estado.** review

---

### 2026-09-12 · S1.9 · FO (agente)

**Hecho.** Definido `RegistroCorporativo` (`backend/src/dossier/schemas/corporate_registry.py`):
el esquema unificado que ADR 0003 nombraba pero no formalizaba. Submodelos
`DomicilioRegistrado`, `Directivo`, `Presentacion`; enum `JurisdiccionRegistro` con las cuatro
jurisdicciones del alcance firme (`uk`, `us`, `fr`, `de`); campo `datos_brutos` como escape
hatch para no perder información de la fuente mientras S2.3 decide qué migrar a campos
estructurados.

Especificación previa (era un contrato nuevo, exige SDD):
`specs/proposals/S1.9-modelo-comun-registro-corporativo.md`, con una tabla de mapeo de campos
por fuente (Companies House, SEC EDGAR, Recherche d'entreprises, Handelsregister) para que
S2.1 y S2.3 no repitan la investigación.

Prueba nueva `backend/tests/test_corporate_registry_schema.py` (9 casos): campos mínimos,
las cuatro jurisdicciones válidas, jurisdicción inválida rechazada, submodelos con forma real
de la fuente francesa (`dirigeants`) y de Companies House (filing history), serialización a
JSON. Suite completa: 69 en verde (60 previas + 9), sin regresiones.

**Sin terminar.** Nada de S1.9. Los adaptadores que conviertan las respuestas reales de cada
API a este modelo NO están hechos — es explícitamente S2.1 (agente europeo) y S2.3 (adaptar UK
y US). `corporate_dossier_graph.py` sigue usando Markdown crudo, no este modelo; conectarlo es
S2.2/S2.3, no S1.9.

**Lo que hay que saber.**
- **`companies_house/cli.py` no trae directores hoy.** Solo expone perfil + filing history; el
  endpoint de officers de Companies House no se consulta en ningún lado del pipeline actual.
  Si S2.3 quiere poblar `directivos` para UK, es un endpoint nuevo, no un campo que ya viene.
- **Francia y Alemania sí traen directivos "gratis".** ADR 0003 dice que la API francesa
  entrega `dirigeants` y que Handelsregister entrega directores en su JSON — por eso
  `directivos` existe en el modelo común desde ahora, aunque UK/US lo dejen vacío por ahora.
- **`fecha_constitucion` va a variar mucho en precisión por fuente** (CH: fecha exacta; Alemania:
  "variable por Land" según ADR 0003). Se dejó como `str | None`, no `date`, a propósito: forzar
  un tipo `date` habría exigido decidir ahora cómo tratar fechas parciales, que no es esta tarea.

**Siguiente paso concreto.** S1.8 (cliente HTTP de la fuente europea) — usa la tabla de mapeo
de esta spec para Francia (columna ya lista); Alemania puede quedar con menos campos si su API
entrega menos estructura, el modelo ya lo permite todo opcional salvo los cuatro campos base.

**Rama.** `FO` · **Estado.** review

---

### 2026-09-12 · S1.6 · FO (agente)

**Hecho.** Ejecutada la acción pendiente de ADR 0001 (línea LLM canónica).

- Eliminado `backend/src/dossier/gemini/` (shim); sus cinco importadores
  (`companies_house/cli.py`, `sec_edgar/cli.py`, `calendar_event_dossiers.py`,
  `person_research_pipeline.py`, `corporate_registry_context.py`) ahora leen directo de
  `dossier.llm.common` y `dossier.llm.document_analyze`.
- Eliminados `services/openai_dossier.py`, `DOSSIER_LEGACY_OPENAI` y la ruta
  `GET /generar-dossier`.
- Eliminados `security/legacy_routes.py`, `DOSSIER_ENABLE_LEGACY_OPEN_ROUTES` y
  `api/google_calendar.py` completo: su única ruta (`POST
  /calendario/generar-dossier-google`, sin JWT) no tenía llamador en el frontend ni en
  pruebas; el flujo real es `/calendario/generar-dossiers-google` (con JWT, ya existente).
- Renombrado `gemini_analysis_markdown` → `llm_analysis_markdown` (backend y frontend) y
  `_node_synthesize_gemini`/`"synthesize_gemini"` → `_node_synthesize_llm`/`"synthesize_llm"`
  en el grafo corporativo y en los reportes de agentes activados/fallidos.
- Prueba nueva `backend/tests/test_llm_canonical_line.py`: escanea `backend/src` y
  `frontend/src` en busca de los tokens retirados y verifica que las rutas/módulos legados
  no existan. Roja antes del cambio (13 fallos), verde después.
- Borrado `backend/tests/test_legacy_routes.py` (probaba el módulo que este commit elimina).

**Sin terminar.** Nada de S1.6. Verificado con la suite completa: 60 en verde, 13 en espera
(sin regresiones frente a las 49+13 previas). `qa.py` sin bloqueos, dos avisos preexistentes
(falta prueba en `tests/security/` para el cambio en `security/` —la baja de
`legacy_routes.py` sí tiene su prueba, pero `qa.py` no distingue eliminación de omisión— y
`frontend/node_modules` no instalado en este worktree).

**Lo que hay que saber.**
- **Este worktree no traía `backend/.venv`.** Lo creé desde cero
  (`python -m venv .venv` + `pip install -r requirements.txt -r requirements-dev.txt`) y
  faltaba `msal` en el entorno hasta instalarlo. Cada worktree nuevo necesita este paso;
  no es compartido entre `mako`, `main` y el checkout original.
- **No toqué las variables `GEMINI_*` de análisis de documentos** (`GEMINI_API_KEY`,
  `GEMINI_MODEL`, `gemini_google_search_used`, `PersonResearchSource.gemini_web`, el
  `"gemini"` en `data_sources_used`, las funciones `_gemini_*` de
  `corporate_registry_context.py`). Son la integración real con la API de Gemini para
  análisis de documentos/búsqueda web, una capacidad distinta de la línea de síntesis de
  texto que ADR 0001 reemplazó por DeepSeek. Confundirlas sería revertir una decisión que
  nadie tomó.
- **La rama `FO` ya traía Sprint 0 resuelto** (commits `a3c45b6` y `b27d168`): 13 de 14
  tareas en `done`, seis ADRs y las especificaciones de S0.9/S0.11/S0.12 ya escritas. Quien
  retome S1.8, S1.9, S4.1 o S4.8 puede partir de esos documentos en
  `docs/architecture/decisions/` y `specs/proposals/` sin rehacerlos.

**Siguiente paso concreto.** S1.9 (modelo común de registro corporativo UK/US/EU), después
S1.8 (cliente HTTP europeo) — en ese orden porque S1.8 va a usar el modelo que define S1.9.

**Rama.** `FO` · **Estado.** review

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
