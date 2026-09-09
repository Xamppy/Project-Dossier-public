# scripts/

Utilidades de proyecto. Se ejecutan desde la raíz del repositorio.

| Script | Para qué |
|---|---|
| `qa.py` | Verificación antes de commitear o de hacer push |
| `install-hooks.py` | Instala los ganchos de git que ejecutan `qa.py` |
| `load/` | Pruebas de carga HTTP con k6 (existentes) |

---

## qa.py

Un solo comando antes de commitear. Ejecuta únicamente lo que corresponde a lo que cambiaste: si
tocaste solo el backend, no compila el frontend.

```bash
python scripts/qa.py             # antes de commitear
python scripts/qa.py --full      # antes de push: añade el build del frontend
python scripts/qa.py --fast      # solo unitarias, mientras desarrollas
python scripts/qa.py --policy    # solo la revisión de la política de pruebas
python scripts/qa.py --since main   # comparar contra una referencia
```

### Qué comprueba

| | `--fast` | (normal) | `--full` |
|---|:---:|:---:|:---:|
| Política de pruebas | ✅ | ✅ | ✅ |
| pytest unitarias | ✅ | ✅ | ✅ |
| pytest integración, estrés, seguridad | | ✅ | ✅ |
| eslint | ✅ | ✅ | ✅ |
| vitest | | ✅ | ✅ |
| `next build` | | | ✅ |
| ruff y mypy | aviso | aviso | aviso |

ruff y mypy avisan en vez de bloquear hasta que exista `backend/pyproject.toml` (tarea **S1.2**).
Cuando exista, pasan a ser obligatorios sin tocar nada: el script lo detecta solo.

### La revisión de política

Es lo que hace real la regla del proyecto. Compara los archivos de código cambiados con los
archivos de prueba cambiados:

- **Código cambiado y ninguna prueba** → falla. El commit se detiene.
- **Zona sensible sin prueba asociada** (`security/`, `billing/`, `db/`, `graphs/`) → aviso.
- **Solo documentación, traducciones o configuración** → pasa.

No cuentan como código: `backend/tests/`, `*.test.ts(x)`, `*.spec.ts(x)` y
`frontend/src/i18n/messages/`.

Si de verdad no aplica una prueba a tu cambio, **dilo en el mensaje del commit** y sáltalo con
`git commit --no-verify`. La opción existe a propósito: el objetivo es que saltarse la regla sea
una decisión consciente y visible, no la costumbre.

---

## install-hooks.py

```bash
python scripts/install-hooks.py             # instalar
python scripts/install-hooks.py --check     # ver qué hay instalado
python scripts/install-hooks.py --uninstall # quitar
```

Deja dos ganchos:

| Gancho | Ejecuta |
|---|---|
| `pre-commit` | `python scripts/qa.py` |
| `pre-push` | `python scripts/qa.py --full` |

**Aviso sobre worktrees.** Git guarda los ganchos en el directorio común del repositorio, así que
se comparten entre todos los worktrees. Instalarlos desde aquí los activa también en los demás.
El script lo detecta y lo avisa antes de escribir nada.

Si ya había un gancho que no era nuestro, se guarda como `<nombre>.anterior` y se restaura al
desinstalar.

---

## load/

Pruebas de carga con k6 contra un servidor levantado. **No** forman parte de `qa.py`: necesitan
API en marcha, PostgreSQL y un token válido.

```bash
k6 run scripts/load/k6-dossier-saturation.js
k6 run -e K6_SCENARIO=dedup scripts/load/k6-dossier-saturation.js
```

Escenarios: deduplicación asíncrona y límite de créditos. Detalle en `load/README.md`.

Las pruebas de estrés que **sí** corren en cada PR viven en `backend/tests/stress/` y no
necesitan servidor. Ver `docs/dev/testing-policy.md` §4.
