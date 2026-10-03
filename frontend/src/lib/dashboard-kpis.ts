import type { Locale, TranslationKey } from "@/i18n/types";
import type { DashboardMetricContext, DashboardSummary } from "@/lib/dossier-api";

type Translate = (key: TranslationKey, params?: Record<string, string | number>) => string;

export type KpiCardId = "pending" | "coverage" | "on_time" | "credits";

export type KpiCardModel = {
  id: KpiCardId;
  label: string;
  value: string;
  /** Líneas auxiliares bajo el valor (periodo, conteos, causa del estado). */
  details?: string[];
  /** Texto que lee el lector de pantalla además del rótulo. */
  description?: string;
  trendVariant?: "default" | "positive" | "warning";
  busy?: boolean;
};

export type KpiStatus = "loading" | "ready" | "error" | "idle";

const NO_VALUE = "—";

const INTL_LOCALE: Record<Locale, string> = {
  en: "en-US",
  "en-gb": "en-GB",
  es: "es-ES",
  pt: "pt-PT",
  it: "it-IT",
  fr: "fr-FR",
  de: "de-DE",
};

/** Porcentaje (0–100) con hasta un decimal según el idioma. El backend conserva la precisión. */
export function formatPercent(value: number, locale: Locale): string {
  return new Intl.NumberFormat(INTL_LOCALE[locale] ?? "en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value / 100);
}

const REASON_KEYS: Record<string, TranslationKey> = {
  no_calendar_connected: "stat.reason_no_calendar",
  no_meetings_in_period: "stat.reason_no_meetings",
  calendar_reauth_required: "stat.reason_reauth",
  calendar_unavailable: "stat.reason_unavailable",
  calendar_incomplete: "stat.reason_incomplete",
  calendar_busy: "stat.reason_busy",
  evidence_unavailable: "stat.reason_evidence",
};

function reasonText(ctx: DashboardMetricContext, t: Translate): string {
  return t(REASON_KEYS[ctx.reason ?? ""] ?? "stat.reason_unavailable");
}

const num = (n: number | null | undefined): string => (typeof n === "number" ? String(n) : NO_VALUE);

type BuildInput = {
  summary: DashboardSummary | null;
  status: KpiStatus;
  t: Translate;
  locale: Locale;
  /** Fecha legible en las preferencias de la persona (zona y formato). */
  formatDate: (iso: string) => string;
  /** Saldo ya conocido por otra vía si la consulta del resumen falló. */
  fallbackCredits?: { balance?: number | null; limit?: number | null } | null;
};

function creditsCard(
  balance: number | null | undefined,
  limit: number | null | undefined,
  t: Translate,
  busy: boolean,
): KpiCardModel {
  const known = typeof balance === "number";
  return {
    id: "credits",
    label: t("stat.credits_balance"),
    value: known ? String(balance) : NO_VALUE,
    details: known && typeof limit === "number" && limit > 0 ? [t("stat.credits_monthly_hint", { limit })] : [],
    busy,
  };
}

/** Las cuatro tarjetas de Resumen. Nunca convierte «sin datos» o «falló» en un cero. */
export function buildKpiCards({ summary, status, t, locale, formatDate, fallbackCredits }: BuildInput): KpiCardModel[] {
  const labels = {
    pending: t("stat.prep_pending_label"),
    coverage: t("stat.prep_coverage_label"),
    on_time: t("stat.prep_on_time_label"),
  };

  if (!summary) {
    const busy = status === "loading" || status === "idle";
    const nota = status === "error" ? [t("stat.error_load")] : [];
    const sinDato = (id: KpiCardId, label: string): KpiCardModel => ({
      id,
      label,
      value: NO_VALUE,
      details: nota,
      busy,
    });
    const credits = creditsCard(fallbackCredits?.balance, fallbackCredits?.limit, t, busy);
    if (credits.value === NO_VALUE) credits.details = nota;
    return [
      sinDato("pending", labels.pending),
      sinDato("coverage", labels.coverage),
      sinDato("on_time", labels.on_time),
      credits,
    ];
  }

  const up = summary.upcoming;
  const hist = summary.history;

  // ── reuniones por preparar y cobertura
  const upOk = up.state === "ok" || up.state === "empty" || up.state === "partial";
  const upEmpty = up.state === "empty";
  const upNote = upOk ? [] : [reasonText(up, t)];

  const pending: KpiCardModel = {
    id: "pending",
    label: labels.pending,
    value: upOk ? num(up.pending_meetings) : NO_VALUE,
    details: upEmpty
      ? [t("stat.reason_no_meetings")]
      : upOk
        ? [t("stat.prep_pending_detail", { total: up.eligible_meetings ?? 0 })]
        : upNote,
    trendVariant: upOk && (up.pending_meetings ?? 0) > 0 ? "warning" : "default",
  };

  const coverage: KpiCardModel = {
    id: "coverage",
    label: labels.coverage,
    value: upOk && up.coverage_percent != null ? formatPercent(up.coverage_percent, locale) : NO_VALUE,
    details: upEmpty
      ? [t("stat.reason_no_meetings")]
      : upOk
        ? [t("stat.prep_coverage_detail", { prepared: up.prepared_meetings ?? 0, total: up.eligible_meetings ?? 0 })]
        : upNote,
  };

  // ── preparadas a tiempo (reuniones y dossiers son cosas distintas)
  const hOk = hist.state === "ok" || hist.state === "empty" || hist.state === "partial";
  const onTimeDetails: string[] = [];
  if (hist.state === "empty") {
    onTimeDetails.push(t("stat.reason_no_meetings"));
  } else if (hOk) {
    onTimeDetails.push(
      t("stat.prep_on_time_meetings", {
        count: hist.manually_prepared_on_time_meetings ?? 0,
        total: hist.eligible_meetings ?? 0,
      }),
      t("stat.prep_on_time_dossiers", { count: hist.manual_on_time_dossiers ?? 0 }),
    );
  } else {
    onTimeDetails.push(reasonText(hist, t));
  }
  if (hist.state === "partial" && hist.measured_from) {
    onTimeDetails.push(t("stat.history_partial", { date: formatDate(hist.measured_from) }));
  }
  const onTime: KpiCardModel = {
    id: "on_time",
    label: labels.on_time,
    value: hOk && hist.on_time_percent != null ? formatPercent(hist.on_time_percent, locale) : NO_VALUE,
    details: onTimeDetails,
    description: t("stat.prep_on_time_explain"),
  };

  const credits = creditsCard(summary.credits.balance, summary.credits.monthly_limit, t, false);
  if (summary.credits.state !== "ok" && summary.credits.balance == null) {
    credits.details = [reasonText(summary.credits, t)];
  }

  return [pending, coverage, onTime, credits];
}
