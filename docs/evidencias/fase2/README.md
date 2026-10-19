# Evidencias de la Fase 2

Respuesta a la evaluación del informe de la Fase 2 (nota 4,6). Observación del docente:

> «Incorporar en el informe capturas que demuestren la integración continua, las migraciones, el calendario
> visual y los indicadores conectados, porque sin ello no es posible verificar el avance técnico ni el
> almacenamiento de datos.»

La rúbrica pide además «evidencias claras dentro del repositorio del aporte de cada uno de los integrantes»,
guardadas en Git. Esta carpeta reúne esas evidencias.

**Reglas que siguen todas:** son salidas reales de comandos ejecutados el **2026-10-19** sobre el commit
**`9f6c69250fbff63b7375d965d5692cf1c494ff30`** (merge del PR #24 en `main`), sin retoques. Cada evidencia es
un par `.txt` + `.png`: el `.txt` lleva en su encabezado la fecha con zona horaria, el commit, el directorio,
el comando exacto y el código de salida, seguido de la salida literal. El `.png` es esa misma salida
renderizada (comando como encabezado; SHA y fecha al pie). Cuando el PNG muestra un extracto de una salida
larga, lo dice en amarillo y el `.txt` conserva la salida completa. Las contraseñas aparecen como `***`, los
hashes se truncan a 12 caracteres y todos los datos de ejemplo son ficticios. Las corridas que no salieron
limpias también se guardan, con su explicación.

## Índice

| Tema | Evidencia | Qué demuestra | Atiende | Cómo reproducir |
|---|---|---|---|---|
| **CI/CD** | [ci-cd/](ci-cd/README.md) | Dos workflows en GitHub Actions: CI bloqueante (ruff, mypy, pytest, eslint, Vitest, build) y publicación de imágenes en ghcr.io con redespliegue en Dokploy. Últimas 30 ejecuciones: 23 en verde, 6 canceladas por diseño (`cancel-in-progress`) y 1 falla de red explicada. Diagrama del pipeline. | Observación: **integración continua** | `gh run list`, `gh run view <id> --verbose`, `_herramientas/tabla_ejecuciones.py` |
| **Migraciones** | [migraciones/](migraciones/README.md) | `alembic upgrade head` sobre una base vacía aplica las 3 revisiones y deja 22 tablas, 2 vistas, 9 triggers y 3 funciones propias. Diagrama entidad-relación del ORM en Mermaid y PNG. | Observación: **migraciones**; avance técnico | `alembic heads/history/current/upgrade head`, `psql \dt \d+`, `_herramientas/er.py` |
| **Almacenamiento** | [almacenamiento/](almacenamiento/README.md) | 109 pruebas que necesitan PostgreSQL pasan contra una base real (768 passed con base vs. 659 sin ella). Jobs reales con proveedores simulados y registro por la API dejan filas en organizaciones, usuarios (bcrypt), jobs con progreso, dossiers con `dossier_data` JSONB y el ledger de créditos. | Observación: **almacenamiento de datos** | `TEST_DATABASE_URL=… pytest -v`, `generar_fixtures_progreso.py`, `registrar_usuario_ficticio.py`, `consultas_almacenamiento.sql` |
| **Pruebas** | [pruebas/](pruebas/README.md) | Backend: 768 passed, 12 skipped, cobertura 63 %. Frontend: 522 pruebas en verde, cobertura de sentencias 36,77 %. Conteo por categoría: 486 unitarias, 166 de integración, 67 de seguridad y 61 de estrés. | Avance técnico; política de pruebas | `pytest --cov=dossier`, `npm test`, `npm run test:cov`, `_herramientas/categorias_pruebas.py` |
| **Calidad** | [calidad/](calidad/README.md) | ruff 0, mypy 0 (124 archivos), eslint 0 errores y 1 advertencia, `tsc` 0. Auditorías: `pip-audit` 2 avisos en `pyjwt`; `npm audit` 6 (5 altas), todas con corrección disponible. | Definición de Terminado (análisis estático); avance técnico | `ruff check`, `mypy`, `npm run lint`, `npx tsc --noEmit`, `pip-audit`, `npm audit --omit=dev` |
| **Contribuciones** | [contribuciones/](contribuciones/README.md) | Commits, líneas, PR y tareas del harness por integrante, con los alias de git unificados, un gráfico de barras y los sesgos de cada cifra explicados (commit raíz heredado, merges, asistencia de agentes, rama `docmac`). | Rúbrica: **aporte de cada integrante** | `git shortlog -sne --all`, `_herramientas/contribuciones.py`, `gh pr list` |
| **Interfaz** | [ui/](ui/README.md) | Capturas del calendario visual y de los indicadores conectados del dashboard (las prepara otra sesión de trabajo en `ui/`). | Observación: **calendario visual** e **indicadores conectados** | ver `ui/README.md` |

## Cifras clave

| Medida | Valor |
|---|---|
| Revisiones de Alembic aplicadas sobre base vacía | 3 (`a3f1c9e2b7d4` → `b7e2d4f1a9c3` → `c4d8a2f6b1e9`) |
| Tablas / vistas / triggers creados | 22 (+ `alembic_version`) / 2 / 9 |
| Pruebas backend con PostgreSQL | 768 passed, 12 skipped, 0 failed (109 de ellas requieren la base) |
| Cobertura backend | 63 % |
| Pruebas frontend | 522 passed (40 archivos); cobertura de sentencias 36,77 % |
| CI, últimas 30 ejecuciones | 23 success · 6 cancelled · 1 failure (timeout de red en ghcr.io) |
| ruff / mypy / eslint / tsc | 0 / 0 / 0 errores (1 advertencia) / 0 |
| pip-audit / npm audit | 2 (pyjwt) / 6 (5 altas, 1 moderada) |
| Commits sin merges en `main` (FO / DG / FD) | 64 / 55 / 12 |

## Pendientes

- **Capturas de la interfaz web de GitHub Actions.** El repositorio es privado y la página de Actions
  responde «Page not found» sin sesión; no se ingresaron credenciales. Las URLs exactas están en
  [ci-cd/README.md](ci-cd/README.md#capturas-de-github-actions-pendientes-de-tomar-cuando-el-repo-sea-público).
- **Redespliegue automático en Dokploy.** El job existe y corre, pero faltan los secretos `DOKPLOY_*`
  en el repositorio: hoy publica las imágenes y avisa que no redespliega.
- **Postgres en la CI.** Las 109 pruebas con base se omiten en Actions; aquí se corrieron localmente.

## Herramientas

[`_herramientas/`](_herramientas/) guarda los scripts usados para generar estas evidencias, para que
cualquiera las pueda repetir:

| Script | Uso |
|---|---|
| `ev.py` | Ejecuta un comando, guarda la salida literal en `.txt` con encabezado (fecha, SHA, comando, código de salida) y la renderiza a `.png` con Chrome sin interfaz. |
| `er.py` · `er_html.py` | Diagrama ER en Mermaid desde `Base.metadata`, y su página para capturarlo. |
| `comparar_pytest.py` | Compara dos salidas de `pytest -v` (sin y con Postgres). |
| `registrar_usuario_ficticio.py` | Registra cuentas ficticias por `POST /auth/register` en una base `…test…`. |
| `consultas_almacenamiento.sql` | Consultas sobre las tablas clave, con hashes truncados. |
| `categorias_pruebas.py` | Conteo de pruebas por categoría y carpeta. |
| `tabla_ejecuciones.py` | Tabla de ejecuciones de GitHub Actions con duración por jobs. |
| `contribuciones.py` · `grafico_contribuciones.py` | Aporte por integrante y su gráfico. |

Variables usadas: `SHA` (commit evaluado) y `W` (raíz del repositorio) para el encabezado de `ev.py`;
`DATABASE_URL` / `TEST_DATABASE_URL` hacia una base cuyo nombre contenga `test`. Nunca se usó la base de
desarrollo.
