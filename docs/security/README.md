# Seguridad

Estado verificado el **07-09-2026**. Este archivo se actualiza a medida que las tareas del
objetivo OE8 se van cerrando.

## Estado de los cuatro controles comprometidos

El objetivo específico 8 compromete cuatro controles. **Solo uno existe.**

| Control | Estado | Tarea | Evidencia |
|---|---|---|---|
| Control de acceso | **implementado** | — | JWT firmado, RBAC con roles admin/user/viewer, aislamiento por organización, pruebas en `test_rbac.py` |
| Limitación de tasa | **ausente** | S5.8 | No hay slowapi ni middleware equivalente |
| Registro de auditoría | **ausente** | S4.10, S6.6 | No hay tabla ni servicio |
| Retención de 24 h con borrado verificado | **diverge** | S6.5 | Hoy 7 a 90 días, sin verificación de borrado |

## Hallazgos abiertos

### Token de acceso de 7 días en `localStorage`

`backend/src/dossier/security/jwt_tokens.py:41`

```python
minutes = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))  # 7 días por defecto
```

El token se guarda en `localStorage` (`frontend/src/app/dashboard/DashboardAuthGate.tsx`). Un
token de larga vida en almacenamiento accesible por script amplía el impacto de cualquier XSS.

Los tokens de restablecimiento y verificación sí usan 15 minutos (`jwt_tokens.py:66` y `:90`):
el token de acceso es el que queda fuera de esa política.

**Cierra en:** S3.9 — vida corta más renovación.

### CORS con métodos abiertos

`backend/src/dossier/api/app.py:211-215`

```python
CORSMiddleware,
allow_origins=_cors_origins,
allow_credentials=True,
allow_methods=["*"],
```

`allow_methods=["*"]` junto a `allow_credentials=True`. El parseo de orígenes sí está bien
resuelto (`_parse_cors_origins`, línea 102: limpia BOM, comillas tipográficas y barra final).

**Cierra en:** S3.8 — lista explícita de métodos.

### Retención por debajo de lo exigido

`backend/src/dossier/services/dossier_retention.py`

```python
ALLOWED_DOSSIER_RETENTION_DAYS = frozenset({7, 14, 30, 90})
DEFAULT_DOSSIER_RETENTION_DAYS = 30
```

`None` significa conservar indefinidamente. La especificación exige **24 horas con borrado
verificado**. Hoy el mínimo es 7 días y el borrado no se verifica: solo se ejecuta.

**Cierra en:** S6.5.

### Sin rastro de acceso a datos personales

El sistema trata datos de personas identificables (PDL, Lusha, registros corporativos, prensa)
y no registra quién accedió a qué. Las coincidencias de «audit» en el código son texto de
instrucciones al modelo y un comentario.

**Cierra en:** S4.10, y se extiende en S6.6 a envíos de correo y borrados por retención.

### Rutas legadas

`backend/src/dossier/security/legacy_routes.py` con `assert_legacy_route_allowed()`, controlado
por `DOSSIER_ENABLE_LEGACY_OPEN_ROUTES`. Están bien acotadas y hay prueba
(`test_legacy_routes.py`), pero deben retirarse.

**Cierra en:** S1.6. Mantén la variable apagada mientras tanto.

## Reglas permanentes

1. **Credenciales solo en variables de entorno.** Nunca en el código, nunca en un commit. Si una
   credencial llega a un commit, hay que rotarla, no solo borrarla.
2. **Solo datos autorizados y ambientes de prueba.** Nunca datos reales de producción.
3. **Sin cobros reales.** Stripe únicamente en entorno de pruebas, y solo si S5.9 lo autoriza.
4. **`JWT_SECRET` de 16 caracteres como mínimo.** La API se niega a arrancar con menos
   (`assert_jwt_secret_configured`).
5. **Toda prueba de seguridad va a la CI.** Una regresión de seguridad debe bloquear la
   integración, no descubrirse en la defensa (S6.8).

## Verificación

Pruebas de seguridad y aislamiento: **S6.7** y **S6.8**. Hasta entonces, lo único que cubre este
frente es `test_rbac.py`.

Auditoría de dependencias (pendiente de S0.3 y S1.4):

```bash
cd backend  && pip-audit
cd frontend && npm audit
```
