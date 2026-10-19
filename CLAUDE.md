# CLAUDE.md

Instrucciones para Claude Code en este repositorio.

## Empieza aquí

Lee [AGENTS.md](AGENTS.md). Es el índice. No leas todo `docs/` de entrada: busca el tema
concreto en la tabla del índice.

Antes de tocar código, en este orden:

1. `.harness/PROMPT.md` — qué es el proyecto y qué se está construyendo
2. `python .harness/next.py` — qué tareas están disponibles ahora
3. `.harness/progress.md` — qué hicieron las sesiones anteriores
4. `.harness/handoff.md` — cómo tomar una tarea sin chocar con otro agente

## Reglas de trabajo

**Una sesión, una tarea.** Toma una sola tarea de `feature_list.json`, ejecútala, deja el estado
escrito. No encadenes tareas sin que te lo pidan.

**Toma la tarea antes de escribir código.**

```bash
python .harness/next.py --claim S2.1 --as "FO (agente)"
git add .harness/feature_list.json
git commit -m "chore(harness): claim S2.1"
```

Ese commit es el candado que evita que dos agentes trabajen lo mismo. Si el push da conflicto en
`feature_list.json`, alguien te ganó: elige otra tarea.

**Deja el traspaso escrito.** Al terminar la sesión, añade una entrada a `.harness/progress.md`
con el formato de `handoff.md` sección 5. Lo importante es la sección «Lo que hay que saber»:
lo que descubriste y no está escrito en ningún otro lado.

**No marques `done` tu propia tarea.** Lo hace el segundo integrante que revisa.

## Este es un proyecto de continuidad

El sistema ya existe y funciona: autenticación, multiempresa, calendarios Google y Microsoft,
generación asíncrona, dossiers de personas, registros de Reino Unido y Estados Unidos, créditos,
dashboard en cinco idiomas.

**Antes de escribir algo nuevo, búscalo.** Es más probable que exista y no lo hayas encontrado
a que falte. Lo que sí falta está enumerado en `.harness/fix_plan.md` y en las cinco brechas de
`AGENTS.md`.

## Estado real del repositorio

Cosas que sorprenden si no las sabes:

- **Hay CI** (S1.5) en `.github/workflows/ci.yml`: en cada push y PR a `main` corre pytest, ruff
  y mypy del backend, y eslint, Vitest y build del frontend (Node 20). Corre igual `qa.py` antes
  de cada PR y revisa el resultado en Actions.
- **Hay migraciones Alembic** (S1.1) en `backend/alembic/versions/`. `db/schema_patches.py` sigue
  aplicando parches al arrancar y `db/Migracion.md` documenta el esquema. No cambies el esquema
  sin leer los tres y avisar en `progress.md`.
- **ruff y mypy están configurados** en `backend/pyproject.toml` (S1.2); sobre `src/dossier` dan
  0 hallazgos.
- **La suite backend corre**: 659 passed y 121 skipped sin Postgres (109 piden `TEST_DATABASE_URL`
  y 12 esperan su tarea). Entorno en `backend/.venv`.
- **El frontend tiene Vitest**: 522 pruebas en 40 archivos. Con Node 26 hay que correrlo con
  `NODE_OPTIONS=--no-experimental-webstorage` (el `localStorage` nativo de Node tapa el de jsdom)
  hasta que se cierre CHORE-2026-10-19-02.
- **eslint da 0 errores** en el frontend (S1.3).
- **`gemini/` y la clave `gemini_analysis_markdown` se retiraron** (S1.6;
  `test_llm_canonical_line.py` impide que vuelvan). Quedan nombres con «gemini», como
  `person_gemini_analysis.py` o la modalidad `gemini_web`, que llaman a DeepSeek sin búsqueda web
  real. El nombre miente; no te confíes.
- **`dossier_data` es JSONB** y sigue guardando `{"format": "markdown", "body": ...}`. En Personas
  suma `executive_payload`, validado contra `DossierExecutivePayload` en la síntesis (S4.1–S4.3);
  la lectura tolera los dossiers históricos sin él (S4.4).

## Pruebas: la regla que no se salta

> **Ningún cambio de código entra sin la prueba que lo respalda.** Agregar, modificar y eliminar
> cuentan como cambio.

Ciclo obligatorio, en este orden:

1. Escribe la prueba
2. Ejecútala y **compruébala en rojo** — si pasa a la primera, no prueba lo que crees
3. Escribe el código mínimo para que pase
4. Refactoriza con las pruebas en verde

Nunca modifiques una prueba para que pase: modifica el código.

Qué categoría exige tu cambio (unitaria, integración, estrés, seguridad) está en la tabla de
[docs/dev/testing-policy.md](docs/dev/testing-policy.md) §1. Al borrar código, borra sus pruebas
en el mismo commit y di cuáles en el mensaje (§5).

Si la tarea define un contrato nuevo, antes va una especificación:
[docs/dev/sdd-workflow.md](docs/dev/sdd-workflow.md).

## Verificar antes de un PR

Un solo comando:

```bash
python scripts/qa.py          # antes de commitear
python scripts/qa.py --full   # antes de push, añade el build
python scripts/qa.py --fast   # solo unitarias, mientras desarrollas
```

Detiene el commit si cambiaste código sin tocar pruebas. Si de verdad no aplica, dilo en el
mensaje del commit y usa `git commit --no-verify`.

Cuando S1.2 esté cerrada, `qa.py` suma ruff y mypy solo (detecta `pyproject.toml`). Cuando S1.5
esté cerrada, lo hace la CI.

## Commits

Formato convencional, con el identificador de tarea en el cuerpo:

```
feat(agents): agente de registros corporativos europeos

Implementa el nodo del orquestador para la fuente europea, siguiendo el
patrón de companies_house y sec_edgar.

Task: S2.1
```

Ramas: `feat/S2.1-agente-europeo`, `fix/S1.3-analisis-estatico`, `docs/S2.7-cobertura-europea`.

## Idioma

Código, comentarios, documentación, commits y mensajes de interfaz **en español**, salvo:
identificadores y nombres de API, palabras clave de commit convencional (`feat`, `fix`), y
cadenas de los otros cuatro idiomas del dashboard.

## Límites

- Nunca credenciales en el código ni en un commit. Solo variables de entorno.
- Nunca datos personales reales. Solo cuentas y ambientes de prueba.
- Nunca cobros reales; Stripe solo en entorno de pruebas, y solo si S5.9 lo autoriza.
- No mezcles corrección de análisis estático con cambio funcional en el mismo PR.
- No presentes una función como terminada sin evidencia de implementación, validación y
  documentación.

## Si te bloqueas

Dos o tres intentos sobre el mismo obstáculo, no más:

```bash
python .harness/next.py --set S2.1 blocked --notes "motivo concreto"
```

Escribe la entrada en `progress.md` con lo que intentaste y toma otra tarea.
