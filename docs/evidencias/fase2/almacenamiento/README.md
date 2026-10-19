# Evidencia: almacenamiento de datos en PostgreSQL

Atiende la observación del docente: «sin ello no es posible verificar [...] el almacenamiento de datos».
Todo se ejecutó el 2026-10-19 sobre el commit `9f6c69250fbff63b7375d965d5692cf1c494ff30`, contra
**`dossier_evid_test`**, una base PostgreSQL 18.6 local creada solo para esta evidencia y borrada al
terminar. La contraseña de la base nunca aparece: los comandos muestran `postgres:***`.

Solo datos ficticios (`example.com`, `example.org`, «Ana Prueba», «Empresa de Prueba SA»). Los hashes
de contraseña se truncan a 12 caracteres y los tokens JWT se muestran solo con su prefijo de cabecera.

## 1. La suite backend contra una base real

| Evidencia | Resultado |
|---|---|
| [01-pytest-sin-postgres.txt](01-pytest-sin-postgres.txt) · [png](01-pytest-sin-postgres.png) | Sin `TEST_DATABASE_URL` (como corre hoy la CI): **659 passed, 121 skipped** en 61,6 s. |
| [02-pytest-con-postgres.txt](02-pytest-con-postgres.txt) · [png](02-pytest-con-postgres.png) | Con `TEST_DATABASE_URL` apuntando a `dossier_evid_test`: **768 passed, 12 skipped** en 96,1 s. |
| [03-pruebas-postgres-por-archivo.txt](03-pruebas-postgres-por-archivo.txt) · [png](03-pruebas-postgres-por-archivo.png) | Comparación prueba por prueba de las dos salidas: **109 pruebas** pasan de omitidas a **aprobadas** con Postgres, **0** fallan. |

De las 121 omitidas sin base, 109 dependen de Postgres (fixture `pg_vacia` de `backend/tests/conftest.py`).
Las otras 12 siguen omitidas con base porque esperan su tarea del plan (S2.4, S3.9, S4.10, S5.8, S6.5,
S6.6, S6.7); el motivo está en cada línea `SKIPPED` del resumen.

Las 109 pruebas con base incluyen: `alembic upgrade head` sobre base vacía (`test_job_queue_migracion.py`,
`test_dossier_entities_migracion.py`), el registro con bcrypt hasta 72 bytes y su login
(`test_register_password_route.py`, 18), los indicadores del dashboard calculados con SQL real
(`test_dashboard_summary.py`, 36), el progreso persistido de jobs de personas y calendario, el canal SSE
y pruebas de seguridad y estrés sobre la cola de trabajos.

## 2. Filas reales en las tablas clave

| Paso | Evidencia | Qué hace |
|---|---|---|
| 1 | [04-generar-datos-ficticios.txt](04-generar-datos-ficticios.txt) · [png](04-generar-datos-ficticios.png) | `backend/scripts/generar_fixtures_progreso.py`: recrea el esquema con `alembic upgrade head` y procesa **8 jobs reales** (worker, grafo corporativo, investigación de personas y guardado) con **todos los proveedores simulados** y sin red. El *traceback* «Companies House no responde» es intencional: el escenario `calendario-agente-caido` simula la caída del agente UK. |
| 2 | [05-registrar-cuentas-ficticias.txt](05-registrar-cuentas-ficticias.txt) · [png](05-registrar-cuentas-ficticias.png) | [`_herramientas/registrar_usuario_ficticio.py`](../_herramientas/registrar_usuario_ficticio.py): dos cuentas por la ruta real `POST /auth/register` (TestClient de FastAPI), una de empresa y una personal. Ambas HTTP 200. |
| 3 | [06-consultas-tablas-clave.txt](06-consultas-tablas-clave.txt) · [png](06-consultas-tablas-clave.png) | [`_herramientas/consultas_almacenamiento.sql`](../_herramientas/consultas_almacenamiento.sql) con `psql`. |

Lo que muestran las consultas:

- **organizations:** 3 filas. `org-fixtures` (plan `pro`, saldo inicial 1000) y las dos organizaciones que
  creó el registro, con `settings` JSONB (`{"email_domain": "example.org", "workspace_kind": "work"}`).
- **users:** 3 filas. Las dos cuentas registradas guardan `password_hash` bcrypt (`$2b$12$…`, 60 caracteres);
  la de fixtures no tiene contraseña. `org_memberships` las une a su organización con rol `admin`.
- **dossier_generation_jobs:** 8 jobs: 5 `completed`, 2 `failed` y 1 `cancelled`, con créditos estimados y
  consumidos, mensaje de error cuando corresponde y el progreso por etapas guardado en
  `result_payload->'_progress'` (scopes, etapas y etapas completadas).
- **dossiers:** 10 filas con `dossier_data` JSONB (`format = markdown`, de 1,0 a 2,6 kB, 11 a 13 claves de primer nivel).
- **credit_ledger:** 6 asientos `dossier_generation` creados por los *triggers* de la base al insertar
  dossiers con créditos consumidos. El saldo de `org-fixtures` pasa de 1000 a **992**, y coincide con la suma
  de `credits_consumed` (8) y con la suma del ledger (−8).

**Observación encontrada al revisar los datos (no corregida aquí).** Los dos primeros asientos (−3 de la
empresa y −1 de la persona, del mismo job de calendario e insertados en el mismo instante) muestran el mismo
`balance_after = 996`; el primero debería decir 997. Explicación probable: `fn_credit_ledger_after_dossier_insert`
es un trigger `AFTER INSERT ... FOR EACH ROW` que lee `organizations.credits_balance` en el momento en que se
dispara; si SQLAlchemy inserta ambos dossiers en una sola sentencia, los dos `BEFORE` (débito) ya corrieron
cuando se disparan los `AFTER`, y ambos leen el saldo final. El saldo de la organización sí queda correcto.
Conviene registrarlo como hallazgo en el harness.

## Cómo reproducir

```bash
createdb dossier_evid_test
export TEST_DATABASE_URL=postgresql://postgres:<clave>@localhost:5432/dossier_evid_test
cd backend && python -m pytest -v -p no:cacheprovider          # suite con Postgres
cd .. && python backend/scripts/generar_fixtures_progreso.py    # reescribe specs/fixtures/S5.10-progreso: descartar con git checkout
python docs/evidencias/fase2/_herramientas/registrar_usuario_ficticio.py
psql -d dossier_evid_test -f docs/evidencias/fase2/_herramientas/consultas_almacenamiento.sql
dropdb dossier_evid_test
```

El generador sobrescribe las fixtures de `specs/fixtures/S5.10-progreso/`. En esta corrida solo cambiaron
los identificadores aleatorios `external_event_id` de siete archivos, y se restauraron con `git checkout`:
esta evidencia no modifica las fixtures del repositorio.
