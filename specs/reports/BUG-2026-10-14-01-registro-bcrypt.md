# Verificación · BUG-2026-10-14-01

Fecha: 2026-10-14 (America/Santiago). Implementación y verificación propia: DG (Codex).
Pendiente revisión por un segundo integrante; este informe no representa esa aprobación.

Spec: [registro bcrypt](../proposals/BUG-2026-10-14-01-registro-bcrypt.md).
Rama: `codex/fix-register-password-bytes`, desde `72d8d7e`.

## Resultado

La creación manual rechaza contraseñas de más de 72 bytes UTF-8 con HTTP 422 y
mensaje comprensible, antes de ejecutar el registro. El formulario bloquea su envío
con el mismo mensaje traducido. Bcrypt, los hashes y el login permanecen compatibles.

| Criterio | Evidencia | Resultado |
|---|---|---|
| CA1: límites válidos y login | `test_registro_hasta_72_bytes_permite_login_y_guarda_bcrypt`, 8 casos | cumple |
| CA2: 422 y ausencia de filas | `test_exceso_de_bytes_devuelve_422_sin_crear_filas`, 10 casos; `test_registro_invitado_rechaza_exceso_antes_de_consultar_bd`, 3 casos | cumple |
| CA3: ASCII, Unicode y mínimo | `test_register_password.py`, 10 casos | cumple |
| CA4: formulario bloquea exceso y permite 72 bytes | `app/register/page.test.tsx`, 6 casos | cumple |
| CA5: mensaje de API traducido | `translate-api-error.test.ts`, 7 idiomas | cumple |
| CA6: no truncar, bcrypt y duplicados | unitarias conservan entrada; integración verifica hash, login y 409; componente comprueba payload exacto | cumple |

El registro por invitación comparte el esquema y se verificó su rechazo antes de
cualquier consulta de base; no se probó aquí el alta completa con invitación válida.
La interfaz se verificó con React Testing Library/jsdom, sin revisión visual en un
navegador. El detector de Impeccable sobre la página modificada no encontró incidencias.

## TDD y comprobaciones

Antes de implementar, las pruebas nuevas quedaron en rojo:

- Backend: 18 fallidas, 13 aprobadas. Los casos de 73/128 bytes y Unicode reproducían
  HTTP 500; el de 129 caracteres carecía del mensaje acordado.
- Frontend: 10 fallidas, 3 aprobadas. El formulario enviaba contraseñas demasiado
  largas y el error de API quedaba oculto tras el mensaje genérico.

Después de implementar:

- **44 pruebas nuevas en verde:** 31 backend, 13 frontend.
- **`python3 scripts/qa.py --full`: salida 0**, con PostgreSQL temporal configurado
  mediante DATABASE_URL y TEST_DATABASE_URL y `PYTHON_DOTENV_DISABLED=1`.
- Backend completo: **621 passed, 12 skipped**, 1 warning, 24,82 s.
- Suite completa de Vitest aprobada; ESLint sin errores (1 warning).
- Compilación Next.js de producción aprobada; `npx tsc --noEmit` aprobado.
- Mypy: sin incidencias en 121 archivos fuente.
- Ruff sobre `backend/src` y sobre los tres archivos de pruebas nuevos: sin errores.
- `git diff --check`: limpio.

El QA conserva un aviso no bloqueante de Ruff: **25 hallazgos en archivos no
modificados** (arranque, scripts, migración base y pruebas anteriores). Se comprobó
que ninguno corresponde a los archivos de esta corrección. No se corrigieron como
parte de este defecto.

Entorno: Python 3.14.7, bcrypt 5.0.0, PostgreSQL 17 local temporal. Todas las pruebas
de integración nuevas se ejecutaron contra una base cuyo nombre contiene `test`,
con Alembic hasta `head`, sin utilizar la base de desarrollo ni producción.
No se repitió la ejecución en Python 3.12, versión de referencia documentada.

Comandos de pruebas específicas (desde sus respectivos directorios):

```bash
# backend, con TEST_DATABASE_URL de una base temporal de pruebas
python -m pytest -q tests/test_register_password.py tests/integration/test_register_password_route.py tests/security/test_register_password_seguridad.py
# frontend
npm test -- src/app/register/page.test.tsx src/lib/translate-api-error.test.ts
```

## Entrega y pendientes

Documentación del comportamiento en [auth-app.md](../../docs/auth-app.md).
No hay migraciones ni cambios de dependencias. La corrección se limita al registro:
los demás flujos de credenciales no cambian.

- Código y pruebas implementados y verificados localmente.
- Pendientes: push/PR, revisión de segundo integrante, evidencia Trello y despliegue.
- Estado de la tarea: `in_progress`, no `done` por su propio autor.
