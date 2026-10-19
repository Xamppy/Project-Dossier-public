# Evidencia: GitHub del repositorio público

El repositorio de trabajo es privado, y sin sesión GitHub responde «Page not found». Estas capturas son de
la copia pública [`Xamppy/Project-Dossier-public`](https://github.com/Xamppy/Project-Dossier-public), que
se sincroniza desde `main` del privado con historial filtrado (el procedimiento se documenta en
`docs/dev/repo-publico.md`, PR #33). Muestran lo que ve cualquier evaluador sin
cuenta.

**Cómo se tomaron:** el **2026-10-19**, con Chrome DevTools (MCP) en un contexto aislado y **sin sesión
iniciada**, ventana de 1440×900. No se hizo clic en nada que cambiara el repositorio. Las capturas 01, 07 y
08 son de página completa; las demás, de la parte visible. La copia pública estaba en `23d51ae`, que
corresponde al merge del PR #32 (`cbc99c5` en el privado). Los SHA difieren porque el filtro reescribe el
historial.

| Archivo | Qué muestra | URL | Fecha | Criterio que respalda |
|---|---|---|---|---|
| [01-repositorio-publico.png](01-repositorio-publico.png) | Portada del repositorio: árbol de carpetas, 165 commits, el último con check verde, y el README completo | https://github.com/Xamppy/Project-Dossier-public | 2026-10-19 | Documentación; uso de Git |
| [02-actions.png](02-actions.png) | Lista de ejecuciones de Actions, todas en verde. El workflow «Imágenes Docker» figura como *Disabled* en la copia | https://github.com/Xamppy/Project-Dossier-public/actions | 2026-10-19 | CI |
| [03-ci-ejecucion-exitosa.png](03-ci-ejecucion-exitosa.png) | Detalle de la CI #3 sobre `main` (push de `23d51ae`): estado *Success*, jobs Backend (pytest, ruff, mypy) y Frontend (eslint, vitest, build) en verde, 1m 15s | https://github.com/Xamppy/Project-Dossier-public/actions/runs/39343754874 | 2026-10-19 | CI |
| [03b-ci-job-backend-pasos.png](03b-ci-job-backend-pasos.png) | Job Backend expandido con sus pasos en verde: instalar Python y dependencias, ruff, mypy, pytest con cobertura | https://github.com/Xamppy/Project-Dossier-public/actions/runs/39343754874/job/118371292764 | 2026-10-19 | CI |
| [04-migraciones-alembic.png](04-migraciones-alembic.png) | Las 3 revisiones de Alembic en `backend/alembic/versions`, con el commit que agregó cada una | https://github.com/Xamppy/Project-Dossier-public/tree/main/backend/alembic/versions | 2026-10-19 | Migraciones |
| [05-evidencias-fase2.png](05-evidencias-fase2.png) | La carpeta `docs/evidencias/fase2` publicada: CI/CD, migraciones, almacenamiento, pruebas, calidad, contribuciones e interfaz | https://github.com/Xamppy/Project-Dossier-public/tree/main/docs/evidencias/fase2 | 2026-10-19 | Documentación |
| [06-commits.png](06-commits.png) | Historial de `main` con commits convencionales (`docs(evidencias)`, `chore(privacidad)`, `chore(harness)`) y merges de PR | https://github.com/Xamppy/Project-Dossier-public/commits/main | 2026-10-19 | Uso de Git |
| [07-contribuidores.png](07-contribuidores.png) | Gráfico de contribuidores de los últimos 3 meses, sin merges: Xamppy 67 commits, darygod 55, fedocmac 12 (ver nota) | https://github.com/Xamppy/Project-Dossier-public/graphs/contributors | 2026-10-19 | Aporte por integrante |
| [08-workflow-ci.png](08-workflow-ci.png) | El archivo `.github/workflows/ci.yml` completo: disparadores en push y PR a `main`, y los pasos de los dos jobs | https://github.com/Xamppy/Project-Dossier-public/blob/main/.github/workflows/ci.yml | 2026-10-19 | CI |
| [09-adr.png](09-adr.png) | Los 9 registros de decisiones de arquitectura (ADR 0001 a 0009) en `docs/architecture/decisions` | https://github.com/Xamppy/Project-Dossier-public/tree/main/docs/architecture/decisions | 2026-10-19 | Documentación |

## Notas

- **Contribuidores.** GitHub muestra también a `claude` (123 commits) porque cuenta como contribuidor a
  cada coautor declarado con `Co-Authored-By`. Esos commits ya figuran a nombre de un integrante; no es una
  quinta persona. La correspondencia es Xamppy = FO, darygod = DG y fedocmac = FD. Los 67 commits de FO
  son los 64 de [contribuciones/](../contribuciones/README.md) más los 3 de los PR #30, #31 y #32, que
  entraron después de ese cálculo.
- **Registros de las ejecuciones.** Sin sesión, GitHub muestra los jobs y sus pasos, pero no el texto de
  los registros («Sign in to view logs»). El texto completo de una ejecución equivalente del privado está
  en [ci-cd/](../ci-cd/README.md).
- **Anotaciones de la CI #3.** Una advertencia de eslint en `frontend/src/app/register/page.test.tsx`
  (`'t' is assigned a value but never used`) y el aviso de GitHub sobre la migración de `ubuntu-latest`.
  Ninguna hace fallar la ejecución.
