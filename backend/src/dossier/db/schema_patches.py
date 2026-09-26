"""Parches DDL idempotentes para bases ya creadas (``create_all`` no altera tablas existentes)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

_PATCHES = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS dossier_output_language VARCHAR(10) NOT NULL DEFAULT 'match';",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS dossier_retention_days INTEGER DEFAULT 30;",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE;",
    "ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS dossier_folder_id UUID;",
    "CREATE INDEX IF NOT EXISTS idx_dossiers_folder ON dossiers (dossier_folder_id) WHERE dossier_folder_id IS NOT NULL;",
    "ALTER TABLE calendar_integrations ADD COLUMN IF NOT EXISTS refresh_token_encrypted TEXT;",
    "ALTER TABLE calendar_integrations ADD COLUMN IF NOT EXISTS access_token_encrypted TEXT;",
    "ALTER TABLE calendar_integrations ADD COLUMN IF NOT EXISTS access_token_expires_at TIMESTAMPTZ;",
    "ALTER TABLE calendar_integrations ADD COLUMN IF NOT EXISTS granted_scopes TEXT;",
    "ALTER TABLE calendar_integrations ADD COLUMN IF NOT EXISTS provider_subject VARCHAR(255);",
    "ALTER TABLE calendar_integrations ADD COLUMN IF NOT EXISTS provider_email VARCHAR(255);",
    "ALTER TABLE calendar_integrations ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;",
    "ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS event_snapshot JSONB;",
    "ALTER TABLE calendar_integrations DROP CONSTRAINT IF EXISTS calendar_integrations_advance_minutes_check;",
    """
    DO $$
    BEGIN
      ALTER TABLE calendar_integrations
        ADD CONSTRAINT calendar_integrations_advance_minutes_check
        CHECK (advance_minutes IN (15, 20, 30, 60, 1440));
    EXCEPTION
      WHEN duplicate_object THEN NULL;
    END $$;
    """,
    """
    CREATE TABLE IF NOT EXISTS dossier_shares (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        dossier_id UUID NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
        shared_with_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        shared_by_user_id UUID NOT NULL REFERENCES users(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (dossier_id, shared_with_user_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_dossier_shares_dossier ON dossier_shares(dossier_id);",
    "CREATE INDEX IF NOT EXISTS idx_dossier_shares_user ON dossier_shares(shared_with_user_id);",
    """
    CREATE TABLE IF NOT EXISTS org_invites (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        email VARCHAR(255) NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'user',
        token VARCHAR(64) NOT NULL UNIQUE,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        invited_by_user_id UUID NOT NULL REFERENCES users(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at TIMESTAMPTZ NOT NULL,
        accepted_at TIMESTAMPTZ
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_org_invites_org ON org_invites(organization_id);",
    "CREATE INDEX IF NOT EXISTS idx_org_invites_email ON org_invites(email);",
    "CREATE INDEX IF NOT EXISTS idx_org_invites_status ON org_invites(status);",
)

# S4.5: extiende las tablas de la línea base al contrato de S4.1
# (schemas/dossier_executive_payload.py). Separado de _PATCHES porque la
# migración de línea base itera _PATCHES en vivo; lo aplica la migración 0002.
ALERT_LEVELS = ("critical", "warning", "low", "medium", "high")

DOSSIER_ENTITIES_PATCHES = (
    "ALTER TABLE dossier_alerts ADD COLUMN IF NOT EXISTS title VARCHAR(255);",
    "ALTER TABLE dossier_alerts ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]'::jsonb;",
    "ALTER TABLE dossier_alerts DROP CONSTRAINT IF EXISTS dossier_alerts_level_check;",
    "ALTER TABLE dossier_alerts ADD CONSTRAINT dossier_alerts_level_check CHECK (level IN ("
    + ", ".join(f"'{nivel}'" for nivel in ALERT_LEVELS)
    + "));",
    "ALTER TABLE dossier_media_mentions ADD COLUMN IF NOT EXISTS source_citation JSONB;",
    "ALTER TABLE dossier_media_mentions ADD COLUMN IF NOT EXISTS query_context VARCHAR(255);",
    "ALTER TABLE dossier_career_entries ADD COLUMN IF NOT EXISTS start_date_text VARCHAR(50);",
    "ALTER TABLE dossier_career_entries ADD COLUMN IF NOT EXISTS end_date_text VARCHAR(50);",
    "ALTER TABLE dossier_career_entries ADD COLUMN IF NOT EXISTS source_citation JSONB;",
)


def apply_schema_patches(engine: Engine) -> None:
    with engine.begin() as conn:
        for sql in _PATCHES + DOSSIER_ENTITIES_PATCHES:
            conn.execute(text(sql))
