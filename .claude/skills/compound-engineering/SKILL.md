---
name: compound-engineering
description: "6-step feature loop (brainstorm, plan, work, simplify, review, compound) that writes each stage's output to docs/ so later features reuse what was learned. Use for a full feature end-to-end when the project doesn't already have a leaner workflow (writing-plans + subagent-driven-development covers steps 2-3 in more detail)."
version: 1.0.0
license: MIT
metadata:
  tags: [workflow, feature-loop, documentation]
  related_skills: [writing-plans, subagent-driven-development, requesting-code-review, owasp-top10]
---

# Compound Engineering

**Nota:** las referencias `[/ce-*]` del original eran slash commands de otro proyecto y no existen en Claude Code. Cada paso se hace directo (prompt normal o skill dedicada — ver mapeo abajo).

## El Loop de 6 Pasos

```
Brainstorm → Plan → Work → Simplify → Review → Compound
```

## Paso 1: Brainstorm

Explorar requisitos para [feature]: qué problema resuelve, quién lo usa, dependencias, qué hay que considerar. Guardar spec doc en `docs/requirements/`.

## Paso 2: Plan

Ver skill `writing-plans` — genera plan con tareas bite-sized, paths exactos, código completo, comandos de verificación. Guardar en `docs/exec-plans/active/`.

## Paso 3: Work

Ver skill `subagent-driven-development` — ejecuta el plan tarea por tarea con revisión de 2 etapas. Build/test verde antes de cada commit.

## Paso 4: Simplify

Refactorizar el código recién escrito: eliminar código muerto, simplificar lógica compleja, extraer funciones si hace falta. Verificar que los tests sigan pasando.

## Paso 5: Review

Ver skill `requesting-code-review` (pipeline completo) u `owasp-top10` (foco seguridad). Listar hallazgos, no aplicar cambios en este paso.

## Paso 6: Compound

Documentar qué funcionó, qué no, qué se haría distinto. Guardar en `docs/solutions/`.

## El Superpoder

Después de 10-15 features, `docs/solutions/` tiene un manual de supervivencia auto-mejorable. El agente lee estos archivos automáticamente al planificar.
