# Tarea A3 — Consolidación de la base técnica (Sprint 1)

Responsable: FD. Tareas: S0.3, S1.1, S1.2, S1.3, S1.4, S1.5, S1.7.
Estado: done (local, sin push).

## S0.3 — Línea base de deuda técnica

Se corrió por primera vez la suite completa (antes no se sabía si pasaba: faltaba el venv).
Resultado inicial: 113 passed, 4 failed, 13 skipped. Cobertura y `pip-audit`/`npm audit`
medidos y dejados como línea base en `fix_plan.md`.

## S1.1 — Alembic (migraciones versionadas)

**Problema.** El esquema se aplicaba con `db/schema_patches.py` (SQL crudo, sin versionar).

**Solución.** `backend/alembic/versions/a3f1c9e2b7d4_baseline_migracion_md.py`: migración de
línea base con el DDL completo de `db/Migracion.md` (19 tablas, vistas, triggers) más los
parches de `schema_patches.py` reutilizados. Probada primero contra un Postgres desechable
(`pgserver`) y confirmada el 23-09-2026 contra Postgres real: `alembic upgrade head` corrió
sin errores sobre una base `dossier` vacía.

**Pendiente, sin tarea asignada.** `db/models.py` (ORM) solo declara ~10 de las 19 tablas
reales — no usar `alembic revision --autogenerate` sin revisar el diff a mano, podría
proponer borrar tablas/triggers reales que el ORM no conoce.

## S1.2 — Análisis estático configurado

`pyproject.toml` con ruff y mypy configurados (incluye plugin `pydantic.mypy`, necesario para
que mypy entienda los modelos Pydantic sin falsos positivos).

## S1.3 — Errores de análisis estático corregidos

**Backend.** 169 errores de ruff y 45 de mypy corregidos en 48 archivos, sin ningún cambio
funcional (verificado con la suite antes/después: mismo resultado).

*Método.* 167 de los 169 errores de ruff se corrigieron con `ruff check . --fix`
(automático — reordenar imports, formateo, simplificaciones mecánicas). Los 2 restantes y
los 45 de mypy no son auto-corregibles: se revisaron uno por uno, comparando el tipo
declarado contra lo que la función realmente recibe/devuelve, y se corrigieron a mano
(23 excepciones genéricas deliberadas quedaron con `# noqa: BLE001` y su razón puntual, el
resto se reescribió).

**Frontend (corrección posterior, 23-09-2026).** El commit original de S1.3 solo tocó el
backend; los 21 errores y 6 avisos de `npm run lint` en el frontend (medidos desde la
auditoría del 07-09-2026, con nota explícita de que se corregían en S1.3) habían quedado sin
tocar. Corregido en 17 archivos:
- 21 errores `react-hooks/set-state-in-effect`: documentados con `eslint-disable-next-line` y
  razón puntual por línea (mismo criterio que los BLE001 del backend) — patrones legítimos
  repetidos en el codebase, sin suite E2E para verificar un refactor real con seguridad.
- 2 `no-unused-vars` reales, eliminados (variable/función muerta en un script, y una función
  `handleRegeneratePerson` sin conectar a ningún botón).
- 2 `exhaustive-deps`: uno con fix real (agregar `t` a las dependencias — corrige un mensaje
  de error que podía quedar en el idioma anterior), otro con disable justificado (lista de
  dependencias parcial a propósito).
- 2 `jsx-a11y/alt-text`: falso positivo por `alt` pasado vía spread; se agregó explícito.

*Método.* No se usó `npm run lint -- --fix`: ninguno de los 21 errores principales es
auto-corregible (eslint no puede reescribir la lógica de un `useEffect`), y los pocos avisos
que sí lo eran (`no-unused-vars`, `alt-text`) se corrigieron a mano igual, archivo por
archivo, para poder dejar la razón de cada decisión por escrito en el propio código.

Verificado el 23-09-2026: `npm run lint` 0/0, `npm test` 14/14, `npm run build` 0/0
(compiló, pasó TypeScript, generó las 14 rutas sin errores). El primer intento de build reveló
un problema aparte: `node_modules` había quedado con una instalación a medias (`@next/swc` en
16.2.6 mientras `next` ya estaba en 16.3.6 por S1.4), mismo tipo de corrupción de
`node_modules` en carpeta de red ya visto antes con `sharp-win32-x64`. Se resolvió con
`Remove-Item -Recurse -Force node_modules` + `npm install` limpio. Detalle completo en
`.harness/progress.md`, entrada del 23-09-2026.

## S1.4 — Dependencias fijadas y vulnerabilidades cerradas

`requirements.txt`/`requirements-dev.txt` pasan de `>=` a `==` (build reproducible).
`next.js` 16.2.6 → 16.3.6, cierra 3 CVEs críticas (RCE no autenticado, bypass de middleware
de autorización).

**Corrección posterior (23-09-2026).** Faltaba `alembic` en `requirements-dev.txt` pese a que
S1.1 ya lo usaba — se agregó (`alembic==1.20.0`).

## S1.5 — Integración continua

`.github/workflows/ci.yml`: job backend (ruff + mypy + pytest --cov) y job frontend (eslint +
vitest + build), sin `continue-on-error`. No se pudo validar corriendo en GitHub Actions real
(requiere push, fuera de alcance de una sesión local). Falta además, aparte del repo,
configurar en GitHub branch protection para que bloquee el merge en rojo.

## S1.7 — Documentación de arranque local

`docs/dev/local-setup.md` (guía completa). Se corrigió de paso `docs/sql/schema_project_dossier.sql`,
que estaba vacío (0 bytes) pese a que el README lo citaba como el SQL a aplicar.

## Hallazgo resuelto fuera de tarea S: 4 pruebas rojas en `test_credit_policy.py`

**Problema.** `test_credit_policy.py` pasaba solo pero fallaba dentro de la suite completa.

**Causa raíz.** `dossier/api/app.py` llama `load_env()` a nivel de módulo. Algunas pruebas
(`tests/integration/test_dossier_stream_route.py`, `tests/security/test_dossier_stream_seguridad.py`)
importan ese módulo durante la *recolección* de pytest, antes de que corriera el fixture
`autouse` de `conftest.py`. Eso cargaba el `.env` real del desarrollador
(`DOSSIER_CHARGE_CREDITS=false`, legítimo para demos) directo a `os.environ`, y quedaba ahí
para el resto de la sesión de pytest.

**Solución.** `tests/conftest.py`: `os.environ.pop("DOSSIER_CHARGE_CREDITS", None)` al inicio
del fixture `entorno_de_pruebas`, para garantizar el "sin fijar" que el docstring ya prometía
sin importar quién la haya fijado antes.

**Verificación.** 117 passed, 0 failed, 13 skipped (antes: 113/4/13). Sin cambios de
comportamiento en producción.

## Estado del árbol de trabajo

Todo en commits locales sobre `main`, sin push a `origin`. Detalle commit por commit en
`.harness/progress.md`. Pendiente de que el responsable (FD) haga push a su propia rama
cuando lo decida.
