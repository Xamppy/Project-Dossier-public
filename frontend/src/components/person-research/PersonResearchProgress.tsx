"use client";

/**
 * Etapas de la investigación de una persona (S5.4), tal como las declara el
 * servidor en el catálogo del scope: no hay una lista fija del cliente. Sirve
 * para Personas y para cada asistente de una reunión de Calendario.
 *
 * La modalidad sale del scope (`research_source`), nunca del formulario. En Web
 * pública el trabajo es una llamada a la IA sin buscador: se dice así y no se
 * muestran búsquedas, páginas ni fuentes que no ocurren.
 */
import type { DossierPersonProgressScope, DossierStageProgressEntry } from "@/lib/dossier-api";
import { useTranslation } from "@/providers/PreferencesProvider";
import {
  ProgressGlyph,
  entryTone,
  stageLabel,
  stageStatusText,
  toneColor,
} from "@/components/dossier/progress-display";

type Props = {
  scope: DossierPersonProgressScope;
  variant?: "full" | "compact";
};

/** Etapa que resume a la persona en una línea: la que corre o, si no, el guardado. */
function summaryStage(scope: DossierPersonProgressScope): DossierStageProgressEntry | undefined {
  return (
    scope.stages.find((s) => s.status === "running") ??
    scope.stages.find((s) => s.stage_id === "person.persist") ??
    scope.stages.at(-1)
  );
}

export default function PersonResearchProgress({ scope, variant = "full" }: Props) {
  const { t } = useTranslation();
  const source = scope.research_source;
  const name = scope.label ?? t("dossier_jobs.person_label");
  const mode = t(source === "pdl" ? "person_research.source_pdl" : "person_research.source_gemini");

  if (variant === "compact") {
    const stage = summaryStage(scope);
    const tone = stage ? entryTone(stage) : "pending";
    return (
      <p className="mt-1 flex flex-wrap items-baseline gap-x-1.5 text-xs" data-status={stage?.status}>
        <ProgressGlyph tone={tone} />
        <span className="font-medium" style={{ color: "var(--text-primary)" }}>
          {name}
        </span>
        {stage ? (
          <span style={{ color: toneColor(tone) }}>
            {`${stageLabel(t, stage.stage_id, source)} · ${stageStatusText(t, stage, source)}`}
          </span>
        ) : null}
      </p>
    );
  }

  return (
    <div>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        {t("progress.mode_label", { mode })}
        {source === "gemini_web" && !scope.live_web_search ? (
          <span className="block">{t("progress.no_live_web_search")}</span>
        ) : null}
      </p>
      {scope.origin === "redis_cache" ? (
        <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
          {t("progress.from_cache")}
        </p>
      ) : null}
      <ol aria-label={t("progress.stages_aria", { name })} className="mt-1.5 space-y-1 text-xs">
        {scope.stages.map((stage) => {
          const tone = entryTone(stage);
          return (
            <li
              key={stage.stage_id}
              data-status={stage.status}
              data-tone={tone}
              aria-current={stage.status === "running" ? "step" : undefined}
              className="flex flex-wrap items-baseline gap-x-1.5"
            >
              <ProgressGlyph tone={tone} />
              <span data-stage-label className="font-medium" style={{ color: "var(--text-primary)" }}>
                {stageLabel(t, stage.stage_id, source)}
              </span>
              <span data-stage-status style={{ color: toneColor(tone) }}>
                {stageStatusText(t, stage, source)}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
