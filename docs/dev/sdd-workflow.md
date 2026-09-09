# SDD — Desarrollo guiado por especificación

Antes de escribir código se escribe qué debe hacer y cómo se sabrá que lo hace. Suena obvio y es
justo lo que se salta cuando hay prisa.

En un proyecto de continuidad como este importa más que en uno nuevo: el código heredado ya tiene
decisiones tomadas que nadie documentó, y la única forma de no repetir esa historia es dejar
escrito el porqué de lo que agregamos.

---

## Dónde vive cada cosa

Tres carpetas, tres preguntas distintas. Si las confundes, terminas escribiendo lo mismo tres
veces.

| Carpeta | Pregunta | Cuándo se escribe |
|---|---|---|
| `specs/` | **Qué** debe hacer y cómo se acepta | Antes de codificar |
| `docs/exec-plans/` | **Cómo** se va a construir, paso a paso | Al empezar, si la tarea es grande |
| `docs/architecture/decisions/` | **Por qué** se eligió esto y no aquello | Cuando hay alternativas reales |

La tarjeta de Trello y `feature_list.json` siguen siendo el estado. Estas carpetas son el
contenido.

---

## Las siete fases

Adaptadas al tamaño real del equipo: tres personas y agentes, no una organización.

| Fase | Qué se hace | Sale |
|---|---|---|
| 0 · Calibrar | ¿Esta tarea necesita spec? Ver §«Cuándo» | — |
| 1 · Explorar | Leer el código que se va a tocar. **Sin editar nada** | Notas |
| 2 · Especificar | Requisitos y criterios de aceptación | `specs/proposals/` |
| 3 · Planificar | Dividir en pasos, listar archivos | `docs/exec-plans/active/` |
| 4 · Implementar | TDD: rojo, verde, refactor | Código y pruebas |
| 5 · Verificar | Contrastar contra la spec, no contra la memoria | `specs/reports/` |
| 6 · Archivar | Mover a completado, registrar lo aprendido | `progress.md` |

### La regla que sostiene el método

**Quien planifica no implementa en la misma pasada.** No es burocracia: cuando escribes el
código, tu criterio de «esto está bien» se contamina con lo que acabas de construir. Separar los
momentos —aunque sea la misma persona en dos ratos distintos— es lo que permite que la fase 5
encuentre algo.

Si delegas a un subagente, dale contexto limpio: la spec y nada más. Un agente que ve tu
implementación va a validarla, no a cuestionarla.

---

## Cuándo escribir una spec

**Sí:**

- Contrato nuevo o cambio de uno existente (endpoint, esquema, evento)
- Integración con un proveedor externo
- Cambio de modelo de datos
- Cualquier tarea que cierre una de las cinco brechas

**No:**

- Corrección de un defecto con causa clara
- Refactor sin cambio de comportamiento
- Documentación, formato, dependencias

Ante la duda: si al terminar alguien podría preguntar «¿y esto por qué se hizo así?», escribe la
spec.

Del plan actual, estas tareas la necesitan sin discusión: **S0.9** (esquema JSON), **S0.11**
(protocolo de estados), **S0.12** (arquitectura de agentes), **S1.9** (modelo común de registro),
**S2.1**, **S3.1**, **S4.1**, **S4.8**, **S5.6**.

---

## Fase 2 — la especificación

`specs/proposals/SN.N-titulo.md`. Plantilla en `specs/README.md`.

Lo que la hace útil o inútil son los **criterios de aceptación**. Comparación directa:

```
Mal:  El agente europeo funciona correctamente.
Bien: Dada una empresa alemana con número de registro válido, el agente devuelve
      un RegistroCorporativo con razón social, fecha de constitución, estado y
      domicilio, más la fuente y la fecha de consulta.
      Dada una empresa inexistente, devuelve None sin lanzar excepción.
      Si la fuente responde 500, el dossier se entrega con agents_failed
      poblado y el usuario ve qué módulo faltó.
```

El segundo se puede convertir en tres pruebas sin pensar. El primero no se puede convertir en
nada. Ese es el filtro: **si no puedes escribir la prueba leyendo el criterio, el criterio está
mal escrito**.

Copia los criterios desde la tarjeta de Trello, que es donde se acordaron. Si al escribir la
spec descubres que el criterio de la tarjeta era vago, arregla la tarjeta.

---

## Fase 4 — implementar con TDD

El detalle está en [`testing-policy.md`](testing-policy.md). El resumen:

1. Toma un criterio de aceptación de la spec
2. Escribe la prueba que lo verifica
3. Ejecútala. **Debe fallar** — si pasa a la primera, no estás probando lo que crees
4. Escribe el código mínimo para que pase
5. Refactoriza con las pruebas en verde
6. Siguiente criterio

Al terminar, cada criterio de aceptación tiene al menos una prueba con su nombre. Eso es lo que
hace la fase 5 casi automática.

---

## Fase 5 — verificar

Contra la spec, no contra el recuerdo de lo que se quiso hacer.

```markdown
# Verificación · SN.N

| Criterio | Prueba que lo cubre | Estado |
|---|---|---|
| Empresa alemana devuelve RegistroCorporativo | test_agente_eu_alemania_ok | cumple |
| Empresa inexistente devuelve None | test_agente_eu_no_encontrada | cumple |
| Fuente 500 no aborta el dossier | test_degradacion_fuente_500 | cumple |

**Sin cubrir:** ninguno.
**Descubierto de paso:** la fuente devuelve fechas en formato local por país.
Normalizador en eu_registry/dates.py. Registrado como ADR 0003.
```

Un criterio sin prueba es un criterio sin cumplir. No hay término medio: o hay una prueba con
nombre, o la fase 5 falla.

---

## Cómo encaja con el resto

```
Tarjeta de Trello ─── qué hay que hacer y cuándo
        │
feature_list.json ─── estado, dependencias, quién lo tomó
        │
   specs/proposals ─── qué debe hacer y cómo se acepta
        │
docs/exec-plans/active ─── cómo se construye, paso a paso
        │
   código + pruebas ─── TDD
        │
   specs/reports ─── se cumplió, con qué prueba
        │
.harness/progress.md ─── qué aprendimos que sirve a otro
```

Ninguna de las siete piezas repite a otra. Si te encuentras copiando de una a otra, sobra una.
