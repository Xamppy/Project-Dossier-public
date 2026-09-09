---
name: systematic-debugging
description: "Root-cause-first debugging: 4 phases (investigate, pattern analysis, hypothesis+test, implement), rule of 3 (3 failed fixes = architecture problem), red-flag phrases that mean stop and restart. Use for any non-trivial bug, never for pure typos."
version: 1.0.0
license: MIT
metadata:
  tags: [debugging, root-cause, hypothesis-testing]
  related_skills: [python-debugpy, test-driven-development]
---

# Systematic Debugging

## Ley de Hierro

```
NO HAY FIXES SIN INVESTIGACIÓN DE CAUSA RAÍZ PRIMERO
```

## Las 4 Fases

### Fase 1: Investigar Causa Raíz

```bash
# 1. Leer el error completo
# 2. Reproducir consistentemente
git log --oneline -10          # Cambios recientes
git diff                       # Cambios sin commit
grep -r "error_message" src/   # Buscar en código

# 3. Trazar flujo de datos
# ¿De dónde viene el valor incorrecto?
# ¿Qué función lo genera?
# ¿Dónde se consume?
```

### Fase 2: Análisis de Patrones

```bash
# Encontrar código que SÍ funciona de forma similar
grep -r "patron_similar" src/
# Comparar con el código roto
# Identificar DIFERENCIAS
```

### Fase 3: Hipótesis y Testing

```
1. Formular UNA hipótesis clara
2. Hacer el CAMBIO MÍNIMO para probar
3. ¿Funcionó? → Fase 4
4. ¿No funcionó? → Nueva hipótesis (NO agregar más fixes)
```

### Fase 4: Implementación

```bash
# 1. Test que falle primero (RED)
# 2. Fix el código (GREEN)
# 3. Refactor
# 4. Verificar
python manage.py test
npm run build
```

## Regla de las 3

Si 3 fixes fallaron → **el problema es de ARQUITECTURA**, no de código.

Preguntar: ¿Es este patrón fundamentalmente correcto?

## Red Flags — PARAR

- "Solo intenta esto rápido"
- "Probemos a ver qué pasa"
- "No entiendo del todo pero esto podría funcionar"
- "Ya intenté 3 cosas"

**→ TODOS significan: PARAR. Volver a Fase 1.**
