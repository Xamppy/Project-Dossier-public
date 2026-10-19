# Evidencia: análisis estático y auditoría de dependencias

Ejecutado el 2026-10-19 sobre el commit `9f6c69250fbff63b7375d965d5692cf1c494ff30`. Los comandos de
backend son los mismos que corre la CI (`.github/workflows/ci.yml`).

| Herramienta | Evidencia | Conteo | Interpretación |
|---|---|---|---|
| `ruff check src/dossier` (0.16.8) | [01-ruff.txt](01-ruff.txt) · [png](01-ruff.png) | **0 problemas** («All checks passed!») | El backend cumple las reglas de `backend/pyproject.toml`; en S1.3 se partió de 169 errores. |
| `mypy src/dossier` (2.3.1) | [02-mypy.txt](02-mypy.txt) · [png](02-mypy.png) | **0 errores en 124 archivos** | Tipado estático limpio con la configuración del proyecto; en S1.3 se partió de 45 errores. |
| `npm run lint` (eslint) | [03-eslint.txt](03-eslint.txt) · [png](03-eslint.png) | **0 errores, 1 advertencia** | La advertencia es una variable `t` sin usar en `src/app/register/page.test.tsx:7`; no bloquea la CI (también aparece como anotación en CI #40). |
| `npx tsc --noEmit` | [04-tsc.txt](04-tsc.txt) · [png](04-tsc.png) | **0 errores** (salida vacía, `tsc exit=0`) | Todo el frontend compila sin errores de tipos. |
| `pip-audit -r requirements.txt` | [05-pip-audit.txt](05-pip-audit.txt) · [png](05-pip-audit.png) | **2 vulnerabilidades en 1 paquete**: `pyjwt 2.14.0` (PYSEC-2026-4141 y PYSEC-2026-4183), corregidas en 2.15.0 | Dependencia directa usada para los JWT de sesión: hay que subirla a 2.15.0 con su prueba. El PNG omite las líneas repetidas `WARNING:cachecontrol` (avisos de la caché local de pip-audit); el `.txt` las conserva. |
| `npm audit --omit=dev` | [06-npm-audit.txt](06-npm-audit.txt) · [png](06-npm-audit.png) | **6 vulnerabilidades: 5 altas, 1 moderada** en `next` (16.0.0–16.3.7), `nanoid`, `postcss`, `sharp`, `source-map-js` y `baseline-browser-mapping` | Todas con `fix available via npm audit fix`. La más relevante es `next 16.3.6`, con avisos de caché/ISR en despliegues propios. No se corrigen en esta entrega: actualizar dependencias es un cambio funcional y va en su propio PR con pruebas (regla de `CLAUDE.md`). |

Los códigos de salida 1 de `pip-audit` y `npm audit` son el comportamiento esperado de esas herramientas
cuando encuentran vulnerabilidades.

## Cómo reproducir

```bash
cd backend
python -m ruff check src/dossier
python -m mypy src/dossier
python -m pip_audit -r requirements.txt --progress-spinner off
cd ../frontend
npm run lint
npx tsc --noEmit
npm audit --omit=dev
```
