---
name: git-workflow
description: "Branch strategy (dev vs main), atomic commits, Conventional Commits format, rebase merge flow. Use when committing, branching, or resolving rebase conflicts on a project that follows this convention."
version: 1.0.0
license: MIT
metadata:
  tags: [git, branching, conventional-commits, rebase]
---

# Git Workflow

## Branch Strategy

```
dev    → desarrollo activo (TRABAJAR AQUÍ)
main   → solo producción
```

**SIEMPRE verificar branch antes de empezar:**
```bash
echo "Branch actual: $(git branch --show-current)"
git branch
git branch -r
```

## Commits Atómicos

**Regla de oro:** Una funcionalidad = un commit. NO acumular.

```bash
# 1. Cambios para UNA funcionalidad
# 2. Tests pasan
# 3. Build pasa
npm run build

# 4. Commit
git add -A
git commit -m "feat(scope): descripción corta"

# 5. Push INMEDIATO
git push origin dev
```

## Conventional Commits

```
feat(scope): nueva funcionalidad
fix(scope): corrección de bug
docs(scope): documentación
refactor(scope): restructuración sin cambio funcional
test(scope): agregar tests
chore(scope): mantenimiento
```

## Ejemplos

```bash
git commit -m "feat(auth): agregar refresh token endpoint"
git commit -m "fix(citas): corregir validación de horario"
git commit -m "docs(api): actualizar endpoints en README"
git commit -m "refactor(pacientes): extraer lógica a servicio"
git commit -m "test(citas): agregar tests para crear cita"
git commit -m "chore(deps): actualizar dependencias"
```

## Merge Strategy

```bash
# Actualizar dev con cambios remotos
git pull --rebase origin dev

# Si hay conflictos
git diff --name-only --diff-filter=U
# Editar archivos conflictivos
git add <archivo>
GIT_EDITOR=true git rebase --continue

# Push
git push origin dev
```

## Reglas

1. **NUNCA** commitear directo a `main`
2. **NUNCA** mezclar features no relacionadas
3. **SIEMPRE** build antes de commit
4. Push tras tests pasados — **confirmar con el usuario antes del primer push de la sesión**, salvo autorización previa explícita
5. **Commits pequeños** y descriptivos
