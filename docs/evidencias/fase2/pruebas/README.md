# Evidencia: pruebas automatizadas y cobertura

Ejecutado el 2026-10-19 sobre el commit `9f6c69250fbff63b7375d965d5692cf1c494ff30`. Backend con el
entorno `backend/.venv` (Python 3.12, pytest con `pytest-cov`) y `TEST_DATABASE_URL` apuntando a la base
local `dossier_evid_test`. Frontend con Vitest 2.1.9 y Node 26.10.0 (`NODE_OPTIONS=--no-experimental-webstorage`).
El `node_modules` del frontend es una *junction* al del worktree `mako`, con las mismas versiones de
`vitest` y `next` que declara `frontend/package.json`.

## Resultados

| Evidencia | Resultado |
|---|---|
| [01-pytest-cobertura.txt](01-pytest-cobertura.txt) · [png](01-pytest-cobertura.png) | **768 passed, 12 skipped** en 211 s. Cobertura de `dossier`: **63 %** (10.040 sentencias, 3.707 sin cubrir). Incluye las 10 pruebas más lentas (`--durations=10`). |
| [02-vitest.txt](02-vitest.txt) · [png](02-vitest.png) | `npm test`, igual que la CI: **40 archivos, 522 pruebas, todas en verde**, en 44,5 s. |
| [03-vitest-cobertura.txt](03-vitest-cobertura.txt) · [png](03-vitest-cobertura.png) | `npm run test:cov -- --testTimeout=30000`: 522 en verde. Cobertura v8 de `src/`: **36,77 % sentencias, 78,62 % ramas, 62,5 % funciones**. |
| [04-categorias.txt](04-categorias.txt) · [png](04-categorias.png) | Conteo por categoría y por carpeta, calculado desde las salidas reales de pytest `-v` y Vitest. |

### Pruebas por categoría (backend)

La categoría la asigna `backend/tests/conftest.py` según la carpeta; nadie la escribe a mano.

| Categoría | Carpeta | Archivos | Pruebas | Pasan | Omitidas |
|---|---|---:|---:|---:|---:|
| Unitaria | `tests/` | 49 | 486 | 486 | 0 |
| Integración | `tests/integration/` | 22 | 166 | 166 | 0 |
| Seguridad | `tests/security/` | 12 | 67 | 57 | 10 |
| Estrés | `tests/stress/` | 12 | 61 | 59 | 2 |
| **Total** | | **95** | **780** | **768** | **12** |

Las 12 omitidas esperan su tarea del plan (S2.4, S3.9, S4.10, S5.8, S6.5, S6.6, S6.7); el motivo está en el
resumen `SKIPPED` de la salida. En el frontend Vitest no distingue categorías: 522 pruebas en 40 archivos,
la mayoría en `src/lib` (247) y en componentes del dashboard (65).

## Corridas que no salieron limpias, y por qué

Se guardan también, para que se vea lo que pasó y no solo la corrida buena:

- [01b-pytest-cobertura-fallo-intermitente.txt](01b-pytest-cobertura-fallo-intermitente.txt) · [png](01b-pytest-cobertura-fallo-intermitente.png):
  **1 failed, 767 passed**. Falló `tests/stress/test_progress_estres.py::test_un_proveedor_lento_no_retrasa_los_eventos_de_los_demas`,
  que exige que un evento llegue en menos de 0,3 s y midió 0,336 s. En ese momento corrían en paralelo
  `mypy` y `pip-audit` en la misma máquina. Repetida sin carga paralela (evidencia 01), pasa. Es una prueba de
  estrés sensible a la carga del equipo, no un error de lógica, pero conviene registrarla como prueba frágil.
- [01c-pytest-cobertura-primera-corrida.txt](01c-pytest-cobertura-primera-corrida.txt) · [png](01c-pytest-cobertura-primera-corrida.png):
  768 passed, misma cobertura (63 %), pero pytest informa 6 h 33 min de reloj. No se determinó la causa
  (la sesión del agente que la lanzó se interrumpió mientras corría; es posible que el proceso quedara en
  espera o el equipo suspendido). Se conserva por transparencia, pero no se usa como medida de duración.
- [03b-vitest-cobertura-timeout-5s.txt](03b-vitest-cobertura-timeout-5s.txt) · [png](03b-vitest-cobertura-timeout-5s.png):
  `npm run test:cov` con el límite por omisión de 5 s: **13 failed, 509 passed**. Las fallas son
  `Test timed out in 5000ms` en `MeetingsCalendar.test.tsx` y `person-research/page.test.tsx`, más fallas
  derivadas en cadena. La instrumentación de cobertura v8 hace más lentas esas pruebas en Windows. Sin
  cobertura (02) y con 30 s de límite (03) pasan las 522. La CI corre `npm test` sin cobertura.

## Cómo reproducir

```bash
cd backend
TEST_DATABASE_URL=postgresql://postgres:<clave>@localhost:5432/dossier_evid_test \
  python -m pytest -q -p no:cacheprovider --cov=dossier --cov-report=term --durations=10
cd ../frontend
NODE_OPTIONS=--no-experimental-webstorage npm test
NODE_OPTIONS=--no-experimental-webstorage npm run test:cov -- --testTimeout=30000
cd ../docs/evidencias/fase2
python _herramientas/categorias_pruebas.py almacenamiento/02-pytest-con-postgres.txt pruebas/02-vitest.txt
```
