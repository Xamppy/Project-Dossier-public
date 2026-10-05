"""Linea base (S1.1): esquema completo segun db/Migracion.md + schema_patches.py.

Revision ID: a3f1c9e2b7d4
Revises:
Create Date: 2026-09-23

Por que esta migracion no viene de `alembic revision --autogenerate`
----------------------------------------------------------------------
Un primer intento de generar la migracion de linea base con
`--autogenerate` comparo Postgres vacio contra `Base.metadata`
(`db/models.py`), y produjo una migracion que solo crea 10 tablas.

Al contrastar contra `backend/src/dossier/db/Migracion.md` -- citado como
la fuente de verdad del DDL en el docstring de `db/models.py`, y
corroborado por SQL crudo contra `credit_ledger` y `dossier_alerts` en
`services/account_service.py` -- se confirmo que la base real tiene 16
tablas, 2 vistas y 8 triggers/funciones, incluyendo el mecanismo real de
cobro de creditos (`fn_debit_credits_on_dossier`,
`fn_credit_ledger_after_dossier_insert`) sobre la tabla `dossiers`. Los
modelos ORM en `db/models.py` solo declaran ~10 de esas 16 tablas y
ninguno de los triggers.

Por eso esta migracion de linea base NO se generó por autogenerate, sino
que se escribio a mano, en dos partes, en el mismo orden en que hoy se
aplican al arrancar la app (ver `api/app.py:lifespan()`):

1. El DDL completo de `db/Migracion.md` (extensiones, 16 tablas, indices,
   funciones/triggers de `updated_at` y de cobro de creditos, y las 2
   vistas), ejecutado tal cual via `op.execute()` -- una migracion de
   base de datos es una foto fija, asi que el SQL se copia literal aqui
   en vez de leer el .md en tiempo de ejecucion (que si puede cambiar).
2. Los parches idempotentes de `db/schema_patches.py` (columnas
   agregadas despues de escrito Migracion.md, mas las tablas
   `dossier_shares` y `org_invites`, que tampoco estan en Migracion.md),
   reutilizando ese modulo directamente para no duplicar su texto y para
   que esta migracion nunca quede desincronizada de lo que la app
   realmente ejecuta hoy.

Hallazgo derivado (no corregido en esta tarea, solo documentado): los
modelos SQLAlchemy en `db/models.py` estan desactualizados respecto al
esquema real/documentado -- les faltan ~9-12 tablas y los 8
triggers/funciones. Mientras eso no se corrija, un futuro
`alembic revision --autogenerate` comparara contra una metadata
incompleta y podria proponer *borrar* las tablas que faltan en el ORM.
Ver hallazgo de seguimiento en progress.md.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "a3f1c9e2b7d4"
down_revision = None
branch_labels = None
depends_on = None


# =============================================================================
# PARTE 1 -- DDL completo de db/Migracion.md (copiado literal, ver docstring)
# =============================================================================
_BASELINE_SQL = r"""
-- =============================================================================
-- PROJECT DOSSIER — Schema de Base de Datos PostgreSQL
-- Versión: 1.0 | Basado en: Project Dossier Especificaciones v2.0
-- Empresa: Alloxentric
-- =============================================================================

-- =============================================================================
-- EXTENSIONES REQUERIDAS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- SECCIÓN 1: ORGANIZACIÓN Y MULTI-TENANCY
-- =============================================================================

CREATE TABLE organizations (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(255)    NOT NULL,
    slug                VARCHAR(100)    NOT NULL UNIQUE,
    plan                VARCHAR(20)     NOT NULL DEFAULT 'free'
                        CHECK (plan IN ('free', 'pro', 'enterprise')),
    credits_balance     INTEGER         NOT NULL DEFAULT 10
                        CHECK (credits_balance >= 0),
    credits_monthly_limit INTEGER       NOT NULL DEFAULT 10,
    stripe_customer_id  VARCHAR(255)    UNIQUE,
    stripe_subscription_id VARCHAR(255) UNIQUE,
    is_white_label      BOOLEAN         NOT NULL DEFAULT FALSE,
    custom_domain       VARCHAR(255),
    settings            JSONB           NOT NULL DEFAULT '{}',
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE organizations IS 'Tabla principal de tenants. Cada organización es un cliente independiente del sistema multi-tenant.';

CREATE INDEX idx_organizations_slug ON organizations(slug);
CREATE INDEX idx_organizations_plan ON organizations(plan);
CREATE INDEX idx_organizations_stripe_customer ON organizations(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;

-- =============================================================================
-- SECCIÓN 2: USUARIOS Y AUTENTICACIÓN
-- =============================================================================

CREATE TABLE users (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    email               VARCHAR(255)    NOT NULL UNIQUE,
    email_verified      BOOLEAN         NOT NULL DEFAULT FALSE,
    password_hash       VARCHAR(255),
    full_name           VARCHAR(255),
    avatar_url          TEXT,
    timezone            VARCHAR(100)    NOT NULL DEFAULT 'UTC',
    locale              VARCHAR(10)     NOT NULL DEFAULT 'en',
    last_login_at       TIMESTAMPTZ,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    is_platform_admin BOOLEAN         NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS 'Usuarios del sistema. Un usuario puede pertenecer a múltiples organizaciones con distintos roles.';

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_active ON users(is_active) WHERE is_active = TRUE;

CREATE TABLE org_memberships (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role                VARCHAR(20)     NOT NULL DEFAULT 'user'
                        CHECK (role IN ('admin', 'user', 'viewer', 'api_user')),
    is_primary_org      BOOLEAN         NOT NULL DEFAULT FALSE,
    invited_by_user_id  UUID            REFERENCES users(id),
    joined_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id)
);

COMMENT ON TABLE org_memberships IS 'Tabla puente para RBAC: define el rol de cada usuario dentro de cada organización.';

CREATE INDEX idx_memberships_org ON org_memberships(organization_id);
CREATE INDEX idx_memberships_user ON org_memberships(user_id);
CREATE UNIQUE INDEX idx_memberships_primary_org
    ON org_memberships(user_id)
    WHERE is_primary_org = TRUE;

-- =============================================================================
-- SECCIÓN 3: AUTENTICACIÓN OAUTH Y SESIONES
-- =============================================================================

CREATE TABLE oauth_accounts (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider            VARCHAR(50)     NOT NULL
                        CHECK (provider IN ('google', 'microsoft', 'linkedin')),
    provider_user_id    VARCHAR(255)    NOT NULL,
    access_token        TEXT,
    refresh_token       TEXT,
    token_expires_at    TIMESTAMPTZ,
    scopes              TEXT[],
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

CREATE INDEX idx_oauth_user ON oauth_accounts(user_id);

CREATE TABLE refresh_tokens (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    token_hash          VARCHAR(255)    NOT NULL UNIQUE,
    expires_at          TIMESTAMPTZ     NOT NULL,
    is_revoked          BOOLEAN         NOT NULL DEFAULT FALSE,
    ip_address          INET,
    user_agent          TEXT,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash);
CREATE INDEX idx_refresh_tokens_expires ON refresh_tokens(expires_at)
    WHERE is_revoked = FALSE;

-- =============================================================================
-- SECCIÓN 4: API KEYS (Enterprise)
-- =============================================================================

CREATE TABLE api_keys (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by_user_id  UUID            NOT NULL REFERENCES users(id),
    name                VARCHAR(255)    NOT NULL,
    key_prefix          VARCHAR(10)     NOT NULL,
    key_hash            VARCHAR(255)    NOT NULL UNIQUE,
    permissions         TEXT[]          NOT NULL DEFAULT '{}',
    rate_limit_per_hour INTEGER         NOT NULL DEFAULT 100,
    last_used_at        TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ,
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_keys_org ON api_keys(organization_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);

-- =============================================================================
-- SECCIÓN 5: CONTACTOS (ADDRESS BOOK)
-- =============================================================================

CREATE TABLE contacts (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by_user_id  UUID            NOT NULL REFERENCES users(id),
    email               VARCHAR(255),
    full_name           VARCHAR(255),
    linkedin_url        VARCHAR(500),
    company             VARCHAR(255),
    job_title           VARCHAR(255),
    domain              VARCHAR(255),
    tags                TEXT[]          NOT NULL DEFAULT '{}',
    is_vip              BOOLEAN         NOT NULL DEFAULT FALSE,
    notes               TEXT,
    last_dossier_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE contacts IS 'Address Book de la organización. Cada contacto puede tener múltiples dossiers generados a lo largo del tiempo.';

CREATE INDEX idx_contacts_org ON contacts(organization_id);
CREATE INDEX idx_contacts_email ON contacts(organization_id, email) WHERE email IS NOT NULL;
CREATE INDEX idx_contacts_domain ON contacts(organization_id, domain) WHERE domain IS NOT NULL;
CREATE INDEX idx_contacts_tags ON contacts USING GIN(tags);
CREATE INDEX idx_contacts_vip ON contacts(organization_id, is_vip) WHERE is_vip = TRUE;

-- =============================================================================
-- SECCIÓN 6: DOSSIERS
-- =============================================================================

CREATE TABLE dossiers (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    requested_by_user_id UUID           NOT NULL REFERENCES users(id),
    contact_id          UUID            REFERENCES contacts(id) ON DELETE SET NULL,
    subject_email       VARCHAR(255),
    subject_name        VARCHAR(255),
    module_identity     BOOLEAN         NOT NULL DEFAULT TRUE,
    module_corporate    BOOLEAN         NOT NULL DEFAULT FALSE,
    module_media        BOOLEAN         NOT NULL DEFAULT FALSE,
    depth_level         VARCHAR(10)     NOT NULL DEFAULT 'basic'
                        CHECK (depth_level IN ('basic', 'standard', 'deep')),
    credits_consumed    INTEGER         NOT NULL DEFAULT 0
                        CHECK (credits_consumed >= 0),
    status              VARCHAR(20)     NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'complete', 'partial', 'failed')),
    status_message      TEXT,
    dossier_data        JSONB,
    alerts              JSONB           NOT NULL DEFAULT '[]',
    agents_activated    TEXT[]          NOT NULL DEFAULT '{}',
    agents_failed       TEXT[]          NOT NULL DEFAULT '{}',
    data_sources_used   TEXT[]          NOT NULL DEFAULT '{}',
    generation_started_at TIMESTAMPTZ,
    generation_completed_at TIMESTAMPTZ,
    generation_duration_ms INTEGER,
    cache_key           VARCHAR(255),
    cached_until        TIMESTAMPTZ,
    trigger_source      VARCHAR(20)     NOT NULL DEFAULT 'manual'
                        CHECK (trigger_source IN ('manual', 'calendar', 'api', 'extension')),
    calendar_event_id   UUID,
    email_sent          BOOLEAN         NOT NULL DEFAULT FALSE,
    email_sent_at       TIMESTAMPTZ,
    email_recipients    TEXT[]          NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE dossiers IS 'Tabla central del sistema. Registra cada solicitud de dossier con su configuración, estado, resultado y metadatos de auditoría.';

CREATE INDEX idx_dossiers_org ON dossiers(organization_id);
CREATE INDEX idx_dossiers_user ON dossiers(requested_by_user_id);
CREATE INDEX idx_dossiers_contact ON dossiers(contact_id) WHERE contact_id IS NOT NULL;
CREATE INDEX idx_dossiers_status ON dossiers(organization_id, status);
CREATE INDEX idx_dossiers_subject_email ON dossiers(organization_id, subject_email);
CREATE INDEX idx_dossiers_created ON dossiers(organization_id, created_at DESC);
CREATE INDEX idx_dossiers_alerts ON dossiers USING GIN(alerts);
CREATE INDEX idx_dossiers_cache_key ON dossiers(cache_key) WHERE cache_key IS NOT NULL;

-- =============================================================================
-- SECCIÓN 7: LÍNEA DE TIEMPO PROFESIONAL (Módulo A/B)
-- =============================================================================

CREATE TABLE dossier_career_entries (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    company_name        VARCHAR(255)    NOT NULL,
    job_title           VARCHAR(255),
    start_date          DATE,
    end_date            DATE,
    tenure_months       INTEGER,
    is_current          BOOLEAN         NOT NULL DEFAULT FALSE,
    gap_months_after    INTEGER,
    has_discrepancy     BOOLEAN         NOT NULL DEFAULT FALSE,
    discrepancy_detail  TEXT,
    source              VARCHAR(50),
    sort_order          INTEGER         NOT NULL DEFAULT 0
);

CREATE INDEX idx_career_dossier ON dossier_career_entries(dossier_id);

-- =============================================================================
-- SECCIÓN 8: REGISTROS CORPORATIVOS (Módulo B)
-- =============================================================================

CREATE TABLE dossier_corporate_records (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    company_name        VARCHAR(255)    NOT NULL,
    company_number      VARCHAR(100),
    country             VARCHAR(3)      NOT NULL,
    jurisdiction        VARCHAR(100),
    role_in_company     VARCHAR(255),
    company_status      VARCHAR(50),
    incorporation_date  DATE,
    appointment_date    DATE,
    resignation_date    DATE,
    insolvency_flag     BOOLEAN         NOT NULL DEFAULT FALSE,
    source_api          VARCHAR(50),
    source_url          TEXT,
    raw_data            JSONB
);

CREATE INDEX idx_corporate_dossier ON dossier_corporate_records(dossier_id);
CREATE INDEX idx_corporate_insolvency ON dossier_corporate_records(dossier_id, insolvency_flag)
    WHERE insolvency_flag = TRUE;

-- =============================================================================
-- SECCIÓN 9: ICE BREAKERS (Módulo C)
-- =============================================================================

CREATE TABLE dossier_ice_breakers (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    content             TEXT            NOT NULL,
    source_url          TEXT,
    source_type         VARCHAR(50),
    sort_order          INTEGER         NOT NULL DEFAULT 0
);

CREATE INDEX idx_icebreakers_dossier ON dossier_ice_breakers(dossier_id);

-- =============================================================================
-- SECCIÓN 10: INTEGRACIONES DE CALENDARIO
-- =============================================================================

CREATE TABLE calendar_integrations (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider            VARCHAR(20)     NOT NULL
                        CHECK (provider IN ('google', 'microsoft')),
    calendar_id         VARCHAR(500),
    is_enabled          BOOLEAN         NOT NULL DEFAULT TRUE,
    advance_minutes     INTEGER         NOT NULL DEFAULT 30
                        CHECK (advance_minutes IN (15, 30, 60, 1440)),
    skip_internal_meetings  BOOLEAN     NOT NULL DEFAULT TRUE,
    skip_recurring_after_first BOOLEAN  NOT NULL DEFAULT TRUE,
    min_attendees       INTEGER         NOT NULL DEFAULT 1
                        CHECK (min_attendees >= 1),
    domain_whitelist    TEXT[]          NOT NULL DEFAULT '{}',
    domain_blacklist    TEXT[]          NOT NULL DEFAULT '{}',
    default_depth       VARCHAR(10)     NOT NULL DEFAULT 'standard'
                        CHECK (default_depth IN ('basic', 'standard', 'deep')),
    auto_send_email     BOOLEAN         NOT NULL DEFAULT TRUE,
    email_cc_assistant  VARCHAR(255),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, provider, calendar_id)
);

CREATE INDEX idx_calendar_integrations_user ON calendar_integrations(user_id);
CREATE INDEX idx_calendar_integrations_org ON calendar_integrations(organization_id);

-- =============================================================================
-- SECCIÓN 11: EVENTOS DE CALENDARIO
-- =============================================================================

CREATE TABLE calendar_events (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    calendar_integration_id UUID        NOT NULL REFERENCES calendar_integrations(id) ON DELETE CASCADE,
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    external_event_id   VARCHAR(500)    NOT NULL,
    title               VARCHAR(500),
    starts_at           TIMESTAMPTZ     NOT NULL,
    ends_at             TIMESTAMPTZ,
    meeting_url         TEXT,
    external_attendees  JSONB           NOT NULL DEFAULT '[]',
    dossier_scheduled_at TIMESTAMPTZ,
    processing_status   VARCHAR(20)     NOT NULL DEFAULT 'detected'
                        CHECK (processing_status IN ('detected', 'scheduled', 'processing', 'completed', 'skipped', 'failed')),
    skip_reason         TEXT,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (calendar_integration_id, external_event_id)
);

CREATE INDEX idx_calendar_events_user ON calendar_events(user_id);
CREATE INDEX idx_calendar_events_scheduled ON calendar_events(dossier_scheduled_at)
    WHERE processing_status = 'scheduled';

-- =============================================================================
-- SECCIÓN 12: FACTURACIÓN Y CRÉDITOS
-- =============================================================================

CREATE TABLE billing_transactions (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    type                VARCHAR(30)     NOT NULL
                        CHECK (type IN ('subscription', 'credit_purchase', 'credit_refund', 'plan_change')),
    amount_cents        INTEGER         NOT NULL,
    currency            VARCHAR(3)      NOT NULL DEFAULT 'USD',
    credits_added       INTEGER         NOT NULL DEFAULT 0,
    stripe_payment_intent_id VARCHAR(255),
    stripe_invoice_id   VARCHAR(255),
    description         TEXT,
    status              VARCHAR(20)     NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('pending', 'completed', 'failed', 'refunded')),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_billing_org ON billing_transactions(organization_id, created_at DESC);

CREATE TABLE credit_ledger (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID            NOT NULL REFERENCES users(id),
    dossier_id          UUID            REFERENCES dossiers(id) ON DELETE SET NULL,
    change_amount       INTEGER         NOT NULL,
    balance_after       INTEGER         NOT NULL
                        CHECK (balance_after >= 0),
    reason              VARCHAR(50)     NOT NULL
                        CHECK (reason IN ('dossier_generation', 'monthly_grant', 'purchase', 'refund', 'admin_adjustment')),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE credit_ledger IS 'Ledger inmutable de movimientos de créditos. Nunca se actualiza ni elimina, solo se inserta.';

CREATE INDEX idx_ledger_org ON credit_ledger(organization_id, created_at DESC);
CREATE INDEX idx_ledger_dossier ON credit_ledger(dossier_id) WHERE dossier_id IS NOT NULL;

-- =============================================================================
-- SECCIÓN 13: AUDIT LOGGING (Estándar Alloxentric - Sección 9.4)
-- =============================================================================

CREATE TABLE audit_logs (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID            REFERENCES users(id) ON DELETE SET NULL,
    user_role_at_time   VARCHAR(20),
    organization_id     UUID            REFERENCES organizations(id) ON DELETE SET NULL,
    action              VARCHAR(100)    NOT NULL,
    resource_type       VARCHAR(50),
    resource_id         UUID,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    ip_address          INET,
    user_agent          TEXT,
    http_status         SMALLINT,
    success             BOOLEAN         NOT NULL DEFAULT TRUE,
    error_message       TEXT,
    request_data        JSONB,
    duration_ms         INTEGER,
    log_hash            VARCHAR(64)
);

COMMENT ON TABLE audit_logs IS 'Log de auditoría inmutable. Registra WHO+WHAT+WHEN+WHERE+RESULT según estándar Alloxentric. NUNCA actualizar ni eliminar registros.';

CREATE INDEX idx_audit_user ON audit_logs(user_id, created_at DESC);
CREATE INDEX idx_audit_org ON audit_logs(organization_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_logs(action, created_at DESC);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_created ON audit_logs(created_at DESC);

-- =============================================================================
-- SECCIÓN 14: ALERTAS DE RIESGO (Módulo A/B/C - Sección 4.2)
-- =============================================================================

CREATE TABLE dossier_alerts (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    level               VARCHAR(10)     NOT NULL
                        CHECK (level IN ('critical', 'warning')),
    category            VARCHAR(50),
    message             TEXT            NOT NULL,
    source_url          TEXT,
    detected_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    is_acknowledged     BOOLEAN         NOT NULL DEFAULT FALSE,
    acknowledged_at     TIMESTAMPTZ,
    acknowledged_by_user_id UUID        REFERENCES users(id)
);

CREATE INDEX idx_alerts_dossier ON dossier_alerts(dossier_id);
CREATE INDEX idx_alerts_level ON dossier_alerts(dossier_id, level);

-- =============================================================================
-- SECCIÓN 15: NOTICIAS Y MENCIONES EN MEDIOS (Módulo C)
-- =============================================================================

CREATE TABLE dossier_media_mentions (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    title               TEXT            NOT NULL,
    url                 TEXT            NOT NULL,
    published_at        TIMESTAMPTZ,
    source_name         VARCHAR(255),
    source_type         VARCHAR(50),
    sentiment           VARCHAR(10)
                        CHECK (sentiment IN ('positive', 'neutral', 'negative', 'mixed')),
    summary             TEXT,
    relevance_score     DECIMAL(3,2)
                        CHECK (relevance_score BETWEEN 0.00 AND 1.00)
);

CREATE INDEX idx_media_dossier ON dossier_media_mentions(dossier_id);
CREATE INDEX idx_media_sentiment ON dossier_media_mentions(dossier_id, sentiment);

-- =============================================================================
-- SECCIÓN 16: CONFIGURACIÓN DE EMAIL
-- =============================================================================

CREATE TABLE email_integrations (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    provider            VARCHAR(20)     NOT NULL
                        CHECK (provider IN ('gmail', 'outlook', 'smtp')),
    is_enabled          BOOLEAN         NOT NULL DEFAULT TRUE,
    is_primary          BOOLEAN         NOT NULL DEFAULT FALSE,
    smtp_host           VARCHAR(255),
    smtp_port           SMALLINT,
    smtp_username       VARCHAR(255),
    smtp_password_encrypted TEXT,
    from_name           VARCHAR(255),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_email_primary ON email_integrations(user_id)
    WHERE is_primary = TRUE;

-- =============================================================================
-- TRIGGERS: AUTO-ACTUALIZACIÓN DE updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_dossiers_updated_at
    BEFORE UPDATE ON dossiers
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_contacts_updated_at
    BEFORE UPDATE ON contacts
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_calendar_integrations_updated_at
    BEFORE UPDATE ON calendar_integrations
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_calendar_events_updated_at
    BEFORE UPDATE ON calendar_events
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

CREATE TRIGGER trg_email_integrations_updated_at
    BEFORE UPDATE ON email_integrations
    FOR EACH ROW EXECUTE FUNCTION fn_update_updated_at();

-- =============================================================================
-- TRIGGER: DÉBITO AUTOMÁTICO DE CRÉDITOS AL CREAR UN DOSSIER
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_debit_credits_on_dossier()
RETURNS TRIGGER AS $$
DECLARE
    v_credits INTEGER;
BEGIN
    IF jsonb_extract_path_text(COALESCE(NEW.dossier_data, '{}'::jsonb), 'billing') = 'none' THEN
        NEW.credits_consumed := 0;
        RETURN NEW;
    END IF;

    v_credits := CASE NEW.depth_level
        WHEN 'basic'    THEN 1
        WHEN 'standard' THEN 3
        WHEN 'deep'     THEN 5
        ELSE 1
    END;

    IF (SELECT credits_balance FROM organizations WHERE id = NEW.organization_id) < v_credits THEN
        RAISE EXCEPTION 'Insufficient credits for organization %', NEW.organization_id;
    END IF;

    UPDATE organizations
    SET credits_balance = credits_balance - v_credits
    WHERE id = NEW.organization_id;

    NEW.credits_consumed := v_credits;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_credit_ledger_after_dossier_insert()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.credits_consumed IS NULL OR NEW.credits_consumed <= 0 THEN
        RETURN NEW;
    END IF;

    INSERT INTO credit_ledger (organization_id, user_id, dossier_id, change_amount, balance_after, reason)
    SELECT
        NEW.organization_id,
        NEW.requested_by_user_id,
        NEW.id,
        -NEW.credits_consumed,
        (SELECT credits_balance FROM organizations WHERE id = NEW.organization_id),
        'dossier_generation';

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_debit_credits
    BEFORE INSERT ON dossiers
    FOR EACH ROW EXECUTE FUNCTION fn_debit_credits_on_dossier();

CREATE TRIGGER trg_credit_ledger_after_dossier_insert
    AFTER INSERT ON dossiers
    FOR EACH ROW EXECUTE FUNCTION fn_credit_ledger_after_dossier_insert();

-- =============================================================================
-- VISTAS ÚTILES
-- =============================================================================

CREATE VIEW v_org_usage_stats AS
SELECT
    o.id                    AS organization_id,
    o.name                  AS organization_name,
    o.plan,
    o.credits_balance,
    COUNT(d.id)             AS total_dossiers,
    COUNT(d.id) FILTER (WHERE d.created_at >= date_trunc('month', NOW()))
                            AS dossiers_this_month,
    AVG(d.generation_duration_ms)::INTEGER
                            AS avg_generation_ms,
    COUNT(d.id) FILTER (WHERE d.status = 'complete')
                            AS successful_dossiers,
    COUNT(d.id) FILTER (WHERE d.status IN ('partial', 'failed'))
                            AS failed_dossiers
FROM organizations o
LEFT JOIN dossiers d ON o.id = d.organization_id
GROUP BY o.id, o.name, o.plan, o.credits_balance;

COMMENT ON VIEW v_org_usage_stats IS 'Estadísticas de uso agregadas por organización. Usada en el panel de admin Enterprise.';

CREATE VIEW v_critical_alerts AS
SELECT
    d.id                    AS dossier_id,
    d.organization_id,
    d.subject_name,
    d.subject_email,
    d.created_at            AS dossier_created_at,
    a.level,
    a.category,
    a.message,
    a.source_url,
    a.is_acknowledged
FROM dossiers d
INNER JOIN dossier_alerts a ON d.id = a.dossier_id
WHERE a.level = 'critical'
  AND a.is_acknowledged = FALSE;

COMMENT ON VIEW v_critical_alerts IS 'Alertas críticas activas no reconocidas. Para widget de riesgo en el dashboard.';
"""


def upgrade() -> None:
    # Parte 1: esquema base completo (16 tablas, 2 vistas, triggers/funciones).
    for statement in _split_sql_statements(_BASELINE_SQL):
        op.execute(text(statement))

    # Parte 2: parches idempotentes ya vigentes en produccion (columnas nuevas
    # en users/dossiers/calendar_integrations/calendar_events, el CHECK de
    # advance_minutes ampliado a (15,20,30,60,1440), y las tablas
    # dossier_shares / org_invites). Se reutiliza el modulo real para que
    # esta migracion nunca se desincronice de lo que aplica la app al
    # arrancar (ver api/app.py:lifespan -> apply_schema_patches).
    from dossier.db.schema_patches import _PATCHES

    for sql in _PATCHES:
        op.execute(text(sql))


def downgrade() -> None:
    op.execute(text("DROP VIEW IF EXISTS v_critical_alerts"))
    op.execute(text("DROP VIEW IF EXISTS v_org_usage_stats"))

    op.execute(text("DROP TRIGGER IF EXISTS trg_credit_ledger_after_dossier_insert ON dossiers"))
    op.execute(text("DROP TRIGGER IF EXISTS trg_debit_credits ON dossiers"))
    op.execute(text("DROP FUNCTION IF EXISTS fn_credit_ledger_after_dossier_insert()"))
    op.execute(text("DROP FUNCTION IF EXISTS fn_debit_credits_on_dossier()"))

    for table in (
        "email_integrations",
        "calendar_events",
        "calendar_integrations",
    ):
        op.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}"))
    for table in ("contacts", "dossiers", "users", "organizations"):
        op.execute(text(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}"))
    op.execute(text("DROP FUNCTION IF EXISTS fn_update_updated_at()"))

    # Tablas agregadas por schema_patches.py (no estan en Migracion.md).
    op.execute(text("DROP TABLE IF EXISTS org_invites"))
    op.execute(text("DROP TABLE IF EXISTS dossier_shares"))

    # Tablas de Migracion.md, en orden inverso de dependencias FK.
    for table in (
        "dossier_media_mentions",
        "dossier_alerts",
        "audit_logs",
        "credit_ledger",
        "billing_transactions",
        "calendar_events",
        "calendar_integrations",
        "dossier_ice_breakers",
        "dossier_corporate_records",
        "dossier_career_entries",
        "dossiers",
        "contacts",
        "api_keys",
        "refresh_tokens",
        "oauth_accounts",
        "email_integrations",
        "org_memberships",
        "users",
        "organizations",
    ):
        op.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))

    # Las extensiones (uuid-ossp, pgcrypto) no se eliminan: pueden ser usadas
    # por otros objetos del cluster ajenos a este esquema.


def _split_sql_statements(sql: str) -> list[str]:
    """Separa el script en sentencias individuales, respetando bloques ``$$``.

    Postgres/psql normalmente ejecuta un script completo de una vez, pero
    SQLAlchemy/Alembic ejecutan una sentencia a la vez via DBAPI, asi que hay
    que partir el texto por ``;`` sin cortar dentro de los bloques
    ``$$ ... $$`` de las funciones plpgsql (``fn_update_updated_at``,
    ``fn_debit_credits_on_dossier``, ``fn_credit_ledger_after_dossier_insert``).

    Los comentarios de sección (``-- ===...``) que preceden a una sentencia
    real quedan pegados al inicio del bloque -- eso es intencional y
    inofensivo: Postgres los ignora al ejecutar la sentencia. Solo se
    descartan bloques que, tras quitar comentarios, quedan vacios (p. ej.
    un comentario suelto sin sentencia real detras, al final del script).
    """
    statements: list[str] = []
    buf: list[str] = []
    in_dollar_quote = False
    for line in sql.splitlines():
        buf.append(line)
        if "$$" in line:
            in_dollar_quote = not in_dollar_quote if line.count("$$") % 2 == 1 else in_dollar_quote
        stripped = line.strip()
        if not in_dollar_quote and stripped.endswith(";"):
            statement = "\n".join(buf).strip()
            has_real_sql = any(
                ln.strip() and not ln.strip().startswith("--") for ln in statement.splitlines()
            )
            if has_real_sql:
                statements.append(statement)
            buf = []
    tail = "\n".join(buf).strip()
    if tail and any(ln.strip() and not ln.strip().startswith("--") for ln in tail.splitlines()):
        statements.append(tail)
    return statements
