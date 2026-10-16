"use client";

/**
 * Vistas previas de la investigación de una persona (S5.4): los perfiles en
 * cuanto llegan (antes del informe) y el texto del informe cuando vuelve.
 *
 * Solo pinta la proyección permitida: nombre, cargo, empresa y enlaces `https`.
 * El resultado final del job todavía trae los perfiles completos de PDL; aquí no
 * se usa. Todo se marca como provisional: no equivale a un dossier guardado.
 */
import type {
  DossierPartialProvenance,
  DossierPersonMarkdownPartial,
  DossierPersonProfilesPartial,
  DossierPersonProgressScope,
} from "@/lib/dossier-api";
import type { TranslationKey } from "@/i18n/types";
import { safeProfileUrl } from "@/lib/dossier-job-progress";
import { useTranslation } from "@/providers/PreferencesProvider";
import { MarkdownPreview, ProvisionalBadge } from "@/components/dossier/progress-display";

type Props = {
  scope: DossierPersonProgressScope;
  /** `false` en Calendario al terminar: ahí se muestra el informe guardado. */
  showReport?: boolean;
};

function provenanceKey(provenance: DossierPartialProvenance): TranslationKey {
  return `progress.provenance.${provenance.basis}` as TranslationKey;
}

/** El informe elegido; el análisis de contexto solo si no hay informe o es distinto y no se usó. */
function reportPartials(scope: DossierPersonProgressScope): DossierPersonMarkdownPartial[] {
  const markdown = scope.partial_results.filter(
    (p): p is DossierPersonMarkdownPartial => p.format === "markdown",
  );
  const report = markdown.find((p) => p.section === "person_report");
  const context = markdown.find((p) => p.section === "person_context_report");
  if (!report) return context ? [context] : [];
  if (!context || context.content.trim() === report.content.trim()) return [report];
  const contextStage = scope.stages.find((s) => s.stage_id === "person.context_analysis");
  return contextStage?.used_in_final === false ? [report, context] : [report];
}

export default function PersonResearchPartialResults({ scope, showReport = true }: Props) {
  const { t } = useTranslation();
  const profiles = scope.partial_results.find(
    (p): p is DossierPersonProfilesPartial => p.format === "person_profiles" && p.data.profiles.length > 0,
  );
  const reports = showReport ? reportPartials(scope) : [];
  // Caché antigua: sabe cuántos perfiles hubo pero no los guarda. No se inventan.
  const cachedCount =
    !profiles && scope.origin === "redis_cache" && (scope.profiles_count ?? 0) > 0 ? scope.profiles_count : null;

  if (!profiles && reports.length === 0 && cachedCount === null) return null;

  return (
    <div className="mt-3 space-y-3">
      {profiles ? (
        <section
          aria-label={t("progress.profiles_title")}
          className="rounded-md border p-2.5"
          style={{ borderColor: "var(--border-default)" }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
              {t("progress.profiles_title")}
            </h4>
            <ProvisionalBadge />
          </div>
          <ul className="mt-2 space-y-2">
            {profiles.data.profiles.map((profile) => {
              const urls = profile.profile_urls.map(safeProfileUrl).filter((u): u is string => u !== null);
              const role = [profile.job_title, profile.company].filter(Boolean).join(" · ");
              return (
                <li key={profile.record_key} className="text-xs leading-relaxed">
                  <p className="font-medium" style={{ color: "var(--text-primary)" }}>
                    {profile.full_name ?? t("progress.no_profile_name")}
                  </p>
                  {role ? <p style={{ color: "var(--text-secondary)" }}>{role}</p> : null}
                  {urls.length > 0 ? (
                    <p className="mt-0.5 flex flex-wrap gap-x-3">
                      {urls.map((url) => (
                        <a
                          key={url}
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="min-w-0 max-w-full break-all underline"
                          style={{ color: "var(--accent-from)" }}
                        >
                          {url.replace(/^https:\/\//, "")}
                        </a>
                      ))}
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
          <p className="mt-2 text-[11px]" style={{ color: "var(--text-subtle)" }}>
            {t("progress.profiles_provenance")}
          </p>
        </section>
      ) : null}
      {cachedCount !== null ? (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {t("progress.from_cache_profiles", { count: cachedCount })}
        </p>
      ) : null}
      {reports.map((report) => {
        const title = t(report.section === "person_report" ? "progress.report_title" : "progress.context_report_title");
        return (
          <section
            key={report.section}
            aria-label={title}
            className="rounded-md border p-2.5"
            style={{ borderColor: "var(--border-default)" }}
          >
            <div className="mb-1.5 flex flex-wrap items-center gap-2">
              <h4 className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
                {title}
              </h4>
              <ProvisionalBadge />
            </div>
            <MarkdownPreview content={report.content} truncated={report.truncated} />
            <p className="mt-1.5 text-[11px]" style={{ color: "var(--text-subtle)" }}>
              {t(provenanceKey(report.provenance))}
            </p>
          </section>
        );
      })}
    </div>
  );
}
