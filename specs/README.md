# Especificaciones

El **qué** y el **cómo se acepta**, escrito antes de codificar.

```
proposals/   la especificación, antes de implementar
reports/     la verificación, después de implementar
```

Flujo completo y cuándo aplica: [`docs/dev/sdd-workflow.md`](../docs/dev/sdd-workflow.md).

Regla de oro para los criterios de aceptación: **si no puedes escribir la prueba leyendo el
criterio, el criterio está mal escrito.**

---

## Plantilla · `proposals/SN.N-titulo.md`

```markdown
# SN.N · Título

- **Tarea:** SN.N · [tarjeta](https://trello.com/c/...)
- **Responsable:** FO | DG | FD
- **Brecha:** B1 | B2 | B3 | B4 | B5 | — (deuda técnica)
- **Estado:** borrador | acordada | implementada | verificada

## Problema

Qué falta hoy y por qué importa. Con evidencia: `archivo:línea` de lo que existe
y de lo que no.

## Alcance

**Incluye:**
- ...

**No incluye:**
- ...  (lo que se decide dejar fuera, para que nadie lo dé por supuesto)

## Diseño

Contratos, esquemas, endpoints, eventos. Concreto: nombres reales de campos y
tipos, no descripciones.

## Criterios de aceptación

Cada uno debe poder convertirse en una prueba sin interpretar nada.

- [ ] **CA1** — Dado [estado], cuando [acción], entonces [resultado observable]
- [ ] **CA2** — Dado [caso borde], cuando [acción], entonces [resultado]
- [ ] **CA3** — Dado [error], cuando [acción], entonces [error esperado, sin corromper estado]

## Pruebas exigidas

Según la tabla de `docs/dev/testing-policy.md` §1:

| Categoría | Obligatoria | Qué cubre |
|---|:---:|---|
| Unitaria | | |
| Integración | | |
| Estrés | | |
| Seguridad | | |

## Riesgos

Qué puede salir mal y qué se hace si sale mal.

## Decisiones pendientes

Lo que hay que resolver antes de implementar. Si es una decisión con
alternativas reales, va también a `docs/architecture/decisions/`.
```

---

## Plantilla · `reports/SN.N-verificacion.md`

```markdown
# Verificación · SN.N

- **Fecha:** AAAA-MM-DD
- **Verifica:** [alguien distinto de quien implementó]
- **Spec:** ../proposals/SN.N-titulo.md

## Criterios

| Criterio | Prueba que lo cubre | Estado |
|---|---|---|
| CA1 | `test_...` | cumple / no cumple / parcial |
| CA2 | `test_...` | |

## Definición de Terminado

- [ ] Código integrado mediante PR revisado
- [ ] Análisis estático sin errores
- [ ] Pruebas asociadas en verde
- [ ] Revisión por un segundo integrante
- [ ] Documentación actualizada
- [ ] Evidencia adjunta en la tarjeta

## Fuera de la spec

Lo que se implementó y no estaba especificado. Si hay algo aquí, o la spec
estaba incompleta o el alcance creció sin acordarlo. Ambas cosas conviene
saberlas.

## Descubierto de paso

Lo que se aprendió y no está escrito en ningún otro lado. Va también a
`.harness/progress.md`.
```

---

## Tareas que necesitan spec

Del plan actual, sin discusión:

| Tarea | Qué especifica |
|---|---|
| S0.9 | Esquema JSON estricto del dossier |
| S0.11 | Protocolo de estados progresivos |
| S0.12 | Arquitectura del agente europeo y del de noticias |
| S1.9 | Modelo común de registro corporativo |
| S2.1 | Agente de registros corporativos europeos |
| S3.1 | Cliente del proveedor de noticias |
| S4.1 | Modelos Pydantic del contrato |
| S4.8 | Canal de estados progresivos |
| S5.6 | Integración del proveedor de correo |

Las tareas de corrección, refactor o documentación **no** necesitan spec.
