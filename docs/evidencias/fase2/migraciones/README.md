# Evidencia: migraciones versionadas con Alembic

Atiende la observación del docente sobre **las migraciones**. Ejecutado el 2026-10-19 sobre el commit
`9f6c69250fbff63b7375d965d5692cf1c494ff30`, contra `dossier_evid_test`: una base PostgreSQL 18.6 local
creada vacía para esta evidencia y borrada al terminar. Los comandos muestran la URL con `postgres:***`;
Alembic también enmascara la contraseña en su propia salida.

## Relación entre `db/schema_patches.py` y Alembic

`db/Migracion.md` es el DDL histórico de referencia (16 tablas, vistas y triggers de cobro).
`db/schema_patches.py` contiene los parches idempotentes (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`)
que la aplicación sigue aplicando al arrancar para bases creadas antes de S1.1. Desde S1.1 el esquema se
versiona con Alembic: la línea base `a3f1c9e2b7d4` copia literalmente el DDL de `Migracion.md` y luego
ejecuta la tupla de `schema_patches.py`. Las revisiones siguientes (`b7e2d4f1a9c3`, `c4d8a2f6b1e9`) también
reutilizan esa tupla, para que una base nueva hecha con `alembic upgrade head` quede igual a una existente
parchada al arrancar (ver el docstring de cada revisión en [02-alembic-history.txt](02-alembic-history.txt)).

## Secuencia ejecutada

| # | Evidencia | Resultado |
|---|---|---|
| 0 | [00-crear-base.txt](00-crear-base.txt) · [png](00-crear-base.png) | `createdb dossier_evid_test` y `\dt`: «Did not find any tables». |
| 1 | [01-alembic-heads.txt](01-alembic-heads.txt) · [png](01-alembic-heads.png) | Una sola cabeza: `c4d8a2f6b1e9 (head)`. |
| 2 | [02-alembic-history.txt](02-alembic-history.txt) · [png](02-alembic-history.png) | Cadena lineal de 3 revisiones: `a3f1c9e2b7d4` (línea base S1.1) → `b7e2d4f1a9c3` (S4.5, entidades del dossier) → `c4d8a2f6b1e9` (BUG-2026-10-05-01, cola de trabajos). |
| 3 | [03-alembic-current-antes.txt](03-alembic-current-antes.txt) · [png](03-alembic-current-antes.png) | Sin revisión actual: base vacía. |
| 4 | [04-alembic-upgrade-head.txt](04-alembic-upgrade-head.txt) · [png](04-alembic-upgrade-head.png) | `Running upgrade -> a3f1c9e2b7d4`, `-> b7e2d4f1a9c3`, `-> c4d8a2f6b1e9`. Código de salida 0. |
| 5 | [05-alembic-current-despues.txt](05-alembic-current-despues.txt) · [png](05-alembic-current-despues.png) | `alembic current` = `c4d8a2f6b1e9 (head)` y `alembic_version.version_num` = `c4d8a2f6b1e9`. |
| 6 | [06-tablas-vistas.txt](06-tablas-vistas.txt) · [png](06-tablas-vistas.png) | `\dt`: **23 tablas** (22 del sistema + `alembic_version`); `\dv`: 2 vistas; `\df`: funciones (la mayoría son de las extensiones `pgcrypto` y `uuid-ossp`). |
| 7 | [07-describe-tablas-principales.txt](07-describe-tablas-principales.txt) · [png](07-describe-tablas-principales.png) | `\d+` de `organizations`, `users`, `dossiers`, `dossier_generation_jobs` y `credit_ledger`: columnas, tipos, índices, claves foráneas, CHECK y triggers. El PNG muestra las primeras 260 líneas. |
| 8 | [08-columnas-information-schema.txt](08-columnas-information-schema.txt) · [png](08-columnas-information-schema.png) | `information_schema.columns`: columnas por tabla y el detalle de las 22 tablas (tipo, nulabilidad, valor por omisión). El PNG muestra las primeras 230 líneas. |
| 9 | [09-triggers-y-funciones-propias.txt](09-triggers-y-funciones-propias.txt) · [png](09-triggers-y-funciones-propias.png) | Base recreada desde cero y migrada otra vez: los **9 triggers** (7 de `updated_at`, débito de créditos `BEFORE INSERT` y asiento en `credit_ledger` `AFTER INSERT` sobre `dossiers`) y las **3 funciones propias** que no vienen de una extensión. |

La evidencia 9 se tomó después de correr la suite de pruebas, que recrea el esquema de la base de prueba;
por eso el comando parte con `DROP SCHEMA public CASCADE` (el `NOTICE` lista lo que había) y vuelve a
aplicar `alembic upgrade head` antes de consultar.

## Modelo de datos

[modelo-datos.md](modelo-datos.md) tiene el diagrama entidad-relación como `erDiagram` de Mermaid (GitHub lo
renderiza) y [modelo-datos.png](modelo-datos.png) es la misma figura en imagen. Se generó desde los metadatos
de SQLAlchemy (`backend/src/dossier/db/models.py`): **14 tablas y 24 relaciones**. El ORM no declara 8 de
las 22 tablas de la base; el detalle está en `modelo-datos.md`.

## Cómo reproducir

```bash
createdb dossier_evid_test
export DATABASE_URL=postgresql://postgres:<clave>@localhost:5432/dossier_evid_test
cd backend
python -m alembic heads --verbose
python -m alembic history --verbose
python -m alembic current --verbose
python -m alembic upgrade head
python -m alembic current --verbose
psql -d dossier_evid_test -c "\dt" -c "\dv"
python ../docs/evidencias/fase2/_herramientas/er.py > modelo.mmd     # diagrama ER
dropdb dossier_evid_test
```

Las salidas se capturaron con [`_herramientas/ev.py`](../_herramientas/ev.py), que guarda la salida literal
en `.txt` y la renderiza a `.png` con Chrome sin interfaz.
