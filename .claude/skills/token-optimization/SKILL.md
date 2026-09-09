---
name: token-optimization
description: "Token-saving strategies: concise CLAUDE.md, right model per task size, small tasks, fresh subagents per task, regular /compact. Use when a session is burning tokens fast or the user asks how to reduce cost."
version: 1.0.0
license: MIT
metadata:
  tags: [tokens, cost, context-management, model-selection]
---

# Ahorro de Tokens

## Estrategias

### 1. CLAUDE.md Conciso

```markdown
# MAL — 5000 palabras (carga en cada turno)
[Historia completa, decisiones archivadas, etc.]

# BIEN — 500 palabras (solo lo esencial)
[Stack, convenciones, comandos, reglas críticas]
```

### 2. Modelo Correcto por Tarea

| Tarea | Modelo | Tokens | Costo |
|-------|--------|--------|-------|
| Rename, typo | Sonnet 5 | ~100 | $0.001 |
| CRUD endpoint | Sonnet 5 | ~500 | $0.005 |
| Feature completa | Sonnet 5 | ~2000 | $0.02 |
| Diseñar BD | Fable 5 | ~3000 | $0.05 |
| Debugging complejo | Fable 5 | ~4000 | $0.06 |
| Code review | Fable 5 | ~2000 | $0.03 |

### 3. Tareas Pequeñas

```
MAL  — todo de una vez (acumula contexto): "Crea sistema completo de auth con JWT, RBAC, refresh tokens"

BIEN — dividir en pasos:
  1. "Crea modelo User con campos: email, password, role"
  2. "Crea endpoint login que retorne JWT"
  3. "Crea middleware que verifique JWT"
```

### 4. No Cargar Contexto Innecesario

```
MAL  — pedir que se analice todo el codebase de una vez sin acotar archivos
BIEN — especificar archivos: "Analiza auth/views.py, busca vulnerabilidades"
```

### 5. Comprimir Regularmente

```
/compact    # Comprimir contexto
/cost       # Ver consumo
```

### 6. Agent tool para Subagentes

```
# Cada subagente empieza con contexto limpio
Agent({subagent_type: "general-purpose", description: "Fix login bug", prompt: "..."})
Agent({subagent_type: "general-purpose", description: "Write tests for cart", prompt: "..."})
Agent({subagent_type: "general-purpose", description: "Update README", prompt: "..."})
# ~70% ahorro vs hacerlo todo en una sesión
```

## Comandos de Monitoreo

```
/cost       # Tokens gastados en sesión
/model      # Cambiar modelo
```
