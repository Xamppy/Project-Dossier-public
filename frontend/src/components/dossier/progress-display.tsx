"use client";

/**
 * Textos e iconos compartidos del progreso (S5.4). El estado siempre se dice con
 * texto: el color y el icono solo lo refuerzan.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  DossierAgentProgressEntry,
  DossierCorporateAgentName,
  DossierPersonResearchSource,
  DossierPersonStageId,
  DossierProgressReasonCode,
  DossierStageProgressEntry,
} from "@/lib/dossier-api";
import type { TranslationKey } from "@/i18n/types";
import { useTranslation } from "@/providers/PreferencesProvider";

type T = (key: TranslationKey, params?: Record<string, string | number>) => string;

export type ProgressTone = "pending" | "running" | "success" | "warning" | "error" | "muted";

export function agentLabel(t: T, agent: DossierCorporateAgentName): string {
  return t(`progress.agent.${agent}` as TranslationKey);
}

export function stageLabel(t: T, stage: DossierPersonStageId, source: DossierPersonResearchSource): string {
  // En Web pública el análisis contextual es el informe entero: una llamada a DeepSeek sin buscador.
  if (stage === "person.context_analysis" && source === "gemini_web") {
    return t("progress.stage.person.context_analysis_web");
  }
  return t(`progress.stage.${stage}` as TranslationKey);
}

function reasonText(t: T, reason: DossierProgressReasonCode | null): string | null {
  return reason ? t(`progress.reason.${reason}` as TranslationKey) : null;
}

function withReason(t: T, base: string, reason: DossierProgressReasonCode | null): string {
  const text = reasonText(t, reason);
  return text ? `${base} · ${text}` : base;
}

function completedText(t: T, reason: DossierProgressReasonCode | null): string {
  // Sin coincidencias es un resultado, no un error.
  if (reason === "no_matches") return t("progress.reason.no_matches");
  if (reason === "cache_hit") return t("progress.reason.cache_hit_found");
  if (reason === "cache_miss") return t("progress.reason.cache_miss");
  return t("progress.status.completed");
}

export function agentStatusText(t: T, entry: DossierAgentProgressEntry): string {
  switch (entry.status) {
    case "running":
      return t(entry.agent_name === "synthesize_llm" ? "progress.status.running_synthesis" : "progress.status.running_agent");
    case "completed":
      return completedText(t, entry.reason_code);
    case "skipped":
      return withReason(t, t("progress.status.skipped"), entry.reason_code);
    case "failed":
      return withReason(t, t("progress.status.failed"), entry.reason_code);
    case "cancelled":
      return t("progress.status.cancelled");
    default:
      return t("progress.status.pending");
  }
}

export function stageStatusText(
  t: T,
  entry: DossierStageProgressEntry,
  source: DossierPersonResearchSource,
): string {
  switch (entry.status) {
    case "running":
      return entry.stage_id === "person.context_analysis" && source === "gemini_web"
        ? t("progress.status.running_ai_report")
        : t("progress.status.running");
    case "completed":
      if (entry.used_in_final === false) return t("progress.status.not_used_in_final");
      return completedText(t, entry.reason_code);
    case "skipped":
      return withReason(t, t("progress.status.skipped"), entry.reason_code);
    case "failed":
      if (entry.recovered_by) return t("progress.status.recovered");
      return withReason(t, t("progress.status.failed"), entry.reason_code);
    case "cancelled":
      return t("progress.status.cancelled");
    default:
      return t("progress.status.pending");
  }
}

export function entryTone(entry: DossierAgentProgressEntry | DossierStageProgressEntry): ProgressTone {
  switch (entry.status) {
    case "running":
      return "running";
    case "completed":
      return "success";
    case "failed":
      return "recovered_by" in entry && entry.recovered_by ? "warning" : "error";
    case "pending":
      return "pending";
    default:
      return "muted";
  }
}

const TONE_STYLE: Record<ProgressTone, { glyph: string; color: string }> = {
  pending: { glyph: "○", color: "var(--text-subtle)" },
  running: { glyph: "●", color: "var(--accent-from)" },
  success: { glyph: "✓", color: "var(--status-success)" },
  warning: { glyph: "!", color: "var(--status-warning)" },
  error: { glyph: "✕", color: "var(--status-error)" },
  muted: { glyph: "–", color: "var(--text-subtle)" },
};

/** Icono decorativo: el estado ya está dicho en texto al lado. */
export function ProgressGlyph({ tone }: { tone: ProgressTone }) {
  const { glyph, color } = TONE_STYLE[tone];
  return (
    <span
      aria-hidden
      className={`inline-flex w-4 shrink-0 justify-center font-semibold ${tone === "running" ? "motion-safe:animate-pulse" : ""}`}
      style={{ color }}
    >
      {glyph}
    </span>
  );
}

export function toneColor(tone: ProgressTone): string {
  if (tone === "error") return "var(--status-error)";
  if (tone === "warning") return "var(--status-warning)";
  return "var(--text-muted)";
}

/** Marca de vista previa: el contenido todavía no es un dossier guardado. */
export function ProvisionalBadge() {
  const { t } = useTranslation();
  return (
    <span
      className="rounded-full border px-2 py-0.5 text-[11px] font-medium"
      style={{ borderColor: "var(--alert-info-border)", color: "var(--alert-info-text)", backgroundColor: "var(--alert-info-bg)" }}
    >
      {t("progress.preview_badge")}
    </span>
  );
}

/**
 * Vista previa en Markdown con el renderer existente (react-markdown + GFM, como el
 * detalle del dossier). Sin HTML crudo; los enlaces abren aparte y sin `opener`.
 */
export function MarkdownPreview({ content, truncated }: { content: string; truncated: boolean }) {
  const { t } = useTranslation();
  return (
    <>
      <div
        className="api-md max-h-72 max-w-none overflow-auto rounded-md p-2.5 text-xs leading-relaxed [&_h1]:mb-1 [&_h1]:text-sm [&_h1]:font-semibold [&_h2]:mb-1 [&_h2]:mt-2 [&_h2]:text-sm [&_h2]:font-semibold [&_h3]:font-semibold [&_li]:ml-4 [&_ol]:list-decimal [&_p]:my-1 [&_ul]:list-disc"
        style={{ backgroundColor: "var(--bg-surface-strong)", color: "var(--text-secondary)" }}
        // Desplazable con teclado cuando el texto es largo.
        tabIndex={0}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          skipHtml
          components={{
            a: ({ href, children }) => (
              <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
                {children}
              </a>
            ),
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
      {truncated ? (
        <p className="mt-1 text-[11px]" style={{ color: "var(--text-subtle)" }}>
          {t("progress.preview_truncated")}
        </p>
      ) : null}
    </>
  );
}
