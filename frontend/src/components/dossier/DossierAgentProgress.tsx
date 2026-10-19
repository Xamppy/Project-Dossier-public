"use client";

/**
 * Búsquedas de la empresa de un job (S5.4): un agente del grafo por fila, en el
 * orden que declara el servidor, y las vistas previas de Europa, Noticias y el
 * resumen. UK y USA no tienen vista previa por decisión del ADR 0009: solo
 * muestran su estado, sin hueco ni error.
 */
import type { DossierCorporateProgressScope } from "@/lib/dossier-api";
import { CORPORATE_AGENTS } from "@/lib/dossier-job-progress";
import { useTranslation } from "@/providers/PreferencesProvider";
import {
  MarkdownPreview,
  ProgressGlyph,
  ProvisionalBadge,
  agentLabel,
  agentStatusText,
  entryTone,
  toneColor,
} from "@/components/dossier/progress-display";

type Props = {
  scope: DossierCorporateProgressScope;
  variant?: "full" | "compact";
  /** Vistas previas provisionales (solo en la variante completa). */
  showPreviews?: boolean;
};

export default function DossierAgentProgress({ scope, variant = "full", showPreviews = false }: Props) {
  const { t } = useTranslation();
  const compact = variant === "compact";
  const name = scope.label ?? t("dossier_jobs.corporate_label");
  const previews = [...scope.partial_results].sort(
    (a, b) => CORPORATE_AGENTS.indexOf(a.agent_name) - CORPORATE_AGENTS.indexOf(b.agent_name),
  );

  return (
    <div className={compact ? "mt-2" : "mt-3"}>
      {compact ? null : (
        <h4 className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
          {t("progress.company_title")}
          {scope.label ? (
            <span className="font-normal" style={{ color: "var(--text-muted)" }}>
              {" "}
              · {scope.label}
            </span>
          ) : null}
        </h4>
      )}
      {scope.origin === "redis_cache" && !compact ? (
        <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
          {t("progress.from_cache")}
        </p>
      ) : null}
      <ol
        aria-label={t("progress.agents_aria", { name })}
        className={compact ? "mt-1 space-y-0.5 text-xs" : "mt-1.5 space-y-1 text-xs"}
      >
        {scope.agents.map((agent) => {
          const tone = entryTone(agent);
          return (
            <li
              key={agent.agent_name}
              data-status={agent.status}
              data-tone={tone}
              aria-current={agent.status === "running" ? "step" : undefined}
              className="flex flex-wrap items-baseline gap-x-1.5"
            >
              <ProgressGlyph tone={tone} />
              <span data-agent-label className="font-medium" style={{ color: "var(--text-primary)" }}>
                {agentLabel(t, agent.agent_name)}
              </span>
              <span data-agent-status style={{ color: toneColor(tone) }}>
                {agentStatusText(t, agent)}
              </span>
            </li>
          );
        })}
      </ol>
      {showPreviews && !compact
        ? previews.map((preview) => (
            <section
              key={preview.section}
              role="group"
              aria-label={`${agentLabel(t, preview.agent_name)} · ${t("progress.preview_badge")}`}
              className="mt-2 rounded-md border p-2"
              style={{ borderColor: "var(--border-default)" }}
            >
              <div className="mb-1.5 flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium" style={{ color: "var(--accent-from)" }}>
                  {agentLabel(t, preview.agent_name)}
                </span>
                <ProvisionalBadge />
              </div>
              <MarkdownPreview content={preview.content} truncated={preview.truncated} />
            </section>
          ))
        : null}
    </div>
  );
}
