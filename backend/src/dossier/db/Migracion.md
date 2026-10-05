-- =============================================================================
-- PROJECT DOSSIER — Schema de Base de Datos PostgreSQL
-- Versión: 1.0 | Basado en: Project Dossier Especificaciones v2.0
-- Empresa: Alloxentric
-- =============================================================================

-- =============================================================================
-- EXTENSIONES REQUERIDAS
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- Habilita la función uuid_generate_v4() para generar UUIDs automáticamente.
-- UUIDs son preferidos sobre SERIAL para sistemas distribuidos y multi-tenant,
-- ya que evitan colisiones de IDs entre diferentes instancias de la base de datos.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- Habilita funciones criptográficas como gen_random_uuid() y digest().
-- Usada para hashing de contraseñas y firmado de logs de auditoría.

-- =============================================================================
-- SECCIÓN 1: ORGANIZACIÓN Y MULTI-TENANCY
-- Cada cliente (tenant) es una organización. Todo el sistema está particionado
-- por client_id, siguiendo los estándares Alloxentric de multi-tenancy.
-- =============================================================================

CREATE TABLE organizations (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Identificador único universal de la organización. UUID evita colisiones
    -- en arquitecturas distribuidas y no expone secuencias predecibles.

    name                VARCHAR(255)    NOT NULL,
    -- Nombre legal o comercial de la organización (tenant).

    slug                VARCHAR(100)    NOT NULL UNIQUE,
    -- Identificador URL-friendly único (ej: "alloxentric", "acme-corp").
    -- Usado para subdominios en modo white-label (v2.0).

    plan                VARCHAR(20)     NOT NULL DEFAULT 'free'
                        CHECK (plan IN ('free', 'pro', 'enterprise')),
    -- Plan de suscripción actual. El CHECK garantiza integridad referencial
    -- sin necesidad de una tabla separada para tipos de plan.

    credits_balance     INTEGER         NOT NULL DEFAULT 10
                        CHECK (credits_balance >= 0),
    -- Saldo de créditos disponibles. Básico=1, Estándar=3, Deep=5 créditos.
    -- El CHECK evita saldos negativos a nivel de base de datos.

    credits_monthly_limit INTEGER       NOT NULL DEFAULT 10,
    -- Límite mensual de créditos según el plan (Free=10, Pro=500, Enterprise=unlimited=-1).

    stripe_customer_id  VARCHAR(255)    UNIQUE,
    -- ID del cliente en Stripe para gestión de pagos y suscripciones.
    -- NULL para organizaciones en plan Free sin tarjeta registrada.

    stripe_subscription_id VARCHAR(255) UNIQUE,
    -- ID de la suscripción activa en Stripe. NULL para plan Free.

    is_white_label      BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Flag para clientes Enterprise con white-labeling activado (Fase v2.0).

    custom_domain       VARCHAR(255),
    -- Dominio propio para white-label (ej: "dossier.empresa.com"). Solo Enterprise.

    settings            JSONB           NOT NULL DEFAULT '{}',
    -- Configuración global de la organización en formato JSON flexible.
    -- Incluye: logo, colores de marca, preferencias de notificación, etc.
    -- JSONB (binario) es más eficiente que JSON para consultas e indexación.

    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    -- Soft-delete: permite desactivar una organización sin eliminar datos históricos.

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- Timestamp con timezone. TIMESTAMPTZ almacena en UTC internamente
    -- y convierte automáticamente según la zona horaria del cliente.

    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
    -- Actualizado automáticamente por el trigger update_updated_at.
);

COMMENT ON TABLE organizations IS 'Tabla principal de tenants. Cada organización es un cliente independiente del sistema multi-tenant.';

-- Índice para búsqueda por slug (usado en resolución de subdominios white-label)
CREATE INDEX idx_organizations_slug ON organizations(slug);
CREATE INDEX idx_organizations_plan ON organizations(plan);
CREATE INDEX idx_organizations_stripe_customer ON organizations(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;


-- =============================================================================
-- SECCIÓN 2: USUARIOS Y AUTENTICACIÓN
-- Usuarios pertenecen a una organización. Un usuario puede existir en múltiples
-- organizaciones con diferentes roles (tabla org_memberships).
-- =============================================================================

CREATE TABLE users (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    email               VARCHAR(255)    NOT NULL UNIQUE,
    -- Email único global en todo el sistema. Es el identificador principal
    -- para login y comunicaciones.

    email_verified      BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Flag de verificación de email. Los usuarios no verificados tienen
    -- acceso limitado hasta confirmar su dirección.

    password_hash       VARCHAR(255),
    -- Hash bcrypt de la contraseña. NULL para usuarios que solo usan OAuth
    -- (Google/Microsoft). Nunca se almacena la contraseña en texto plano.

    full_name           VARCHAR(255),
    -- Nombre completo del usuario para personalización de emails y UI.

    avatar_url          TEXT,
    -- URL de foto de perfil. Puede ser externa (Google, LinkedIn) o interna (S3).

    timezone            VARCHAR(100)    NOT NULL DEFAULT 'UTC',
    -- Zona horaria IANA del usuario (ej: 'Europe/London', 'America/New_York').
    -- Usada para mostrar timestamps y programar generación de dossiers.

    locale              VARCHAR(10)     NOT NULL DEFAULT 'en',
    -- Idioma preferido del usuario en formato BCP-47 (ej: 'en', 'es', 'fr').
    -- Determina el idioma del output de los dossiers (T-10).

    last_login_at       TIMESTAMPTZ,
    -- Último acceso para métricas de engagement y detección de cuentas inactivas.

    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    -- Soft-delete de usuario sin eliminar su historial.

    is_platform_admin BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Administrador de plataforma: acceso al panel `/admin` y métricas globales (no ligado a un tenant).

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS 'Usuarios del sistema. Un usuario puede pertenecer a múltiples organizaciones con distintos roles.';

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_active ON users(is_active) WHERE is_active = TRUE;


-- Membresías: relación N:N entre usuarios y organizaciones con RBAC
CREATE TABLE org_memberships (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- FK a la organización. CASCADE: si se elimina la org, se eliminan todas sus membresías.

    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- FK al usuario. CASCADE: si se elimina el usuario, se eliminan sus membresías.

    role                VARCHAR(20)     NOT NULL DEFAULT 'user'
                        CHECK (role IN ('admin', 'user', 'viewer', 'api_user')),
    -- Rol dentro de la organización según RBAC definido en la Sección 9.3:
    -- admin: gestión completa | user: genera y ve dossiers propios
    -- viewer: solo lectura | api_user: acceso vía API key (Enterprise)

    is_primary_org      BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Indica si esta es la organización principal del usuario.
    -- Solo puede haber una primary por usuario (enforced por unique partial index).

    invited_by_user_id  UUID            REFERENCES users(id),
    -- Usuario que envió la invitación. NULL si es el fundador de la organización.

    joined_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    UNIQUE (organization_id, user_id)
    -- Un usuario solo puede tener un rol por organización.
);

COMMENT ON TABLE org_memberships IS 'Tabla puente para RBAC: define el rol de cada usuario dentro de cada organización.';

CREATE INDEX idx_memberships_org ON org_memberships(organization_id);
CREATE INDEX idx_memberships_user ON org_memberships(user_id);

-- Garantiza que cada usuario solo tenga UNA organización primaria
CREATE UNIQUE INDEX idx_memberships_primary_org
    ON org_memberships(user_id)
    WHERE is_primary_org = TRUE;
-- Partial index: solo indexa filas donde is_primary_org = TRUE.
-- Es más eficiente que un índice completo y garantiza la restricción de unicidad.


-- =============================================================================
-- SECCIÓN 3: AUTENTICACIÓN OAUTH Y SESIONES
-- Soporta Google y Microsoft OAuth además de email/password.
-- =============================================================================

CREATE TABLE oauth_accounts (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    provider            VARCHAR(50)     NOT NULL
                        CHECK (provider IN ('google', 'microsoft', 'linkedin')),
    -- Proveedor OAuth. Google y Microsoft para Calendar/Email.
    -- LinkedIn guardado para futuras integraciones directas.

    provider_user_id    VARCHAR(255)    NOT NULL,
    -- ID único del usuario en el proveedor OAuth externo.

    access_token        TEXT,
    -- Token de acceso OAuth. Encriptado en reposo (AES-256 según Sección 9.1).
    -- Permite acceder a Calendar y Email APIs sin re-autenticación.

    refresh_token       TEXT,
    -- Token de renovación OAuth. Long-lived, permite obtener nuevos access_tokens.

    token_expires_at    TIMESTAMPTZ,
    -- Expiración del access_token. El sistema renueva automáticamente antes de esta fecha.

    scopes              TEXT[],
    -- Array de permisos OAuth concedidos por el usuario
    -- (ej: ['calendar.readonly', 'gmail.send']).

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    UNIQUE (provider, provider_user_id)
    -- Un proveedor+ID externo solo puede estar vinculado a un usuario interno.
);

CREATE INDEX idx_oauth_user ON oauth_accounts(user_id);


-- Refresh tokens JWT para autenticación stateful
CREATE TABLE refresh_tokens (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    token_hash          VARCHAR(255)    NOT NULL UNIQUE,
    -- Hash SHA-256 del refresh token. Nunca se almacena el token en texto plano.
    -- El token real se entrega al cliente y solo el hash se persiste.

    expires_at          TIMESTAMPTZ     NOT NULL,
    -- Expiración a 30 días según Sección 9.3. Después requiere nuevo login.

    is_revoked          BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Permite invalidar tokens sin esperar su expiración (logout explícito).

    ip_address          INET,
    -- IP de origen al momento de creación. Para detección de anomalías.

    user_agent          TEXT,
    -- User-Agent del cliente. Para identificar dispositivos y auditoría.

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_hash ON refresh_tokens(token_hash);
-- Índice para lookup rápido durante validación de tokens en cada request.

-- Limpia automáticamente tokens expirados (ejecutar periódicamente con pg_cron)
CREATE INDEX idx_refresh_tokens_expires ON refresh_tokens(expires_at)
    WHERE is_revoked = FALSE;


-- =============================================================================
-- SECCIÓN 4: API KEYS (Enterprise)
-- Los API users del plan Enterprise acceden vía API keys en lugar de JWT.
-- =============================================================================

CREATE TABLE api_keys (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by_user_id  UUID            NOT NULL REFERENCES users(id),

    name                VARCHAR(255)    NOT NULL,
    -- Nombre descriptivo de la API key (ej: "CRM Integration", "Jenkins CI").

    key_prefix          VARCHAR(10)     NOT NULL,
    -- Prefijo visible del key (ej: "pd_live_"). Ayuda al usuario a identificar claves.

    key_hash            VARCHAR(255)    NOT NULL UNIQUE,
    -- Hash SHA-256 de la API key completa. La key real solo se muestra una vez al crear.

    permissions         TEXT[]          NOT NULL DEFAULT '{}',
    -- Array de permisos específicos: ['dossiers:generate', 'dossiers:read', 'contacts:read'].

    rate_limit_per_hour INTEGER         NOT NULL DEFAULT 100,
    -- Límite de requests por hora para esta API key específica.

    last_used_at        TIMESTAMPTZ,
    -- Última vez que se usó esta clave. Útil para detectar claves no utilizadas.

    expires_at          TIMESTAMPTZ,
    -- Fecha de expiración opcional. NULL = no expira.

    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_keys_org ON api_keys(organization_id);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);


-- =============================================================================
-- SECCIÓN 5: CONTACTOS (ADDRESS BOOK)
-- Los contactos son las personas sobre quienes se generan dossiers.
-- Pertenecen a una organización (multi-tenant).
-- =============================================================================

CREATE TABLE contacts (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- Particionado por tenant. Un contacto pertenece a una organización específica.

    created_by_user_id  UUID            NOT NULL REFERENCES users(id),
    -- Usuario que añadió el contacto. Importante para trazabilidad.

    email               VARCHAR(255),
    -- Email del contacto. Puede ser NULL si solo se conoce nombre/empresa.
    -- Es el campo principal de lookup para integración con Calendar.

    full_name           VARCHAR(255),
    -- Nombre completo del contacto según los datos recuperados.

    linkedin_url        VARCHAR(500),
    -- URL del perfil de LinkedIn. Fuente primaria para Agent_Identity.

    company             VARCHAR(255),
    -- Empresa actual del contacto según última búsqueda.

    job_title           VARCHAR(255),
    -- Cargo actual del contacto.

    domain              VARCHAR(255),
    -- Dominio corporativo del email del contacto (ej: "empresa.com").
    -- Usado por el sistema de detección de reuniones externas (T-05).

    tags                TEXT[]          NOT NULL DEFAULT '{}',
    -- Tags para clasificación: ['vip', 'cliente', 'candidato', 'inversor'].
    -- GIN index permite búsquedas eficientes en arrays.

    is_vip              BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Flag VIP para la funcionalidad Address Book Pro (prioridad de actualización).

    notes               TEXT,
    -- Notas privadas del usuario sobre el contacto.

    last_dossier_at     TIMESTAMPTZ,
    -- Timestamp del último dossier generado para este contacto.
    -- Útil para mostrar "data puede estar desactualizada" si es muy antiguo.

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE contacts IS 'Address Book de la organización. Cada contacto puede tener múltiples dossiers generados a lo largo del tiempo.';

CREATE INDEX idx_contacts_org ON contacts(organization_id);
CREATE INDEX idx_contacts_email ON contacts(organization_id, email) WHERE email IS NOT NULL;
CREATE INDEX idx_contacts_domain ON contacts(organization_id, domain) WHERE domain IS NOT NULL;
CREATE INDEX idx_contacts_tags ON contacts USING GIN(tags);
-- GIN (Generalized Inverted Index) es el tipo de índice óptimo para arrays y JSONB
-- ya que indexa cada elemento individualmente, permitiendo búsquedas tipo @> (contains).

CREATE INDEX idx_contacts_vip ON contacts(organization_id, is_vip) WHERE is_vip = TRUE;


-- =============================================================================
-- SECCIÓN 6: DOSSIERS
-- Tabla central del sistema. Almacena los dossiers generados con su estado,
-- configuración, resultado y metadatos de auditoría.
-- =============================================================================

CREATE TABLE dossiers (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    requested_by_user_id UUID           NOT NULL REFERENCES users(id),
    contact_id          UUID            REFERENCES contacts(id) ON DELETE SET NULL,
    -- FK al contacto. SET NULL: si se elimina el contacto, el dossier histórico se preserva
    -- pero pierde la referencia al contacto (el dossier_data contiene la info).

    -- --- Identificación del sujeto del dossier ---
    subject_email       VARCHAR(255),
    -- Email del sujeto del dossier. Campo de búsqueda principal para los agentes.

    subject_name        VARCHAR(255),
    -- Nombre del sujeto. Puede pre-popularse del contacto o llenarse post-generación.

    -- --- Configuración de módulos activados ---
    module_identity     BOOLEAN         NOT NULL DEFAULT TRUE,
    -- Módulo A (siempre activo): identidad básica, cargo, empresa, tenure.

    module_corporate    BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Módulo B (configurable): registros corporativos, historial de directivos.

    module_media        BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Módulo C (configurable): noticias, podcasts, ice breakers, social.

    depth_level         VARCHAR(10)     NOT NULL DEFAULT 'basic'
                        CHECK (depth_level IN ('basic', 'standard', 'deep')),
    -- Nivel de profundidad: basic=A(1cr), standard=A+B(3cr), deep=A+B+C(5cr).

    credits_consumed    INTEGER         NOT NULL DEFAULT 0
                        CHECK (credits_consumed >= 0),
    -- Créditos debitados para este dossier específico. Registrado para auditoría.

    -- --- Estado del proceso de generación ---
    status              VARCHAR(20)     NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'complete', 'partial', 'failed')),
    -- pending: en cola | processing: agentes ejecutando
    -- complete: exitoso | partial: algunos agentes fallaron | failed: fallo total.

    status_message      TEXT,
    -- Mensaje descriptivo del estado actual. Visible al usuario vía WebSocket
    -- (ej: "Consultando registros corporativos UK...").

    -- --- Resultados ---
    dossier_data        JSONB,
    -- Resultado completo del dossier en el schema JSON definido en Sección 5.4.
    -- JSONB permite consultas estructuradas sobre el contenido del dossier.
    -- NULL mientras status != 'complete'|'partial'.

    alerts              JSONB           NOT NULL DEFAULT '[]',
    -- Array JSON de alertas de riesgo con level ('critical'|'warning') y message.
    -- Separado del dossier_data para consultas rápidas de alertas.

    -- --- Fuentes y agentes ---
    agents_activated    TEXT[]          NOT NULL DEFAULT '{}',
    -- Lista de agentes que se activaron para este dossier
    -- (ej: ['Agent_Identity', 'Agent_Corporate_UK', 'Agent_News']).

    agents_failed       TEXT[]          NOT NULL DEFAULT '{}',
    -- Agentes que fallaron. Si agents_failed no está vacío, status='partial'.

    data_sources_used   TEXT[]          NOT NULL DEFAULT '{}',
    -- Fuentes de datos efectivamente consultadas (trazabilidad completa, Sección 5.4).

    -- --- Timing de generación ---
    generation_started_at TIMESTAMPTZ,
    -- Momento en que el orquestador comenzó a procesar el dossier.

    generation_completed_at TIMESTAMPTZ,
    -- Momento en que el dossier quedó disponible (complete o partial).

    generation_duration_ms INTEGER,
    -- Duración total en milisegundos. KPI crítico: target <60s (estándar), <90s (deep).

    -- --- Caché y retención ---
    cache_key           VARCHAR(255),
    -- Clave Redis para el caché de 24h. Permite invalidación manual si es necesario.

    cached_until        TIMESTAMPTZ,
    -- Timestamp de expiración del caché Redis (NOW() + interval '24 hours').

    -- --- Contexto de origen ---
    trigger_source      VARCHAR(20)     NOT NULL DEFAULT 'manual'
                        CHECK (trigger_source IN ('manual', 'calendar', 'api', 'extension')),
    -- Origen de la solicitud: manual (usuario), calendar (automatización),
    -- api (integración Enterprise), extension (Chrome Extension v1.0).

    calendar_event_id   UUID,
    -- FK a calendar_events si el dossier fue generado por automatización de calendario.
    -- Sin FK directa aquí para evitar dependencia circular con calendar_events.

    -- --- Email de entrega ---
    email_sent          BOOLEAN         NOT NULL DEFAULT FALSE,
    email_sent_at       TIMESTAMPTZ,
    email_recipients    TEXT[]          NOT NULL DEFAULT '{}',
    -- Lista de emails a quienes se envió el dossier (usuario + asistente si configurado).

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
-- Índice descendente para listados por fecha más reciente (caso de uso más común).

CREATE INDEX idx_dossiers_alerts ON dossiers USING GIN(alerts);
-- Permite filtrar dossiers con alertas críticas: WHERE alerts @> '[{"level":"critical"}]'

CREATE INDEX idx_dossiers_cache_key ON dossiers(cache_key) WHERE cache_key IS NOT NULL;


-- =============================================================================
-- SECCIÓN 7: LÍNEA DE TIEMPO PROFESIONAL (Módulo A/B)
-- Almacena el historial de cargos del sujeto extraído de LinkedIn y registros
-- corporativos. Corresponde al campo career_timeline[] del schema JSON.
-- =============================================================================

CREATE TABLE dossier_career_entries (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,
    -- CASCADE: si se elimina el dossier, se eliminan sus entradas de carrera.

    company_name        VARCHAR(255)    NOT NULL,
    job_title           VARCHAR(255),
    start_date          DATE,
    end_date            DATE,
    -- NULL en end_date indica posición actual.

    tenure_months       INTEGER,
    -- Duración calculada automáticamente en meses. Facilita ordenamiento y comparación.

    is_current          BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Flag para el cargo actual. Permite filtros eficientes sin cálculos de fecha.

    gap_months_after    INTEGER,
    -- Brecha en meses entre esta posición y la siguiente en la línea de tiempo.
    -- Brechas > 0 se destacan visualmente en el frontend.

    has_discrepancy     BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Flag: TRUE si LinkedIn difiere de registros oficiales (Companies House, SEC).
    -- Marcado con "flag de advertencia" en el frontend según Sección 4.4.

    discrepancy_detail  TEXT,
    -- Descripción de la discrepancia detectada por el LLM.

    source              VARCHAR(50),
    -- Fuente de este registro: 'linkedin', 'companies_house', 'sec_edgar', 'opencorporates'.

    sort_order          INTEGER         NOT NULL DEFAULT 0
    -- Orden cronológico para renderizado de la timeline (0=más reciente).
);

CREATE INDEX idx_career_dossier ON dossier_career_entries(dossier_id);


-- =============================================================================
-- SECCIÓN 8: REGISTROS CORPORATIVOS (Módulo B)
-- Almacena los registros de empresas asociadas al sujeto, obtenidos de
-- Companies House, SEC EDGAR, OpenCorporates, etc.
-- =============================================================================

CREATE TABLE dossier_corporate_records (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,

    company_name        VARCHAR(255)    NOT NULL,
    company_number      VARCHAR(100),
    -- Número de registro oficial de la empresa (ej: Companies House number en UK).

    country             VARCHAR(3)      NOT NULL,
    -- Código ISO 3166-1 alpha-3 del país (ej: 'GBR', 'USA', 'FRA', 'DEU').

    jurisdiction        VARCHAR(100),
    -- Jurisdicción específica dentro del país (ej: estado en USA: 'Delaware', 'California').

    role_in_company     VARCHAR(255),
    -- Cargo del sujeto en la empresa (ej: 'Director', 'CEO', 'Secretary').

    company_status      VARCHAR(50),
    -- Estado actual de la empresa: 'active', 'dissolved', 'liquidation', 'administration'.

    incorporation_date  DATE,
    appointment_date    DATE,
    -- Fecha en que el sujeto fue nombrado en el cargo dentro de la empresa.

    resignation_date    DATE,
    -- NULL si sigue siendo directivo activo.

    insolvency_flag     BOOLEAN         NOT NULL DEFAULT FALSE,
    -- TRUE si la empresa tiene procesos de insolvencia activos o históricos.
    -- Trigger para alerta de riesgo CRÍTICO (Sección 4.2).

    source_api          VARCHAR(50),
    -- API de origen: 'companies_house', 'sec_edgar', 'opencorporates', 'infogreffe'.

    source_url          TEXT,
    -- URL directa al registro oficial para verificación.

    raw_data            JSONB
    -- Respuesta completa de la API en crudo, para trazabilidad y re-procesamiento.
);

CREATE INDEX idx_corporate_dossier ON dossier_corporate_records(dossier_id);
CREATE INDEX idx_corporate_insolvency ON dossier_corporate_records(dossier_id, insolvency_flag)
    WHERE insolvency_flag = TRUE;


-- =============================================================================
-- SECCIÓN 9: ICE BREAKERS (Módulo C)
-- Puntos de conversación personalizados generados por el LLM basados en
-- actividad pública del sujeto.
-- =============================================================================

CREATE TABLE dossier_ice_breakers (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,

    content             TEXT            NOT NULL,
    -- Texto del ice breaker generado por GPT-4o (ej: "Mencionó en un podcast de Fintech
    -- en enero 2026 su interés en...").

    source_url          TEXT,
    -- URL verificada de la fuente del ice breaker. Garantiza que no es una alucinación.

    source_type         VARCHAR(50),
    -- Tipo de fuente: 'podcast', 'linkedin_post', 'article', 'charity', 'hobby', 'interview'.

    sort_order          INTEGER         NOT NULL DEFAULT 0
    -- Orden de presentación (0=más relevante o reciente).
);

CREATE INDEX idx_icebreakers_dossier ON dossier_ice_breakers(dossier_id);


-- =============================================================================
-- SECCIÓN 10: INTEGRACIONES DE CALENDARIO
-- Configuración de la automatización de calendarios Google y Microsoft
-- por usuario y organización.
-- =============================================================================

CREATE TABLE calendar_integrations (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    provider            VARCHAR(20)     NOT NULL
                        CHECK (provider IN ('google', 'microsoft')),
    -- Proveedor del calendario: Google Calendar API o Microsoft Graph API.

    calendar_id         VARCHAR(500),
    -- ID del calendario específico dentro de la cuenta (puede tener múltiples).

    is_enabled          BOOLEAN         NOT NULL DEFAULT TRUE,
    -- Permite desactivar la integración sin eliminarla.

    -- --- Configuración de generación automática ---
    advance_minutes     INTEGER         NOT NULL DEFAULT 30
                        CHECK (advance_minutes IN (15, 30, 60, 1440)),
    -- Minutos de antelación para generar el dossier: 15min, 30min, 1h o 1 día (1440min).

    -- --- Reglas de filtrado ---
    skip_internal_meetings  BOOLEAN     NOT NULL DEFAULT TRUE,
    -- TRUE: no generar dossier para reuniones con participantes del mismo dominio.

    skip_recurring_after_first BOOLEAN  NOT NULL DEFAULT TRUE,
    -- TRUE: en reuniones recurrentes, solo genera en la primera ocurrencia.

    min_attendees       INTEGER         NOT NULL DEFAULT 1
                        CHECK (min_attendees >= 1),
    -- Número mínimo de participantes externos para activar la generación.

    domain_whitelist    TEXT[]          NOT NULL DEFAULT '{}',
    -- Dominios que siempre deben generar dossier (ej: ['cliente-vip.com']).

    domain_blacklist    TEXT[]          NOT NULL DEFAULT '{}',
    -- Dominios que nunca deben generar dossier (ej: ['calendly.com', 'hubspot.com']).

    default_depth       VARCHAR(10)     NOT NULL DEFAULT 'standard'
                        CHECK (default_depth IN ('basic', 'standard', 'deep')),
    -- Profundidad por defecto para dossiers generados automáticamente.

    -- --- Entrega por email ---
    auto_send_email     BOOLEAN         NOT NULL DEFAULT TRUE,
    -- TRUE: enviar el dossier por email al generarse automáticamente.

    email_cc_assistant  VARCHAR(255),
    -- Email del asistente ejecutivo para CC en cada dossier. NULL si no aplica.

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    UNIQUE (user_id, provider, calendar_id)
    -- Un usuario no puede tener dos integraciones del mismo proveedor+calendario.
);

CREATE INDEX idx_calendar_integrations_user ON calendar_integrations(user_id);
CREATE INDEX idx_calendar_integrations_org ON calendar_integrations(organization_id);


-- =============================================================================
-- SECCIÓN 11: EVENTOS DE CALENDARIO
-- Registra los eventos detectados por la automatización de calendario.
-- =============================================================================

CREATE TABLE calendar_events (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    calendar_integration_id UUID        NOT NULL REFERENCES calendar_integrations(id) ON DELETE CASCADE,
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    external_event_id   VARCHAR(500)    NOT NULL,
    -- ID del evento en el sistema externo (Google Calendar event ID o Outlook event ID).

    title               VARCHAR(500),
    -- Título del evento de calendario. Solo metadatos, no el contenido.

    starts_at           TIMESTAMPTZ     NOT NULL,
    ends_at             TIMESTAMPTZ,

    meeting_url         TEXT,
    -- URL de la videoconferencia (Google Meet, Zoom, Teams) si está disponible.

    external_attendees  JSONB           NOT NULL DEFAULT '[]',
    -- Array JSON con los participantes externos detectados:
    -- [{"email": "john@cliente.com", "name": "John Doe", "domain": "cliente.com"}]

    dossier_scheduled_at TIMESTAMPTZ,
    -- Cuándo está programada la generación del dossier (starts_at - advance_minutes).

    processing_status   VARCHAR(20)     NOT NULL DEFAULT 'detected'
                        CHECK (processing_status IN ('detected', 'scheduled', 'processing', 'completed', 'skipped', 'failed')),
    -- Estado del pipeline de automatización para este evento.

    skip_reason         TEXT,
    -- Razón por la que se omitió (ej: "Reunión interna", "Dominio en blacklist").

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    UNIQUE (calendar_integration_id, external_event_id)
    -- Evita duplicados al sincronizar el mismo evento múltiples veces.
);

CREATE INDEX idx_calendar_events_user ON calendar_events(user_id);
CREATE INDEX idx_calendar_events_scheduled ON calendar_events(dossier_scheduled_at)
    WHERE processing_status = 'scheduled';
-- Partial index: solo indexa eventos pendientes de procesar. Muy eficiente
-- para el job scheduler que busca "qué dossiers generar ahora".


-- =============================================================================
-- SECCIÓN 12: FACTURACIÓN Y CRÉDITOS
-- =============================================================================

-- Historial de compras y suscripciones
CREATE TABLE billing_transactions (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    type                VARCHAR(30)     NOT NULL
                        CHECK (type IN ('subscription', 'credit_purchase', 'credit_refund', 'plan_change')),
    -- Tipo de transacción de facturación.

    amount_cents        INTEGER         NOT NULL,
    -- Monto en centavos (evita problemas de punto flotante en dinero).
    -- Ej: 4900 = £49.00 o $49.00.

    currency            VARCHAR(3)      NOT NULL DEFAULT 'USD',
    -- Código ISO 4217 de moneda (USD, GBP, EUR).

    credits_added       INTEGER         NOT NULL DEFAULT 0,
    -- Créditos añadidos al saldo con esta transacción.

    stripe_payment_intent_id VARCHAR(255),
    stripe_invoice_id   VARCHAR(255),
    -- Referencias de Stripe para reconciliación contable.

    description         TEXT,
    status              VARCHAR(20)     NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('pending', 'completed', 'failed', 'refunded')),

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_billing_org ON billing_transactions(organization_id, created_at DESC);


-- Registro de consumo de créditos (ledger inmutable)
CREATE TABLE credit_ledger (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID            NOT NULL REFERENCES users(id),
    dossier_id          UUID            REFERENCES dossiers(id) ON DELETE SET NULL,

    change_amount       INTEGER         NOT NULL,
    -- Cambio en el saldo: positivo = créditos añadidos, negativo = créditos consumidos.

    balance_after       INTEGER         NOT NULL
                        CHECK (balance_after >= 0),
    -- Saldo resultante después de esta transacción. Permite reconstruir historial.

    reason              VARCHAR(50)     NOT NULL
                        CHECK (reason IN ('dossier_generation', 'monthly_grant', 'purchase', 'refund', 'admin_adjustment')),
    -- Razón del movimiento de créditos.

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE credit_ledger IS 'Ledger inmutable de movimientos de créditos. Nunca se actualiza ni elimina, solo se inserta.';

CREATE INDEX idx_ledger_org ON credit_ledger(organization_id, created_at DESC);
CREATE INDEX idx_ledger_dossier ON credit_ledger(dossier_id) WHERE dossier_id IS NOT NULL;


-- =============================================================================
-- SECCIÓN 13: AUDIT LOGGING (Estándar Alloxentric - Sección 9.4)
-- Registra 5 dimensiones obligatorias: WHO, WHAT, WHEN, WHERE, RESULT.
-- Tabla de solo-inserción (append-only). Nunca se actualiza ni elimina.
-- =============================================================================

CREATE TABLE audit_logs (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- WHO (Sección 9.4)
    user_id             UUID            REFERENCES users(id) ON DELETE SET NULL,
    -- NULL para acciones de sistema (procesos automáticos, scheduler, etc.).

    user_role_at_time   VARCHAR(20),
    -- Rol del usuario en el momento de la acción (snapshot, no FK).
    -- Guardado directamente porque el rol puede cambiar después.

    organization_id     UUID            REFERENCES organizations(id) ON DELETE SET NULL,

    -- WHAT (Sección 9.4)
    action              VARCHAR(100)    NOT NULL,
    -- Verbo HTTP + recurso (ej: 'POST /dossiers', 'DELETE /contacts/{id}', 'GET /billing').

    resource_type       VARCHAR(50),
    -- Tipo de recurso afectado: 'dossier', 'contact', 'user', 'billing', 'api_key'.

    resource_id         UUID,
    -- ID del recurso afectado.

    -- WHEN (Sección 9.4)
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    -- Timestamp ISO 8601 con precisión de milisegundos según el estándar Alloxentric.

    -- WHERE (Sección 9.4)
    ip_address          INET,
    -- Dirección IP del origen de la acción. INET soporta IPv4 e IPv6.

    user_agent          TEXT,
    -- User-Agent del cliente HTTP.

    -- RESULT (Sección 9.4)
    http_status         SMALLINT,
    -- Código de respuesta HTTP (200, 201, 400, 401, 403, 404, 500...).

    success             BOOLEAN         NOT NULL DEFAULT TRUE,
    -- TRUE si la acción fue exitosa, FALSE si resultó en error.

    error_message       TEXT,
    -- Mensaje de error descriptivo. NULL si success = TRUE.

    -- DATOS ADICIONALES
    request_data        JSONB,
    -- Payload de la request (con PII redactada). Para debugging y auditoría forense.

    duration_ms         INTEGER,
    -- Duración de la operación en milisegundos. Para detección de performance issues.

    log_hash            VARCHAR(64)
    -- Hash SHA-256 de los campos críticos del log para garantizar inmutabilidad.
    -- Permite detectar si un log fue manipulado (Sección 9.4: logs firmados digitalmente).
);

COMMENT ON TABLE audit_logs IS 'Log de auditoría inmutable. Registra WHO+WHAT+WHEN+WHERE+RESULT según estándar Alloxentric. NUNCA actualizar ni eliminar registros.';

-- Índices para consultas frecuentes de auditoría
CREATE INDEX idx_audit_user ON audit_logs(user_id, created_at DESC);
CREATE INDEX idx_audit_org ON audit_logs(organization_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_logs(action, created_at DESC);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_created ON audit_logs(created_at DESC);
-- Índice principal para queries por rango de fechas (el más común en auditoría).

-- Previene modificaciones (a nivel de comentario; enforced con roles de DB)
-- GRANT INSERT ON audit_logs TO app_user;
-- REVOKE UPDATE, DELETE ON audit_logs FROM app_user;


-- =============================================================================
-- SECCIÓN 14: ALERTAS DE RIESGO (Módulo A/B/C - Sección 4.2)
-- Alertas detectadas automáticamente durante la generación del dossier.
-- =============================================================================

CREATE TABLE dossier_alerts (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,

    level               VARCHAR(10)     NOT NULL
                        CHECK (level IN ('critical', 'warning')),
    -- CRÍTICO: insolvencia, fraude, condena penal, disqualificación de director.
    -- ADVERTENCIA: noticias negativas, despidos masivos, conflictos públicos.

    category            VARCHAR(50),
    -- Categoría de la alerta: 'insolvency', 'fraud', 'legal', 'negative_press',
    -- 'layoffs', 'disqualification', 'regulatory'.

    message             TEXT            NOT NULL,
    -- Descripción de la alerta generada por el LLM.

    source_url          TEXT,
    -- URL de la fuente que originó la alerta.

    detected_at         TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    is_acknowledged     BOOLEAN         NOT NULL DEFAULT FALSE,
    -- TRUE si el usuario ya revisó y reconoció esta alerta.

    acknowledged_at     TIMESTAMPTZ,
    acknowledged_by_user_id UUID        REFERENCES users(id)
);

CREATE INDEX idx_alerts_dossier ON dossier_alerts(dossier_id);
CREATE INDEX idx_alerts_level ON dossier_alerts(dossier_id, level);


-- =============================================================================
-- SECCIÓN 15: NOTICIAS Y MENCIONES EN MEDIOS (Módulo C)
-- Artículos, podcasts y menciones públicas del sujeto.
-- =============================================================================

CREATE TABLE dossier_media_mentions (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    dossier_id          UUID            NOT NULL REFERENCES dossiers(id) ON DELETE CASCADE,

    title               TEXT            NOT NULL,
    -- Título del artículo, episodio de podcast o publicación.

    url                 TEXT            NOT NULL,
    -- URL de la mención.

    published_at        TIMESTAMPTZ,
    -- Fecha de publicación. NULL si no se pudo determinar.

    source_name         VARCHAR(255),
    -- Nombre del medio (ej: 'The Guardian', 'TechCrunch', 'Lex Fridman Podcast').

    source_type         VARCHAR(50),
    -- Tipo: 'news', 'podcast', 'interview', 'linkedin_post', 'blog', 'press_release'.

    sentiment           VARCHAR(10)
                        CHECK (sentiment IN ('positive', 'neutral', 'negative', 'mixed')),
    -- Sentimiento detectado por el LLM. 'negative' puede triggear alerta de ADVERTENCIA.

    summary             TEXT,
    -- Resumen de 1-3 oraciones generado por el LLM.

    relevance_score     DECIMAL(3,2)
                        CHECK (relevance_score BETWEEN 0.00 AND 1.00)
    -- Score de relevancia del LLM (0.00 = poco relevante, 1.00 = muy relevante).
    -- Usado para ordenar y filtrar menciones.
);

CREATE INDEX idx_media_dossier ON dossier_media_mentions(dossier_id);
CREATE INDEX idx_media_sentiment ON dossier_media_mentions(dossier_id, sentiment);


-- =============================================================================
-- SECCIÓN 16: CONFIGURACIÓN DE EMAIL
-- Configuración de proveedores de email para entrega de dossiers.
-- =============================================================================

CREATE TABLE email_integrations (
    id                  UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),

    user_id             UUID            NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    organization_id     UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    provider            VARCHAR(20)     NOT NULL
                        CHECK (provider IN ('gmail', 'outlook', 'smtp')),
    -- Gmail API, Microsoft Outlook Mail API o SMTP personalizado.

    is_enabled          BOOLEAN         NOT NULL DEFAULT TRUE,
    is_primary          BOOLEAN         NOT NULL DEFAULT FALSE,
    -- Solo puede haber un proveedor primario por usuario.

    smtp_host           VARCHAR(255),
    smtp_port           SMALLINT,
    smtp_username       VARCHAR(255),
    smtp_password_encrypted TEXT,
    -- Contraseña SMTP encriptada con AES-256 (solo para provider='smtp').

    from_name           VARCHAR(255),
    -- Nombre remitente en los emails (ej: "John Doe via Project Dossier").

    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_email_primary ON email_integrations(user_id)
    WHERE is_primary = TRUE;
-- Solo un proveedor primario por usuario.


-- =============================================================================
-- TRIGGERS: AUTO-ACTUALIZACIÓN DE updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION fn_update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    -- Asigna el timestamp actual al campo updated_at antes de cada UPDATE.
    -- RETURN NEW es obligatorio en triggers BEFORE para confirmar la operación.
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- plpgsql es el lenguaje procedural de PostgreSQL, similar a PL/SQL en Oracle.

-- Aplica el trigger a todas las tablas con campo updated_at
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
    -- Variable local para almacenar los créditos a debitar.
BEGIN
    -- Generación sin cobro (p. ej. API con billing desactivado): `dossier_data.billing = 'none'`.
    IF jsonb_extract_path_text(COALESCE(NEW.dossier_data, '{}'::jsonb), 'billing') = 'none' THEN
        NEW.credits_consumed := 0;
        RETURN NEW;
    END IF;

    -- Determina los créditos según el nivel de profundidad del dossier
    v_credits := CASE NEW.depth_level
        WHEN 'basic'    THEN 1   -- Módulo A solo
        WHEN 'standard' THEN 3   -- Módulos A+B
        WHEN 'deep'     THEN 5   -- Módulos A+B+C
        ELSE 1
    END;

    -- Verifica que haya saldo suficiente antes de generar
    IF (SELECT credits_balance FROM organizations WHERE id = NEW.organization_id) < v_credits THEN
        RAISE EXCEPTION 'Insufficient credits for organization %', NEW.organization_id;
        -- RAISE EXCEPTION aborta la transacción completa y devuelve un error al backend.
    END IF;

    -- Descuenta los créditos del saldo de la organización
    UPDATE organizations
    SET credits_balance = credits_balance - v_credits
    WHERE id = NEW.organization_id;

    -- Actualiza el campo credits_consumed del dossier recién creado
    NEW.credits_consumed := v_credits;

    -- El INSERT en credit_ledger ocurre en AFTER INSERT (`fn_credit_ledger_after_dossier_insert`):
    -- en BEFORE INSERT la fila de dossiers aún no existe y violaría credit_ledger_dossier_id_fkey.

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
-- BEFORE INSERT: debita saldo y fija NEW.credits_consumed; no escribe credit_ledger aquí.

CREATE TRIGGER trg_credit_ledger_after_dossier_insert
    AFTER INSERT ON dossiers
    FOR EACH ROW EXECUTE FUNCTION fn_credit_ledger_after_dossier_insert();
-- AFTER INSERT: el dossier ya existe; el ledger puede referenciar dossier_id con FK válida.


-- =============================================================================
-- VISTAS ÚTILES
-- =============================================================================

-- Vista: estadísticas de uso por organización (para dashboard admin)
CREATE VIEW v_org_usage_stats AS
SELECT
    o.id                    AS organization_id,
    o.name                  AS organization_name,
    o.plan,
    o.credits_balance,
    COUNT(d.id)             AS total_dossiers,
    COUNT(d.id) FILTER (WHERE d.created_at >= date_trunc('month', NOW()))
                            AS dossiers_this_month,
    -- FILTER clause: cuenta solo los dossiers del mes actual.
    -- Es más eficiente que un CASE WHEN dentro del COUNT.
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


-- Vista: dossiers con alertas críticas activas (para dashboard de riesgo)
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
-- Filtra solo alertas críticas no reconocidas. El dashboard muestra estas
-- alertas de forma prominente hasta que el usuario las reconozca.

COMMENT ON VIEW v_critical_alerts IS 'Alertas críticas activas no reconocidas. Para widget de riesgo en el dashboard.';


-- =============================================================================
-- ROLES DE BASE DE DATOS (Principio de mínimo privilegio)
-- =============================================================================

-- Rol de la aplicación: acceso a operaciones normales
-- CREATE ROLE app_user LOGIN PASSWORD 'secure_password';
-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_user;
-- REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM app_user;
-- REVOKE UPDATE, DELETE ON audit_logs FROM app_user; -- Audit logs: solo INSERT
-- GRANT DELETE ON dossiers, contacts, calendar_events, calendar_integrations TO app_user; -- Solo donde se necesita

-- Rol de lectura para analytics/reporting
-- CREATE ROLE readonly_user LOGIN PASSWORD 'secure_password';
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
-- REVOKE SELECT ON audit_logs FROM readonly_user; -- Logs de auditoría: acceso restringido


-- =============================================================================
-- MIGRACIÓN INCREMENTAL: administrador de plataforma (usuarios existentes)
-- Ejecutar una vez si la tabla `users` ya existía sin la columna siguiente.
-- =============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT FALSE;
-- Opcional: otorgar panel de admin a un usuario concreto:
-- UPDATE users SET is_platform_admin = TRUE WHERE lower(email) = lower('tu-admin@dominio.com');


-- =============================================================================
-- FIN DEL SCHEMA
-- Total de tablas: 16 principales + 2 vistas
-- Extensiones: uuid-ossp, pgcrypto
-- Triggers: 8 (7 updated_at + 1 débito de créditos)
-- =============================================================================
