---
name: sdd
description: "Spec-Driven Development: 7-phase flow (explore, propose+spec, plan tasks, implement TDD, verify, archive) with clean-context subagents per phase. Use for features needing a written spec before code."
version: 1.0.0
license: MIT
metadata:
  tags: [spec-driven-development, planning, tdd, subagents]
  related_skills: [writing-plans, subagent-driven-development, test-driven-development]
---

# SDD (Spec-Driven Development)

## Flujo de 7 Fases

| Fase | Rol | Qué hace | Output |
|------|-----|----------|--------|
| 0 | Orquestador | Calibración, leer config | Diagnóstico |
| 1 | Explorer | Explora codebase | Contexto |
| 2 | Proposer + Spec | Propone y especifica | specs/proposals/ |
| 3 | Task Planner | Divide en tareas | specs/tasks/ |
| 4 | Implementer | Codifica con TDD | Código + tests |
| 5 | Verifier | Revisa contra specs | specs/reports/ |
| 6 | Archiver | Documenta | docs/solutions/ |

## Reglas SDD

1. **El orquestador NO edita código** — solo planifica y delega
2. Cada subagente recibe contexto LIMPIO (solo su tarea)
3. TDD obligatorio (RED → GREEN → REFACTOR)
4. Build antes de cada commit
5. Documentar decisiones en Engram/docs/solutions/

## Para Crear una Feature

```bash
# 1. Crear spec
mkdir -p specs/proposals
cat > specs/proposals/FEATURE-001.md << 'EOF'
# Feature: [Nombre]

## Requisitos
- [ ] Requisito 1
- [ ] Requisito 2

## Diseño
- Endpoint: /api/...
- Modelo: ...
- Componente: ...

## Criterios de Aceptación
- [ ] Test pasa
- [ ] Build pasa
- [ ] Documentación actualizada
EOF

# 2. Crear plan de implementación
mkdir -p docs/exec-plans/active
cat > docs/exec-plans/active/FEAT-001.md << 'EOF'
# Plan: [Nombre]

## Archivos a modificar
- path/to/file1.ts
- path/to/file2.py

## Pasos
1. Crear modelo en models.py
2. Crear endpoint en views.py
3. Crear componente en Component.tsx
4. Escribir tests
5. Build + commit

## Verificación
- python manage.py test
- npm run build
EOF
```
