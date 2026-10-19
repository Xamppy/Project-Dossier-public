/**
 * Progreso por scopes de un job de dossier (ADR 0009, S5.4).
 *
 * Funciones puras: validan lo que llega del servidor (eventos SSE y el snapshot
 * `progress` de GET o de `job_status`) y lo fusionan por revisión. El estado es
 * el mismo snapshot del contrato, de modo que los componentes leen una sola forma.
 *
 * Reglas:
 * - Manda la revisión por entidad (`scope_id` + `agent_name`/`stage_id`/`section`):
 *   un cambio con revisión igual o menor se ignora, así que duplicados y desorden
 *   no cambian el resultado.
 * - Un estado terminal no cambia de estado; solo gana metadatos (`used_in_final`,
 *   `recovered_by`…), igual que en el backend.
 * - Los campos del scope (`origin`, `profiles_count`, `dossier`) solo llegan en
 *   snapshots: gana el snapshot con mayor revisión del job.
 * - Un evento cuyo scope o entidad no declaró el servidor se descarta: el catálogo
 *   siempre llega antes que sus transiciones, y el snapshot siguiente lo trae igual.
 * - Nada fuera de la proyección permitida llega al estado: un perfil se reduce a
 *   nombre, cargo, empresa y hasta tres URLs `https`.
 */
import type {
  DossierAgentProgressEntry,
  DossierCorporateAgentName,
  DossierCorporatePartial,
  DossierCorporatePartialSection,
  DossierCorporateProgressScope,
  DossierJobProgressSnapshot,
  DossierPartialProvenance,
  DossierPersonPartial,
  DossierPersonProfilePreview,
  DossierPersonProgressScope,
  DossierPersonResearchSource,
  DossierPersonStageId,
  DossierProgressOrigin,
  DossierProgressReasonCode,
  DossierProgressScope,
  DossierProgressStatus,
  DossierScopeDossierRef,
  DossierStageProgressEntry,
} from "@/lib/dossier-api";

export const PROGRESS_SCHEMA_VERSION = 1;

export const PROGRESS_EVENT_NAMES: ReadonlySet<string> = new Set([
  "agent_progress",
  "stage_progress",
  "partial_result",
]);

/** Catálogo corporativo en el orden del ADR 0009 (IDs de los nodos del grafo). */
export const CORPORATE_AGENTS: readonly DossierCorporateAgentName[] = [
  "agent_corporate_uk",
  "agent_corporate_usa",
  "agent_corporate_eu",
  "agent_news",
  "synthesize_llm",
];

/** Etapas posibles por modalidad. El catálogo real de cada scope lo declara el servidor. */
export const PERSON_STAGES_BY_SOURCE: Readonly<
  Record<DossierPersonResearchSource, readonly DossierPersonStageId[]>
> = {
  pdl: [
    "person.cache_lookup",
    "person.pdl_enrich",
    "person.pdl_search",
    "person.profile_normalization",
    "person.context_analysis",
    "person.profile_synthesis",
    "person.markdown_fallback",
    "person.report_finalize",
    "person.persist",
  ],
  // Web pública: una llamada a DeepSeek sin buscador; no hay etapas de búsqueda.
  gemini_web: [
    "person.cache_lookup",
    "person.context_analysis",
    "person.report_finalize",
    "person.persist",
  ],
};

const TERMINAL: ReadonlySet<DossierProgressStatus> = new Set([
  "completed",
  "failed",
  "skipped",
  "cancelled",
]);

const STATUSES: ReadonlySet<string> = new Set([
  "pending",
  "running",
  "completed",
  "failed",
  "skipped",
  "cancelled",
]);

/** Motivos válidos por estado (mismo conjunto que `dossier_progress_model.REASON_CODES`). */
const REASONS_BY_STATUS: Readonly<Record<DossierProgressStatus, ReadonlySet<string>>> = {
  pending: new Set(),
  running: new Set(),
  cancelled: new Set(),
  completed: new Set(["no_matches", "cache_hit", "cache_miss"]),
  skipped: new Set([
    "out_of_scope",
    "no_target_company",
    "plan_not_included",
    "cache_hit",
    "cache_unavailable",
    "force_refresh",
    "mode_not_applicable",
    "sufficient_profiles",
    "no_profiles",
    "configuration_missing",
    "feature_disabled",
    "insufficient_input",
    "not_required",
    "no_content",
    "upstream_auth_failed",
    "not_reached",
  ]),
  failed: new Set([
    "provider_error",
    "provider_timeout",
    "provider_quota",
    "provider_rate_limit",
    "upstream_auth_failed",
    "structured_output_invalid",
    "no_valid_report",
    "persistence_error",
    "interrupted",
  ]),
};

/** Sección corporativa → agente que la produce. UK y USA no tienen vista previa (ADR 0009). */
const CORPORATE_SECTIONS: Readonly<Record<DossierCorporatePartialSection, DossierCorporateAgentName>> = {
  corporate_eu: "agent_corporate_eu",
  news: "agent_news",
  synthesis: "synthesize_llm",
};

const PERSON_MARKDOWN_SECTIONS: ReadonlySet<string> = new Set(["person_context_report", "person_report"]);
const BASES: ReadonlySet<string> = new Set(["provider_records", "model_only", "mixed", "unknown"]);
const SCOPE_ID = /^(corporate|person):\d{1,3}$/;
const MAX_PROFILES = 5;
const MAX_PROFILE_URLS = 3;
const MAX_FIELD_CHARS = 200;
const MAX_URL_CHARS = 500;

type EventBase = { job_id: string; scope_id: string; revision: number };

export type DossierAgentProgressEvent = EventBase & {
  type: "agent_progress";
  agent_name: DossierCorporateAgentName;
  status: DossierProgressStatus;
  reason_code: DossierProgressReasonCode | null;
  timestamp: string | null;
};

type StageMeta = Pick<
  DossierStageProgressEntry,
  "attempts" | "used_in_final" | "recovered_by" | "dossier_id" | "dossier_status"
>;

export type DossierStageProgressEvent = EventBase &
  StageMeta & {
    type: "stage_progress";
    research_source: DossierPersonResearchSource;
    stage_id: DossierPersonStageId;
    status: DossierProgressStatus;
    reason_code: DossierProgressReasonCode | null;
    timestamp: string | null;
  };

export type DossierPartialResultEvent = EventBase & {
  type: "partial_result";
  /** Solo en parciales de persona. */
  research_source?: DossierPersonResearchSource;
  partial: DossierCorporatePartial | DossierPersonPartial;
};

export type DossierJobProgressEvent =
  | DossierAgentProgressEvent
  | DossierStageProgressEvent
  | DossierPartialResultEvent;

// --- validación ---------------------------------------------------------------

type Obj = Record<string, unknown>;

function asObject(value: unknown): Obj | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Obj) : null;
}

function isRevision(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function asStatus(value: unknown): DossierProgressStatus | null {
  return typeof value === "string" && STATUSES.has(value) ? (value as DossierProgressStatus) : null;
}

/** Un motivo desconocido o que no corresponde al estado no se muestra: queda `null`. */
function asReason(value: unknown, status: DossierProgressStatus): DossierProgressReasonCode | null {
  return typeof value === "string" && REASONS_BY_STATUS[status].has(value)
    ? (value as DossierProgressReasonCode)
    : null;
}

function asTimestamp(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function asSource(value: unknown): DossierPersonResearchSource | null {
  return value === "pdl" || value === "gemini_web" ? value : null;
}

function isAgentName(value: unknown): value is DossierCorporateAgentName {
  return typeof value === "string" && (CORPORATE_AGENTS as readonly string[]).includes(value);
}

function isStageOf(value: unknown, source: DossierPersonResearchSource): value is DossierPersonStageId {
  return typeof value === "string" && (PERSON_STAGES_BY_SOURCE[source] as readonly string[]).includes(value);
}

function isAnyStage(value: unknown): value is DossierPersonStageId {
  return typeof value === "string" && (PERSON_STAGES_BY_SOURCE.pdl as readonly string[]).includes(value);
}

function asOrigin(value: unknown): DossierProgressOrigin {
  return value === "generated" || value === "redis_cache" ? value : null;
}

function scopeKind(scopeId: unknown): "corporate" | "person" | null {
  if (typeof scopeId !== "string") return null;
  const match = SCOPE_ID.exec(scopeId);
  return match ? (match[1] as "corporate" | "person") : null;
}

function shortText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.split(/\s+/).filter(Boolean).join(" ");
  return text ? text.slice(0, MAX_FIELD_CHARS) : null;
}

/** Igual que `safe_profile_url` del backend: solo `https`, con host y sin credenciales. */
export function safeProfileUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const url = value.trim();
  if (!url || url.length > MAX_URL_CHARS || /[\s\u0000-\u001f]/.test(url)) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:" || !parsed.hostname || parsed.username || parsed.password) return null;
  return url;
}

function validMarkdown(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text || text.startsWith("# Error")) return null;
  return value;
}

function parseProvenance(value: unknown): DossierPartialProvenance | null {
  const o = asObject(value);
  if (!o || typeof o.basis !== "string" || !BASES.has(o.basis)) return null;
  const sources = Array.isArray(o.sources)
    ? o.sources.filter((s): s is string => typeof s === "string" && s.length > 0)
    : [];
  return {
    basis: o.basis as DossierPartialProvenance["basis"],
    sources,
    live_web_search: o.live_web_search === true,
  };
}

function parseProfiles(value: unknown): { profiles: DossierPersonProfilePreview[]; profiles_count: number } | null {
  const o = asObject(value);
  if (!o || !Array.isArray(o.profiles)) return null;
  const profiles: DossierPersonProfilePreview[] = [];
  for (const [index, raw] of o.profiles.slice(0, MAX_PROFILES).entries()) {
    const p = asObject(raw);
    if (!p) continue;
    const urls: string[] = [];
    for (const u of Array.isArray(p.profile_urls) ? p.profile_urls : []) {
      const safe = safeProfileUrl(u);
      if (safe && !urls.includes(safe)) urls.push(safe);
      if (urls.length >= MAX_PROFILE_URLS) break;
    }
    profiles.push({
      record_key: typeof p.record_key === "string" && p.record_key ? p.record_key : `profile:${index}`,
      full_name: shortText(p.full_name),
      job_title: shortText(p.job_title),
      company: shortText(p.company),
      profile_urls: urls,
    });
  }
  const count =
    typeof o.profiles_count === "number" && Number.isInteger(o.profiles_count) && o.profiles_count >= 0
      ? o.profiles_count
      : profiles.length;
  return { profiles, profiles_count: count };
}

/** Normaliza un parcial (de un evento o del snapshot) a la forma del estado. */
function parsePartial(
  raw: Obj,
  kind: "corporate" | "person",
  revision: number,
): DossierCorporatePartial | DossierPersonPartial | null {
  const truncated = raw.truncated === true;
  const origin = asOrigin(raw.origin);
  if (kind === "corporate") {
    const section = raw.section as DossierCorporatePartialSection;
    if (typeof raw.section !== "string" || !Object.prototype.hasOwnProperty.call(CORPORATE_SECTIONS, section)) {
      return null;
    }
    if (raw.agent_name !== CORPORATE_SECTIONS[section] || raw.format !== "markdown") return null;
    const content = validMarkdown(raw.content);
    if (content === null) return null;
    return {
      section,
      agent_name: CORPORATE_SECTIONS[section],
      format: "markdown",
      content,
      origin,
      provisional: true,
      truncated,
      revision,
    };
  }
  if (!isAnyStage(raw.stage_id)) return null;
  const provenance = parseProvenance(raw.provenance);
  if (!provenance) return null;
  if (raw.section === "person_profiles") {
    if (raw.format !== "person_profiles") return null;
    const data = parseProfiles(raw.data);
    if (!data) return null;
    return {
      section: "person_profiles",
      stage_id: raw.stage_id,
      format: "person_profiles",
      data,
      provenance,
      origin,
      provisional: true,
      truncated,
      revision,
    };
  }
  if (typeof raw.section !== "string" || !PERSON_MARKDOWN_SECTIONS.has(raw.section)) return null;
  if (raw.format !== "markdown") return null;
  const content = validMarkdown(raw.content);
  if (content === null) return null;
  return {
    section: raw.section as "person_context_report" | "person_report",
    stage_id: raw.stage_id,
    format: "markdown",
    content,
    provenance,
    origin,
    provisional: true,
    truncated,
    revision,
  };
}

function stageMetaOf(event: DossierStageProgressEvent): StageMeta {
  const meta: StageMeta = {};
  if (event.attempts) meta.attempts = event.attempts;
  if (event.used_in_final !== undefined) meta.used_in_final = event.used_in_final;
  if (event.recovered_by) meta.recovered_by = event.recovered_by;
  if (event.dossier_id) meta.dossier_id = event.dossier_id;
  if (event.dossier_status) meta.dossier_status = event.dossier_status;
  return meta;
}

function parseStageMeta(o: Obj): StageMeta {
  const meta: StageMeta = {};
  const attempts = asObject(o.attempts);
  if (attempts && isRevision(attempts.total) && isRevision(attempts.failed)) {
    meta.attempts = { total: attempts.total, failed: attempts.failed };
  }
  if (typeof o.used_in_final === "boolean") meta.used_in_final = o.used_in_final;
  if (isAnyStage(o.recovered_by)) meta.recovered_by = o.recovered_by;
  if (typeof o.dossier_id === "string" && o.dossier_id) meta.dossier_id = o.dossier_id;
  if (typeof o.dossier_status === "string" && o.dossier_status) meta.dossier_status = o.dossier_status;
  return meta;
}

/**
 * Valida un evento de progreso del stream del job `expectedJobId`. Devuelve
 * `null` si no cumple el contrato: quien lo recibe lo descarta sin cortar el canal.
 */
export function parseProgressEvent(
  event: string,
  data: unknown,
  expectedJobId: string,
): DossierJobProgressEvent | null {
  if (!PROGRESS_EVENT_NAMES.has(event)) return null;
  const o = asObject(data);
  if (!o || o.schema_version !== PROGRESS_SCHEMA_VERSION || o.job_id !== expectedJobId) return null;
  const kind = scopeKind(o.scope_id);
  if (!kind || !isRevision(o.revision) || o.revision < 1) return null;
  const base: EventBase = { job_id: expectedJobId, scope_id: o.scope_id as string, revision: o.revision };

  if (event === "agent_progress") {
    const status = asStatus(o.status);
    if (kind !== "corporate" || !isAgentName(o.agent_name) || !status) return null;
    return {
      type: "agent_progress",
      ...base,
      agent_name: o.agent_name,
      status,
      reason_code: asReason(o.reason_code, status),
      timestamp: asTimestamp(o.timestamp),
    };
  }

  if (event === "stage_progress") {
    const status = asStatus(o.status);
    const source = asSource(o.research_source);
    if (kind !== "person" || !status || !source || !isStageOf(o.stage_id, source)) return null;
    return {
      type: "stage_progress",
      ...base,
      research_source: source,
      stage_id: o.stage_id,
      status,
      reason_code: asReason(o.reason_code, status),
      timestamp: asTimestamp(o.timestamp),
      ...parseStageMeta(o),
    };
  }

  const partial = parsePartial(o, kind, o.revision);
  if (!partial) return null;
  if (kind === "corporate") return { type: "partial_result", ...base, partial };
  const source = asSource(o.research_source);
  if (!source || !isStageOf((partial as DossierPersonPartial).stage_id, source)) return null;
  return { type: "partial_result", ...base, research_source: source, partial };
}

// --- snapshot -----------------------------------------------------------------

function parseDossierRef(value: unknown): DossierScopeDossierRef | null {
  const o = asObject(value);
  if (!o || typeof o.id !== "string" || !o.id || typeof o.status !== "string") return null;
  return { id: o.id, status: o.status };
}

function parseAgentEntry(value: unknown): DossierAgentProgressEntry | null {
  const o = asObject(value);
  const status = asStatus(o?.status);
  if (!o || !status || !isAgentName(o.agent_name) || !isRevision(o.revision)) return null;
  return {
    agent_name: o.agent_name,
    status,
    reason_code: asReason(o.reason_code, status),
    revision: o.revision,
    timestamp: asTimestamp(o.timestamp),
  };
}

function parseStageEntry(value: unknown, source: DossierPersonResearchSource): DossierStageProgressEntry | null {
  const o = asObject(value);
  const status = asStatus(o?.status);
  if (!o || !status || !isStageOf(o.stage_id, source) || !isRevision(o.revision)) return null;
  return {
    stage_id: o.stage_id,
    status,
    reason_code: asReason(o.reason_code, status),
    revision: o.revision,
    timestamp: asTimestamp(o.timestamp),
    ...parseStageMeta(o),
  };
}

function uniqueBy<T>(items: T[], key: (item: T) => string): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const k = key(item);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function parseScope(value: unknown): DossierProgressScope | null {
  const o = asObject(value);
  const kind = scopeKind(o?.scope_id);
  if (!o || !kind || o.kind !== kind) return null;
  const label = typeof o.label === "string" && o.label.trim() ? o.label : null;
  const partialsRaw = Array.isArray(o.partial_results) ? o.partial_results : [];
  const dossier = parseDossierRef(o.dossier);
  const origin = asOrigin(o.origin);

  if (kind === "corporate") {
    if (!Array.isArray(o.agents)) return null;
    const agents = uniqueBy(
      o.agents.map(parseAgentEntry).filter((a): a is DossierAgentProgressEntry => a !== null),
      (a) => a.agent_name,
    );
    const partial_results = uniqueBy(
      partialsRaw
        .map((p) => {
          const po = asObject(p);
          return po && isRevision(po.revision) ? parsePartial(po, "corporate", po.revision) : null;
        })
        .filter((p): p is DossierCorporatePartial => p !== null),
      (p) => p.section,
    );
    return { scope_id: o.scope_id as string, kind, label, origin, agents, partial_results, dossier };
  }

  const source = asSource(o.research_source);
  if (!source || !Array.isArray(o.stages)) return null;
  const stages = uniqueBy(
    o.stages
      .map((s) => parseStageEntry(s, source))
      .filter((s): s is DossierStageProgressEntry => s !== null),
    (s) => s.stage_id,
  );
  const partial_results = uniqueBy(
    partialsRaw
      .map((p) => {
        const po = asObject(p);
        if (!po || !isRevision(po.revision) || !isStageOf(po.stage_id, source)) return null;
        return parsePartial(po, "person", po.revision) as DossierPersonPartial | null;
      })
      .filter((p): p is DossierPersonPartial => p !== null),
    (p) => p.section,
  );
  const count = o.profiles_count;
  return {
    scope_id: o.scope_id as string,
    kind,
    label,
    research_source: source,
    live_web_search: o.live_web_search === true,
    origin,
    profiles_count: typeof count === "number" && Number.isInteger(count) && count >= 0 ? count : null,
    stages,
    partial_results,
    dossier,
  };
}

/** Valida el `progress` de un snapshot del job. `null` si falta o no cumple el contrato. */
export function normalizeProgressSnapshot(raw: unknown): DossierJobProgressSnapshot | null {
  const o = asObject(raw);
  if (!o || o.schema_version !== PROGRESS_SCHEMA_VERSION || !isRevision(o.revision)) return null;
  if (!Array.isArray(o.scopes)) return null;
  const scopes = uniqueBy(
    o.scopes.map(parseScope).filter((s): s is DossierProgressScope => s !== null),
    (s) => s.scope_id,
  );
  return { schema_version: PROGRESS_SCHEMA_VERSION, revision: o.revision, scopes };
}

// --- fusión -------------------------------------------------------------------

type Entity = { status: DossierProgressStatus; revision: number };

/**
 * Elige entre dos versiones de la misma entidad. Gana la revisión mayor, pero un
 * terminal conserva su estado y su motivo: de la versión nueva solo toma metadatos.
 */
function pickEntity<T extends Entity>(current: T, incoming: T): T {
  if (incoming.revision <= current.revision) return current;
  if (TERMINAL.has(current.status) && incoming.status !== current.status) {
    const metadata = { ...incoming } as Partial<T>;
    delete metadata.status;
    delete (metadata as { reason_code?: unknown }).reason_code;
    return { ...current, ...metadata };
  }
  return { ...current, ...incoming };
}

/** Une dos listas por clave: orden de `primary`, luego lo que solo tiene `secondary`. */
function mergeLists<T>(
  primary: T[],
  secondary: T[],
  key: (item: T) => string,
  pick: (fromPrimary: T, fromSecondary: T) => T,
): T[] {
  const other = new Map(secondary.map((item) => [key(item), item]));
  const out = primary.map((item) => {
    const match = other.get(key(item));
    return match ? pick(item, match) : item;
  });
  const used = new Set(primary.map(key));
  for (const item of secondary) if (!used.has(key(item))) out.push(item);
  return out;
}

function sameList<T>(a: T[], b: T[]): boolean {
  return a.length === b.length && a.every((item, i) => item === b[i]);
}

function mergeScope(
  current: DossierProgressScope,
  incoming: DossierProgressScope,
  incomingIsNewer: boolean,
): DossierProgressScope {
  // La identidad de un scope no cambia dentro de un job: uno incoherente no se aplica.
  if (current.kind !== incoming.kind) return current;
  if (current.kind === "person" && incoming.kind === "person" && current.research_source !== incoming.research_source) {
    return current;
  }
  const [primary, secondary] = incomingIsNewer ? [incoming, current] : [current, incoming];
  const pickNewest = <T extends { revision: number }>(fromPrimary: T, fromSecondary: T): T => {
    const [cur, inc] = incomingIsNewer ? [fromSecondary, fromPrimary] : [fromPrimary, fromSecondary];
    return "status" in cur ? (pickEntity(cur as T & Entity, inc as T & Entity) as T) : inc.revision > cur.revision ? inc : cur;
  };

  if (primary.kind === "corporate" && secondary.kind === "corporate") {
    const agents = mergeLists(primary.agents, secondary.agents, (a) => a.agent_name, pickNewest);
    const partial_results = mergeLists(
      primary.partial_results,
      secondary.partial_results,
      (p) => p.section,
      pickNewest,
    );
    const merged: DossierCorporateProgressScope = { ...primary, agents, partial_results };
    return sameCorporate(current as DossierCorporateProgressScope, merged) ? current : merged;
  }
  if (primary.kind === "person" && secondary.kind === "person") {
    const stages = mergeLists(primary.stages, secondary.stages, (s) => s.stage_id, pickNewest);
    const partial_results = mergeLists(
      primary.partial_results,
      secondary.partial_results,
      (p) => p.section,
      pickNewest,
    );
    const merged: DossierPersonProgressScope = { ...primary, stages, partial_results };
    return samePerson(current as DossierPersonProgressScope, merged) ? current : merged;
  }
  return current;
}

function sameScopeFields(a: DossierProgressScope, b: DossierProgressScope): boolean {
  return (
    a.label === b.label &&
    a.origin === b.origin &&
    a.dossier?.id === b.dossier?.id &&
    a.dossier?.status === b.dossier?.status
  );
}

function sameCorporate(a: DossierCorporateProgressScope, b: DossierCorporateProgressScope): boolean {
  return sameScopeFields(a, b) && sameList(a.agents, b.agents) && sameList(a.partial_results, b.partial_results);
}

function samePerson(a: DossierPersonProgressScope, b: DossierPersonProgressScope): boolean {
  return (
    sameScopeFields(a, b) &&
    a.profiles_count === b.profiles_count &&
    a.live_web_search === b.live_web_search &&
    sameList(a.stages, b.stages) &&
    sameList(a.partial_results, b.partial_results)
  );
}

/**
 * Fusiona un snapshot ya normalizado sobre el estado. Acepta `null` (job sin
 * progreso): nunca borra lo que ya se tenía. Devuelve la misma referencia si no
 * cambia nada.
 */
export function mergeProgress(
  current: DossierJobProgressSnapshot | null | undefined,
  incoming: DossierJobProgressSnapshot | null,
): DossierJobProgressSnapshot | null {
  if (!incoming) return current ?? null;
  if (!current) return incoming;
  const incomingIsNewer = incoming.revision >= current.revision;
  const [primary, secondary] = incomingIsNewer ? [incoming, current] : [current, incoming];
  const currentById = new Map(current.scopes.map((s) => [s.scope_id, s]));
  const incomingById = new Map(incoming.scopes.map((s) => [s.scope_id, s]));
  const order = mergeLists(primary.scopes, secondary.scopes, (s) => s.scope_id, (a) => a).map(
    (s) => s.scope_id,
  );
  const scopes = order.map((id) => {
    const cur = currentById.get(id);
    const inc = incomingById.get(id);
    if (cur && inc) return mergeScope(cur, inc, incomingIsNewer);
    return (cur ?? inc) as DossierProgressScope;
  });
  const revision = Math.max(current.revision, incoming.revision);
  if (revision === current.revision && sameList(scopes, current.scopes)) return current;
  return { schema_version: PROGRESS_SCHEMA_VERSION, revision, scopes };
}

function withScope(
  state: DossierJobProgressSnapshot,
  index: number,
  scope: DossierProgressScope,
  revision: number,
): DossierJobProgressSnapshot {
  const scopes = [...state.scopes];
  scopes[index] = scope;
  return { ...state, revision: Math.max(state.revision, revision), scopes };
}

/**
 * Aplica un evento ya validado. Sin catálogo (estado vacío), con scope o entidad
 * no declarados, o con otra modalidad, no cambia nada y devuelve la misma referencia.
 */
export function applyProgressEvent(
  current: DossierJobProgressSnapshot | null | undefined,
  event: DossierJobProgressEvent,
): DossierJobProgressSnapshot | null | undefined {
  if (!current) return current;
  const index = current.scopes.findIndex((s) => s.scope_id === event.scope_id);
  if (index < 0) return current;
  const scope = current.scopes[index];

  if (event.type === "agent_progress") {
    if (scope.kind !== "corporate") return current;
    const i = scope.agents.findIndex((a) => a.agent_name === event.agent_name);
    if (i < 0) return current;
    const next = pickEntity(scope.agents[i], {
      agent_name: event.agent_name,
      status: event.status,
      reason_code: event.reason_code,
      revision: event.revision,
      timestamp: event.timestamp,
    });
    if (next === scope.agents[i]) return current;
    const agents = [...scope.agents];
    agents[i] = next;
    return withScope(current, index, { ...scope, agents }, event.revision);
  }

  if (event.type === "stage_progress") {
    if (scope.kind !== "person" || scope.research_source !== event.research_source) return current;
    const i = scope.stages.findIndex((s) => s.stage_id === event.stage_id);
    if (i < 0) return current;
    const next = pickEntity(scope.stages[i], {
      stage_id: event.stage_id,
      status: event.status,
      reason_code: event.reason_code,
      revision: event.revision,
      timestamp: event.timestamp,
      ...stageMetaOf(event),
    });
    if (next === scope.stages[i]) return current;
    const stages = [...scope.stages];
    stages[i] = next;
    return withScope(current, index, { ...scope, stages }, event.revision);
  }

  const partial = event.partial;
  if (scope.kind === "corporate") {
    if (partial.format !== "markdown" || !("agent_name" in partial)) return current;
    const i = scope.partial_results.findIndex((p) => p.section === partial.section);
    if (i >= 0 && scope.partial_results[i].revision >= partial.revision) return current;
    const partial_results = [...scope.partial_results];
    if (i >= 0) partial_results[i] = partial;
    else partial_results.push(partial);
    return withScope(current, index, { ...scope, partial_results }, event.revision);
  }
  if ("agent_name" in partial || event.research_source !== scope.research_source) return current;
  if (!scope.stages.some((s) => s.stage_id === partial.stage_id)) return current;
  const i = scope.partial_results.findIndex((p) => p.section === partial.section);
  if (i >= 0 && scope.partial_results[i].revision >= partial.revision) return current;
  const partial_results = [...scope.partial_results];
  if (i >= 0) partial_results[i] = partial;
  else partial_results.push(partial);
  return withScope(current, index, { ...scope, partial_results }, event.revision);
}

export function isTerminalProgressStatus(status: DossierProgressStatus): boolean {
  return TERMINAL.has(status);
}
