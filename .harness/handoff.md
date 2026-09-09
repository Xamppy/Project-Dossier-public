# Protocolo de coordinación

Cómo trabajan varias personas y varios agentes sobre este repositorio sin pisarse.

La regla que sostiene todo lo demás: **el estado vive en archivos, no en la memoria de nadie**.
Un agente que abre el repositorio por primera vez debe poder saber qué está pasando leyendo
`feature_list.json`, `progress.md` y este archivo. Si algo importante solo existe en un chat,
en la cabeza de alguien o en el contexto de una sesión, está perdido.

---

## 1. Tomar una tarea

```
1. Leer .harness/feature_list.json
2. Elegir UNA tarea con status "pending" y sin dependencias abiertas
3. Cambiar su status a "claimed", poner tu identificador en "owner_session"
4. Commit inmediato de ese cambio, solo, antes de escribir código
5. Recién ahí empezar
```

El paso 4 no es burocracia: es lo que evita que dos agentes tomen la misma tarea. El commit del
`claimed` es el candado. Si al hacer push hay conflicto en `feature_list.json`, alguien te ganó:
elige otra tarea.

Mensaje de ese commit:

```
chore(harness): claim S4.2

Session: <tu identificador>
```

### Cómo saber si una tarea está lista para tomarse

Una tarea está lista cuando `depends_on` está vacío o **todas** sus dependencias tienen
`status: "done"`. El campo `blocks` te dice a quién desbloqueas al terminarla: si `blocks` es
largo, esa tarea es ruta crítica y conviene priorizarla.

```bash
python .harness/next.py            # tareas disponibles ahora
python .harness/next.py --owner FO # solo las de un responsable
python .harness/next.py --status   # resumen del proyecto
```

---

## 2. Estados

| Estado | Significa | Quién lo pone |
|---|---|---|
| `pending` | Nadie la tomó | — |
| `claimed` | Alguien la tomó, aún no empieza | quien la toma |
| `in_progress` | Hay trabajo en curso, hay rama | quien la ejecuta |
| `review` | PR abierto, esperando revisión de un segundo integrante | quien la ejecuta |
| `blocked` | No se puede avanzar; el motivo va en `notes` | cualquiera |
| `done` | Definición de Terminado cumplida, evidencia adjunta | quien revisa |

Una tarea nunca pasa a `done` por quien la implementó. La mueve **el segundo integrante que la
revisa**. Ese es el punto de la condición 4 de la Definición de Terminado.

---

## 3. Ramas y commits

Una rama por tarea, con el identificador dentro:

```
feat/S2.1-agente-europeo
fix/S1.3-analisis-estatico
docs/S2.7-cobertura-europea
```

Commits en formato convencional, con el identificador de tarea en el cuerpo:

```
feat(agents): agente de registros corporativos europeos

Implementa el nodo del orquestador para la fuente europea, siguiendo el
patrón de companies_house y sec_edgar.

Task: S2.1
```

Prefijos: `feat` · `fix` · `docs` · `test` · `refactor` · `chore` · `perf`

---

## 4. Áreas de trabajo

Cada tarea declara un `area` en `feature_list.json`. Dos tareas de áreas distintas casi nunca
tocan los mismos archivos, así que pueden avanzar en paralelo sin coordinación previa.

| Área | Toca | Responsable habitual |
|---|---|---|
| `backend` | `backend/src/dossier/{api,services,graphs,llm,companies_house,sec_edgar}` | FO |
| `frontend` | `frontend/src` | DG |
| `db` | `backend/src/dossier/db`, migraciones | FO / FD |
| `security` | `backend/src/dossier/security`, CORS, tasa, auditoría | FD |
| `quality` | pruebas, linters, cobertura | FD |
| `ci` | integración continua | FD |
| `docs` | `docs/`, `.harness/`, informes | quien corresponda |

**Antes de empezar una tarea de `db`**, avisa en `progress.md`: los cambios de esquema afectan a
todos. Es la única área que exige aviso previo.

---

## 5. Traspaso entre sesiones

Cuando una sesión termina sin cerrar la tarea, deja el traspaso escrito. Un agente que retoma
mañana no tiene tu contexto: solo tiene lo que escribiste.

Añade una entrada a `progress.md` con esta forma:

```markdown
### 2026-10-12 · S2.1 · FO (agente)

**Hecho.** Cliente HTTP de la fuente europea funcionando contra el entorno de prueba.
Normaliza tres países. Pruebas sobre respuestas fijas en `tests/test_eu_registry.py`.

**Sin terminar.** Falta la integración al orquestador (el nodo existe pero no está
conectado en `corporate_dossier_graph.py`).

**Lo que hay que saber.** La fuente devuelve fechas en formato local por país, no ISO.
Hay un normalizador en `eu_registry/dates.py`; usarlo, no reimplementar.

**Siguiente paso concreto.** Conectar el nodo en `corporate_dossier_graph.py` siguiendo
el patrón de la línea 77 (UK). La selección de jurisdicción va antes del fan-out.

**Rama.** `feat/S2.1-agente-europeo` · **Estado.** in_progress
```

Las cuatro secciones importan, pero la tercera es la que ahorra horas: es lo que descubriste y
no está escrito en ningún otro lado.

---

## 6. Antes de abrir un PR

Un solo comando, desde la raíz:

```bash
python scripts/qa.py          # antes de commitear
python scripts/qa.py --full   # antes de push, añade el build del frontend
```

Ejecuta solo lo que corresponde a lo que cambiaste, y **detiene el commit si tocaste código sin
tocar pruebas**. Para que corra solo en cada commit: `python scripts/install-hooks.py`.

La regla que impone: *ningún cambio de código entra sin la prueba que lo respalda*. Qué categoría
exige tu cambio está en la tabla de [`docs/dev/testing-policy.md`](../docs/dev/testing-policy.md) §1.

Cuando S1.2 esté cerrada, `qa.py` suma ruff y mypy solo. Cuando S1.5 esté cerrada, lo hace la CI
y deja de ser tu responsabilidad recordarlo.

---

## 7. Decisiones técnicas

Toda decisión que un agente futuro podría revertir por desconocimiento va escrita en
`docs/architecture/decisions/`, un archivo por decisión:

```
docs/architecture/decisions/0001-linea-llm-canonica.md
docs/architecture/decisions/0002-protocolo-estados-progresivos.md
```

Formato: contexto, alternativas evaluadas, decisión, consecuencias, fecha, quién decidió.

Sprint 0 produce seis decisiones obligatorias: línea LLM canónica (S0.4), modelo de lenguaje
(S0.5), fuente europea (S0.6), proveedor de noticias (S0.7), proveedor de correo (S0.8) y
protocolo de estados progresivos (S0.11). Sin ellas escritas, el Sprint 0 no está cerrado.

---

## 8. Qué NO hacer

- No tomar dos tareas a la vez.
- No escribir el código antes que la prueba, ni modificar una prueba para que pase.
- No borrar código sin borrar sus pruebas en el mismo commit, diciendo cuáles.
- No mezclar corrección de análisis estático con cambio funcional en el mismo PR (riesgo R4).
- No marcar `done` tu propia tarea.
- No cambiar el esquema de base de datos sin leer `db/Migracion.md` y `db/schema_patches.py`.
- No presentar como terminada una función sin evidencia de implementación, validación y documentación.
- No dejar credenciales en el código. Solo variables de entorno.
- No usar datos personales reales. Solo cuentas y ambientes de prueba.

---

## 9. Escalar

Si estás bloqueado y no puedes avanzar:

1. Pon la tarea en `blocked` con el motivo en `notes`
2. Escribe la entrada en `progress.md` explicando qué intentaste
3. Toma otra tarea disponible

No insistas más de dos o tres intentos sobre el mismo obstáculo. Un bloqueo escrito y una tarea
distinta avanzando valen más que una sesión entera peleando con lo mismo.
