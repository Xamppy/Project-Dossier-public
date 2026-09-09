# Política de pruebas

El objetivo de este documento es concreto: **que QA no tenga que descubrir a mano lo que una
prueba podía haber descubierto sola**. Cada cosa que se automatiza aquí es una cosa que nadie
vuelve a verificar clic a clic antes de cada entrega.

La regla base es una sola:

> **Ningún cambio de código entra sin la prueba que lo respalda.** Agregar, modificar y eliminar
> cuentan como cambio. Eliminar también.

---

## 1. Qué prueba exige cada cambio

Busca tu fila. Las celdas marcadas son obligatorias; las vacías, opcionales.

| Cambio | Unitaria | Integración | Estrés | Seguridad |
|---|:---:|:---:|:---:|:---:|
| Endpoint HTTP nuevo | ✅ | ✅ | ✅ | ✅ |
| Cambio de contrato de un endpoint | ✅ | ✅ | | ✅ |
| Agente o nodo del orquestador | ✅ | ✅ | ✅ | |
| Cliente de proveedor externo | ✅ | ✅ | ✅ | |
| Tabla, columna o migración | ✅ | ✅ | | ✅ |
| Esquema Pydantic / contrato de datos | ✅ | | | |
| Lógica de créditos o de planes | ✅ | ✅ | | ✅ |
| Control de acceso, tasa, auditoría, retención | ✅ | ✅ | ✅ | ✅ |
| Componente o proveedor de frontend | ✅ | | | |
| Trabajador en segundo plano | ✅ | ✅ | ✅ | |
| Corrección de defecto | ✅ | | | |
| Eliminación de código | ver §5 | | | |
| Solo documentación o formato | | | | |

**«Estrés» no significa montar un laboratorio de carga.** Significa responder tres preguntas con
una prueba: qué pasa con volumen alto, qué pasa con muchas llamadas a la vez, y qué pasa cuando
el proveedor externo tarda o falla. Ver §4.

---

## 2. TDD: el orden importa

El ciclo es **RED → GREEN → REFACTOR**, y el orden no es decorativo. Una prueba escrita después
del código tiende a confirmar lo que el código hace, no lo que debería hacer.

```
1. RED       Escribe la prueba. Ejecútala. Debe FALLAR.
2. GREEN     Escribe el código mínimo para que pase. No más.
3. REFACTOR  Mejora el código. Las pruebas siguen en verde.
```

### Las tres reglas que no se rompen

1. **Nunca modifiques la prueba para que pase.** Modifica el código. Si la prueba estaba mal
   escrita, bórrala, entiende el requisito y escríbela de nuevo — pero eso es un acto consciente,
   no un ajuste al vuelo.
2. **Una cosa a la vez.** No mezcles una funcionalidad nueva con un refactor en el mismo ciclo.
3. **Verifica que falla antes de implementar.** Una prueba que nunca estuvo en rojo no ha
   demostrado que prueba algo. Es el paso que más se salta y el que más valor da.

### Qué cubre una prueba unitaria decente

Tres casos, siempre:

- **El normal.** La entrada esperada produce la salida esperada.
- **El borde.** Vacío, cero, uno, el máximo, el carácter raro, la lista de un elemento.
- **El error.** La entrada inválida falla como debe, con el error que debe, sin corromper estado.

Si tu prueba solo tiene el caso normal, está a un tercio.

---

## 3. Categorías

Se asignan solas según la carpeta (`tests/conftest.py`). No hace falta escribir el marcador.

| Carpeta | Marcador | Qué va aquí | Cuándo corre |
|---|---|---|---|
| `backend/tests/` | `unit` | Funciones puras, validadores, esquemas. Sin entrada/salida real | Siempre |
| `backend/tests/integration/` | `integration` | Cruza capas, usa `TestClient`, red simulada | Siempre |
| `backend/tests/stress/` | `stress` | Volumen, concurrencia, degradación | Siempre (son rápidas) |
| `backend/tests/security/` | `security` | Acceso, aislamiento, tasa, retención | Siempre |
| `frontend/src/**/*.test.tsx` | — | Componentes y proveedores | Siempre |
| `scripts/load/` | — | Carga HTTP real con k6 | A mano, no en cada PR |

```bash
pytest -m unit              # rápido, mientras desarrollas
pytest -m "not stress"      # si tienes prisa
pytest                      # todo, antes del PR
```

### Ninguna prueba sale a la red

`conftest.py` bloquea las conexiones reales en todas las pruebas. Una prueba que depende de
internet no es una prueba: es un monitor de disponibilidad ajena que falla los viernes por
razones que no son tuyas.

Simula la respuesta del proveedor. Hay una utilidad lista: la fixture `respuesta_fija`.

---

## 4. Pruebas de estrés sin montar un laboratorio

Tres preguntas, tres formas de responderlas con pytest normal. Ejemplos reales en
`backend/tests/stress/`.

### Volumen

¿Qué pasa cuando la entrada es grande? Un dossier con 500 menciones de prensa, una organización
con 10 000 dossiers, una respuesta del proveedor con 1 MB de JSON.

Lo que se verifica: que no explota, que no se degrada más de lo razonable, y que respeta los
límites declarados (por ejemplo, el máximo de tres ideas de conversación).

### Concurrencia

¿Qué pasa con muchas llamadas a la vez? Diez generaciones simultáneas de la misma organización.

Lo que se verifica: que los créditos se descuentan una sola vez por dossier, que no hay
condiciones de carrera en el estado, que el aislamiento entre organizaciones aguanta bajo carga.

Este es el que más defectos encuentra en producción y el que menos se escribe.

### Degradación

¿Qué pasa cuando el proveedor externo tarda o falla? Es la pregunta central de este sistema:
cinco agentes externos, cualquiera puede caerse.

Lo que se verifica: que el dossier se entrega igual con resultado parcial, que el fallo queda en
`agents_failed`, que no se cobran créditos por lo que no se entregó, y que hay tiempo límite.

### Carga HTTP real

Para medir latencia y capacidad de verdad hace falta un servidor levantado. Eso **ya existe**:
`scripts/load/k6-dossier-saturation.js`, con dos escenarios reales — deduplicación asíncrona
(diez peticiones simultáneas del mismo nombre deben devolver un solo `job_id`) y límite de
créditos (saldo agotado debe dar HTTP 402).

Se corre a mano contra un servidor levantado y **no bloquea un PR**. Ver `scripts/load/README.md`.

```bash
k6 run scripts/load/k6-dossier-saturation.js
k6 run -e K6_SCENARIO=dedup scripts/load/k6-dossier-saturation.js
```

Al escribir una prueba de estrés, mira primero si su escenario ya está en k6: puede que solo
falte llevarlo a `tests/stress/` como versión rápida que sí corre en cada PR.

---

## 5. Eliminar código

La parte que casi nunca se escribe en una política de pruebas, y la que más problemas causa.

Cuando borras código, borras también sus pruebas. Eso está bien y es lo correcto. Lo que **no**
está bien es borrar sin comprobar que nadie más lo usaba.

```bash
# 1. ¿Quién referencia esto?
grep -rn "nombre_de_lo_que_borras" backend/src frontend/src

# 2. ¿Qué pruebas lo cubren?
grep -rln "nombre_de_lo_que_borras" backend/tests frontend/src

# 3. Borra código y pruebas juntos, en el mismo commit.

# 4. La suite completa debe quedar en verde.
```

En el commit, di qué pruebas se fueron y por qué:

```
refactor(llm): retirar el shim de gemini

El shim quedó sin uso tras declarar DeepSeek como línea canónica (ADR 0001).

Pruebas eliminadas: test_gemini_shim.py (5 casos). Cubrían la traducción de
llamadas al cliente antiguo, que ya no existe.

Task: S1.6
```

**Si una prueba estorba y no sabes por qué existe, no la borres.** Busca el commit que la
introdujo. Casi siempre defiende de un defecto real que alguien ya sufrió una vez.

---

## 6. Cobertura

La cobertura mide qué líneas ejecuta la suite. **No mide si las pruebas son buenas.** Una suite
con 90 % de cobertura y sin una sola aserción sobre casos de error no vale nada.

Sirve para una cosa: encontrar lo que nadie probó nunca.

```bash
cd backend
pytest --cov=src/dossier --cov-report=term-missing
pytest --cov=src/dossier --cov-report=html   # htmlcov/index.html
```

La meta se fija en **S0.3**, sobre la línea base medida, no sobre un número inventado. Hasta
entonces la regla es direccional y basta: **la cobertura no baja**. Un PR que la baja necesita
justificación escrita en su descripción.

Módulos sin ninguna prueba hoy, por orden de riesgo (de `fix_plan.md`):

1. `graphs/corporate_dossier_graph.py` — el orquestador
2. `services/person_research_pipeline.py` — el pipeline
3. `services/calendar_event_dossiers.py` — 1000+ líneas
4. `api/app.py` — 1400+ líneas

---

## 7. Qué le queda a QA manual

Automatizar todo lo automatizable deja fuera exactamente tres cosas. Estas sí se revisan a mano,
y solo estas:

1. **Lo visual.** Que el dashboard se vea bien en pantalla real, en los cinco idiomas, en móvil.
   Ninguna prueba automática juzga si algo se ve mal.
2. **Lo exploratorio.** Buscar lo que nadie previó. Es lo que mejor hace una persona y peor hace
   una máquina, y necesita tiempo libre — que es justo lo que le devuelve todo lo anterior.
3. **La aceptación con el docente guía.** El flujo completo demostrado en vivo (S7.1).

**Todo lo demás debería fallar solo antes de llegar a QA.** Si QA encuentra un defecto que una
prueba podía haber encontrado, esa es la señal de que falta una prueba: se escribe la prueba que
lo reproduce (en rojo), y luego se corrige. Esa prueba se queda para siempre.

---

## 8. Antes de cada commit y cada push

Un solo comando:

```bash
python scripts/qa.py            # antes de commitear
python scripts/qa.py --full     # antes de push, incluye build del frontend
```

Los ganchos de git lo ejecutan solos si los instalas:

```bash
python scripts/install-hooks.py
```

Detalle de qué corre cada uno: [`scripts/README.md`](../../scripts/README.md).

---

## 9. Resumen en cinco líneas

1. Escribe la prueba primero y compruébala en rojo.
2. Consulta la tabla de §1 para saber qué categorías exige tu cambio.
3. Caso normal, caso borde, caso de error. Los tres.
4. Al borrar código, borra sus pruebas en el mismo commit y di cuáles.
5. `python scripts/qa.py` antes de commitear. Sin excepciones.
