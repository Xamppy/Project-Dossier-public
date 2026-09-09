# Estrategia de evolución del modelo de datos y migración

- **Fecha:** 2026-09-09
- **Estado:** aprobada
- **Responsable:** FO (con revisión de FD)
- **Tareas asociadas:** S0.10, S1.1, S4.5
- **Brechas que atiende:** B1 (Síntesis en Markdown), B4 (Trazabilidad)

---

## 1. Situación actual y diagnóstico

El esquema actual documentado en `backend/src/dossier/db/Migracion.md` y aplicado desde `backend/src/dossier/db/schema_patches.py` presenta las siguientes características:
- La tabla `dossiers` almacena el resultado generado en la columna `dossier_data` de tipo `JSONB`.
- Actualmente almacena:
  ```json
  {
    "format": "markdown",
    "body": "# Dossier...",
    "pipeline": "person_research",
    "billing": "charged",
    "cache": { "hit": false }
  }
  ```
- **Dependencia crítica de trigger en PostgreSQL:**
  En `dossiers`, el cobro de créditos se desencadena mediante un trigger SQL cuando `dossier_data->>'billing' != 'none'`. En `dossier_routes.py:91` existe una advertencia explícita sobre no duplicar este cobro en Python. Cualquier cambio en la estructura de `dossier_data` **debe preservar la clave `'billing'`** en la raíz para no romper el trigger financiero ni la facturación.
- La tabla `dossiers` posee columnas planas como `alerts` (`TEXT[]` o `JSONB`), `agents_activated` (`VARCHAR[]`), `agents_failed` (`VARCHAR[]`), pero carece de tablas normalizadas para consultas analíticas de trayectoria profesional y menciones de prensa.

---

## 2. Nuevas entidades en PostgreSQL (S4.5)

Para dar soporte analítico, trazabilidad granular por afirmación y persistencia relacional complementaria al JSON estructurado, se diseñan las siguientes tres tablas:

### 2.1. `dossier_risk_alerts`
```sql
CREATE TABLE dossier_risk_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dossier_id UUID NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    description TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dossier_alerts_dossier_id ON dossier_risk_alerts(dossier_id);
```

### 2.2. `dossier_career_positions`
```sql
CREATE TABLE dossier_career_positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dossier_id UUID NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    person_name VARCHAR(255) NOT NULL,
    role_title VARCHAR(255) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    start_date VARCHAR(50),
    end_date VARCHAR(50),
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    source_name VARCHAR(100),
    source_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dossier_career_dossier_id ON dossier_career_positions(dossier_id);
```

### 2.3. `dossier_press_mentions`
```sql
CREATE TABLE dossier_press_mentions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dossier_id UUID NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    headline VARCHAR(500) NOT NULL,
    publisher VARCHAR(255) NOT NULL,
    published_date DATE,
    summary TEXT NOT NULL,
    url TEXT NOT NULL,
    query_context VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_dossier_press_dossier_id ON dossier_press_mentions(dossier_id);
```

---

## 3. Transición de `dossier_data` (JSONB)

En lugar de reemplazar abruptamente la columna `dossier_data`, se adopta una migración no disruptiva de esquema:

1. **Estructura v2.0 en `dossier_data`:**
   ```json
   {
     "schema_version": "2.0.0",
     "format": "structured_json",
     "billing": "charged",
     "payload": {
       "executive_summary": "...",
       "corporate_records": [...],
       "press_mentions": [...],
       "risk_alerts": [...],
       "conversation_starters": [...]
     },
     "legacy_markdown_body": "# Dossier..."
   }
   ```
2. **Preservación del trigger de créditos:**
   La clave `"billing"` se mantiene en el primer nivel del documento JSONB, garantizando que `dossier_data->>'billing'` continúe funcionando idénticamente en el motor PostgreSQL.
3. **Retrocompatibilidad de lectura:**
   Los dossiers históricos con `{"format": "markdown"}` seguirán siendo legibles por el endpoint `GET /dossiers/{id}`, mapeándolos automáticamente mediante la capa de compatibilidad (S4.4).

---

## 4. Estrategia de migraciones con Alembic (S1.1)

Actualmente las modificaciones se aplican manualmente en `schema_patches.py`. La tarea **S1.1** introducirá Alembic con la siguiente convención:

1. `0001_initial_baseline.py`: Captura el estado exacto del esquema v1.0 existente en producción (tablas `organizations`, `users`, `dossiers`, `credit_ledger`, etc.).
2. `0002_dossier_entities.py`: Crea las tablas `dossier_risk_alerts`, `dossier_career_positions` y `dossier_press_mentions` con sus respectivos índices e integridad referencial.
3. Se desactiva progresivamente `DATABASE_AUTO_CREATE_TABLES` en favor del comando estandarizado `alembic upgrade head` en el arranque del despliegue en Render.
