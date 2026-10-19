"use client";

/**
 * Resultado de un job ya terminado (S5.4) y anuncio accesible de sus hitos.
 *
 * El resultado sale de `classifyJobOutcome`: no del estado de la conexión (el
 * corte se muestra aparte) ni de `job.status` a secas. Un job `failed` puede
 * tener información disponible y un dossier guardado `failed` no es un éxito.
 */
import type { ReactNode } from "react";
import type {
  DossierCorporatePartial,
  DossierJobProgressSnapshot,
  DossierPersonPartial,
} from "@/lib/dossier-api";
import type { DossierJobOutcome } from "@/lib/dossier-job-outcome";
import type { TranslationKey } from "@/i18n/types";
import { useTranslation } from "@/providers/PreferencesProvider";

type T = (key: TranslationKey, params?: Record<string, string | number>) => string;

export function outcomeText(t: T, outcome: DossierJobOutcome): string | null {
  switch (outcome.kind) {
    case "complete":
      return t("dossier_jobs.ready");
    case "partial":
      return t("progress.outcome.partial");
    case "failed_with_partial":
      return t("progress.outcome.failed_with_partial");
    case "failed":
      return t("dossier_jobs.failed");
    case "cancelled":
      return t("progress.outcome.cancelled");
    default:
      return null;
  }
}

/** Agentes y personas que no se completaron, con nombres comprensibles. */
export function missingItems(t: T, outcome: DossierJobOutcome): string[] {
  return [
    ...outcome.failedAgents.map((a) => t(`progress.agent.${a}` as TranslationKey)),
    ...outcome.failedPeople,
  ];
}

const TONE: Record<DossierJobOutcome["kind"], string> = {
  in_progress: "ui-alert-info",
  complete: "ui-alert-success",
  partial: "ui-alert-warning",
  failed_with_partial: "ui-alert-warning",
  failed: "ui-alert-error",
  cancelled: "ui-alert-info",
};

export default function JobOutcomeNotice({
  outcome,
  children,
}: {
  outcome: DossierJobOutcome;
  /** Acciones reales (enlace al dossier guardado, ver información disponible). */
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const text = outcomeText(t, outcome);
  if (!text) return null;
  const missing = outcome.kind === "partial" ? missingItems(t, outcome) : [];
  return (
    <div className={`ui-alert ${TONE[outcome.kind]} rounded-lg px-3 py-2 text-xs leading-relaxed`}>
      <p className="font-semibold">{text}</p>
      {outcome.recovered ? <p>{t("progress.outcome.recovered")}</p> : null}
      {missing.length > 0 ? <p>{t("progress.outcome.missing", { items: missing.join(", ") })}</p> : null}
      {children ? <div className="mt-2 flex flex-wrap items-center gap-3">{children}</div> : null}
    </div>
  );
}

/**
 * Texto del hito actual. Cambia solo en momentos importantes (perfiles, informe,
 * resultado final), así que un lector de pantalla no anuncia cada evento.
 */
export function progressMilestone(
  t: T,
  outcome: DossierJobOutcome,
  progress: DossierJobProgressSnapshot | null | undefined,
): string {
  const finalText = outcomeText(t, outcome);
  if (finalText) return finalText;
  const partials: (DossierCorporatePartial | DossierPersonPartial)[] =
    progress?.scopes.flatMap((s): (DossierCorporatePartial | DossierPersonPartial)[] => s.partial_results) ?? [];
  const hasReport = partials.some(
    (p) => p.section === "synthesis" || p.section === "person_report" || p.section === "person_context_report",
  );
  if (hasReport) return t("progress.announce.report");
  const hasProfiles = partials.some((p) => p.format === "person_profiles" && p.data.profiles.length > 0);
  return hasProfiles ? t("progress.announce.profiles") : "";
}

/**
 * Región `aria-live` (polite) del panel, una por panel. Mientras el job corre
 * lleva el hito en texto para lectores de pantalla; al terminar contiene el aviso
 * visible del resultado, de modo que el texto existe una sola vez.
 */
export function ProgressLiveRegion({ message, children }: { message: string; children?: ReactNode }) {
  return (
    <div role="status" aria-live="polite">
      {children ?? <span className="sr-only">{message}</span>}
    </div>
  );
}
