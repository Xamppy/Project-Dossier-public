---
name: owasp-top10
description: "OWASP Top 10 audit checklist with grep probes per vulnerability class (A01-A10) and an audit report template. Use for a security pass on Django/Node projects, or when the user asks for an OWASP audit."
version: 1.0.0
license: MIT
metadata:
  tags: [security, owasp, audit, django, checklist]
  related_skills: [requesting-code-review]
---

# OWASP Top 10

## Checklist por Vulnerabilidad

### A01: Broken Access Control
```bash
# ¿Se verifica ownership?
grep -r "request.user" views.py
grep -r "permission_classes" views.py

# ¿Se validan roles?
grep -r "is_superuser\|rol ==" views.py
```

### A02: Cryptographic Failures
```bash
# ¿Secrets en env vars?
grep -r "SECRET_KEY\|API_KEY\|PASSWORD" --include="*.py" . | grep -v ".env"
grep -v "os.environ" settings.py

# ¿HTTPS forzado?
grep "SECURE_SSL_REDIRECT" settings.py
```

### A03: Injection
```bash
# ¿Validación de inputs?
grep -r "serializer\|Serializer" views.py
grep -r "Zod\|zod" --include="*.ts" .

# ¿SQL parametrizado?
grep -r "raw\|execute" --include="*.py" . | grep -v "migrations"
```

### A04: Insecure Design
```bash
# ¿Rate limiting?
grep -r "throttle\|rate_limit" views.py

# ¿Brute force protection?
grep -r "login.*attempt\|lockout" .
```

### A05: Security Misconfiguration
```bash
# ¿DEBUG = False en producción?
grep "DEBUG" settings.py

# ¿Errores internos expuestos?
grep "DEBUG" settings.py
```

### A06: Vulnerable Components
```bash
npm audit
pip-audit
```

### A07: Auth Failures
```bash
# ¿JWT config correcta?
grep "JWT" settings.py
grep "ACCESS_TOKEN" settings.py

# ¿Refresh token rotation?
grep "refresh" --include="*.py" -r .
```

### A08: Software Integrity
```bash
# ¿CI/CD validation?
cat .github/workflows/ci.yml
```

### A09: Logging & Monitoring
```bash
# ¿Se loguea lo correcto?
grep -r "logger\.\|logging\." --include="*.py" . | head -20
```

### A10: SSRF
```bash
# ¿URL validation?
grep -r "requests\.get\|fetch(" --include="*.py" .
# ¿Se valida la URL antes de hacer request?
```

## Template de Auditoría

```markdown
# Auditoría OWASP — [Proyecto]

## Fecha: [fecha]
## Auditor: Claude Code

### A01: Broken Access Control
- [ ] Ownership verificado en endpoints
- [ ] Roles implementados
- [ ] No horizontal privilege escalation

### A02: Cryptographic Failures
- [ ] Secrets en .env
- [ ] HTTPS forzado
- [ ] Passwords hasheados (bcrypt/argon2)

### A03: Injection
- [ ] Inputs validados
- [ ] SQL parametrizado
- [ ] No eval() en código

[... completar para A04-A10 ...]

## Hallazgos
1. [descripción]
2. [descripción]

## Recomendaciones
1. [descripción]
2. [descripción]
```
