/**
 * Clasificación del resultado de un job de dossier (S5.4).
 *
 * Función pura y separada de dos cosas que a veces se confunden con ella:
 * - el estado de la conexión SSE (un corte no es un fallo de generación), y
 * - `job.status` a secas: un job `completed` puede traer un dossier guardado
 *   `failed`, y uno `failed` puede conservar perfiles útiles.
 *
 * No deduce éxito de la ausencia en `agents_failed`: un agente pudo omitirse o no
 * tener metadatos. El éxito exige un dossier guardado con `status: complete`.
 */
import type {
  CalendarGenerarDossierItem,
  CalendarSavedDossierRef,
  CreateCorporateDossierResponse,
  DossierCorporateAgentName,
  DossierGenerationJobApi,
  DossierJobProgressSnapshot,
  DossierProgressScope,
  PersonResearchApiResponse,
} from "@/lib/dossier-api";
import { CORPORATE_AGENTS, normalizeProgressSnapshot } from "@/lib/dossier-job-progress";
import { isPdlProfileFoundInfoWarning } from "@/lib/translate-pdl-warning";

export type DossierJobOutcomeKind =
  | "in_progress"
  | "complete"
  | "partial"
  | "failed_with_partial"
  | "failed"
  | "cancelled";

export type DossierJobOutcome = {
  kind: DossierJobOutcomeKind;
  /** El informe se recuperó con el respaldo (una etapa fallida tiene `recovered_by`). */
  recovered: boolean;
  /** Resultado reutilizado de una ejecución anterior (caché). */
  fromCache: boolean;
  /** Hay vistas previas válidas (perfiles o texto) en el progreso del job. */
  hasPartial: boolean;
  /** Enlace al dossier o la carpeta guardados válidos; `null` si no hay. */
  savedHref: string | null;
  /** Agentes corporativos que fallaron. */
  failedAgents: DossierCorporateAgentName[];
  /** Personas de una reunión cuyo dossier no se completó. */
  failedPeople: string[];
};

const COMPLETE = "complete";

function progressOf(job: DossierGenerationJobApi): DossierJobProgressSnapshot | null {
  return normalizeProgressSnapshot(job.progress);
}

/** ¿El scope tiene contenido mostrable? Una vista previa vacía no cuenta. */
export function scopeHasUsefulPartial(scope: DossierProgressScope): boolean {
  return scope.partial_results.some((p) =>
    p.format === "person_profiles" ? p.data.profiles.length > 0 : p.content.trim().length > 0,
  );
}

function legacyCriticalWarnings(result: PersonResearchApiResponse): string[] {
  return (result.warnings ?? []).filter(
    (w) =>
      !isPdlProfileFoundInfoWarning(w) &&
      !w.toLowerCase().includes("no se encontró información adicional") &&
      !w.toLowerCase().includes("no se encontró perfil verificable"),
  );
}

function base(kind: DossierJobOutcomeKind): DossierJobOutcome {
  return {
    kind,
    recovered: false,
    fromCache: false,
    hasPartial: false,
    savedHref: null,
    failedAgents: [],
    failedPeople: [],
  };
}

function classifyPerson(job: DossierGenerationJobApi, progress: DossierJobProgressSnapshot | null): DossierJobOutcome {
  const result = (job.result ?? null) as PersonResearchApiResponse | null;
  const scope = progress?.scopes.find((s) => s.kind === "person") ?? null;
  const out = base("failed");
  out.hasPartial = scope ? scopeHasUsefulPartial(scope) : false;
  out.fromCache = scope?.origin === "redis_cache" || result?.dossier_source === "redis_cache";
  if (scope?.kind === "person") {
    out.recovered = scope.stages.some((s) => s.status === "failed" && Boolean(s.recovered_by));
  }

  if (job.status === "cancelled") return { ...out, kind: "cancelled" };
  if (job.status !== "completed") return { ...out, kind: out.hasPartial ? "failed_with_partial" : "failed" };
  // Sin resultado no hay nada que clasificar: se conserva el comportamiento de S5.1.
  if (!result) return { ...out, kind: "complete" };

  const saved = result.saved_dossier;
  if (!saved?.id || saved.status !== COMPLETE) {
    return { ...out, kind: out.hasPartial ? "failed_with_partial" : "failed" };
  }
  out.savedHref = `/dashboard/dossiers/${saved.id}`;

  if (scope?.kind === "person") {
    const unresolved = scope.stages.some((s) => s.status === "failed" && !s.recovered_by);
    return { ...out, kind: unresolved ? "partial" : "complete" };
  }
  // Jobs anteriores a S5.4, sin progreso: mismas reglas que antes (texto de avisos).
  const hasAnalysis = Boolean(result.llm_analysis_markdown?.trim());
  const partial = !hasAnalysis || legacyCriticalWarnings(result).length > 0;
  return { ...out, kind: partial ? "partial" : "complete" };
}

function calendarPeople(saved: CalendarGenerarDossierItem["saved_dossiers"]): CalendarSavedDossierRef[] {
  if (Array.isArray(saved?.persons) && saved.persons.length > 0) return saved.persons;
  return saved?.person ? [saved.person] : [];
}

function classifyCalendar(job: DossierGenerationJobApi, progress: DossierJobProgressSnapshot | null): DossierJobOutcome {
  const result = (job.result ?? null) as CalendarGenerarDossierItem | null;
  const out = base("failed");
  out.hasPartial = Boolean(progress?.scopes.some(scopeHasUsefulPartial));
  const corporate = progress?.scopes.find((s) => s.kind === "corporate");
  out.fromCache = corporate?.origin === "redis_cache" || result?.corporate_cache_hit === true;

  const failed = new Set<string>();
  if (corporate?.kind === "corporate") {
    for (const a of corporate.agents) if (a.status === "failed") failed.add(a.agent_name);
  }
  for (const name of result?.corporate_agents_failed ?? []) failed.add(name);
  out.failedAgents = CORPORATE_AGENTS.filter((a) => failed.has(a));

  if (job.status === "cancelled") return { ...out, kind: "cancelled" };
  if (job.status !== "completed") return { ...out, kind: out.hasPartial ? "failed_with_partial" : "failed" };
  if (!result) return { ...out, kind: "complete" };

  const saved = result.saved_dossiers;
  const people = calendarPeople(saved);
  const items = [...(saved?.corporate ? [saved.corporate] : []), ...people];
  const ok = items.filter((i) => i.status === COMPLETE);
  out.failedPeople = people
    .filter((p) => p.status !== COMPLETE)
    .map((p) => p.subject_name?.trim() || "")
    .filter(Boolean);

  if (ok.length === 0) return { ...out, kind: out.hasPartial ? "failed_with_partial" : "failed" };

  const firstPerson = people.find((p) => p.status === COMPLETE);
  out.savedHref = saved?.folder?.id
    ? `/dashboard/dossiers/folder/${saved.folder.id}`
    : firstPerson
      ? `/dashboard/dossiers/${firstPerson.id}`
      : saved?.corporate?.status === COMPLETE
        ? `/dashboard/dossiers/${saved.corporate.id}`
        : "/dashboard/dossiers";
  const partial = ok.length < items.length || out.failedAgents.length > 0;
  return { ...out, kind: partial ? "partial" : "complete" };
}

function classifyCorporate(job: DossierGenerationJobApi): DossierJobOutcome {
  if (job.status === "cancelled") return base("cancelled");
  if (job.status !== "completed") return base("failed");
  const id = (job.result as CreateCorporateDossierResponse | null | undefined)?.id;
  if (!job.result) return base("complete");
  return id ? { ...base("complete"), savedHref: `/dashboard/dossiers/${id}` } : base("failed");
}

export function classifyJobOutcome(job: DossierGenerationJobApi): DossierJobOutcome {
  if (job.status === "queued" || job.status === "running") return base("in_progress");
  if (job.job_type === "person_manual") return classifyPerson(job, progressOf(job));
  if (job.job_type === "calendar_manual") return classifyCalendar(job, progressOf(job));
  if (job.job_type === "corporate_manual") return classifyCorporate(job);
  if (job.status === "completed") return base("complete");
  return base(job.status === "cancelled" ? "cancelled" : "failed");
}
