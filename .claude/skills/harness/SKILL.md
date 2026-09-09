---
name: harness
description: "Project structure for agent-driven dev: AGENTS.md index, .harness/ state files, docs/ layout. Use when setting up a new codebase for sustained agent work or asking 'how should this repo be organized for Claude Code'."
version: 1.0.0
license: MIT
metadata:
  tags: [project-structure, agents-md, state-files, documentation]
---

# Harness Engineering

## Estructura del Proyecto

```
proyecto/
├── AGENTS.md                    # Índice (~100 líneas)
├── CLAUDE.md                    # Contexto para Claude Code
├── .harness/
│   ├── AGENT.md                 # Cómo correr el proyecto
│   ├── PROMPT.md                # Contexto inicial
│   ├── progress.md              # Log de sesiones
│   ├── fix_plan.md              # TODO priorizado
│   └── feature_list.json        # Estado de features
├── docs/
│   ├── architecture/
│   ├── auth/
│   ├── dev/
│   ├── security/
│   └── exec-plans/
│       ├── active/
│       └── completed/
```

## Flujo

1. Leer `.harness/feature_list.json` → saber qué está pendiente
2. Leer `.harness/progress.md` → saber qué se hizo antes
3. Seleccionar UNA tarea
4. Ejecutar
5. Build → Tests → Commit → Push
6. Actualizar `progress.md` y `feature_list.json`

## Reglas

- AGENTS.md = índice corto, NO manual monolítico
- Estado en archivos, no en contexto del agente
- Tests como backpressure
- Separación de roles: Planificador ≠ Implementador
