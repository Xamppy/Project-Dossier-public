"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import CalendarDossierPreview from "@/components/dashboard/CalendarDossierPreview";
import { calendarUiLabels } from "@/i18n/calendar-ui-labels";
import type { CalendarEventModel } from "@/lib/calendar-events";
import {
  DossierApiError,
  type CalendarGenerarDossierItem,
  type CalendarProvider,
} from "@/lib/dossier-api";
import { formatMeetingTimeRange } from "@/lib/format";
import { useDossierJobs } from "@/providers/DossierJobsProvider";
import { usePreferences, useTranslation } from "@/providers/PreferencesProvider";

type Props = {
  event: CalendarEventModel;
  onClose: () => void;
  /** Elemento que abrió el detalle: recupera el foco al cerrarse. */
  returnFocusTo: HTMLElement | null;
  /** Dónde dejar el foco si el elemento anterior ya no está en el documento. */
  fallbackFocus?: () => HTMLElement | null;
};

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

const PROVIDER_COLOR: Record<CalendarProvider, string> = {
  google: "var(--dossier-google, #0f9d58)",
  microsoft: "var(--dossier-outlook, #2a7de1)",
};

function descriptionHasPersonHint(text: string): boolean {
  return /(?:contacto|contact|nombre|name|nome|nom|contatto|kontakt)\s*:/i.test(text);
}

/** Día completo: fechas civiles; el fin es exclusivo, así que se muestra el día anterior. */
function allDayLabel(start: string, end: string | null, locale: string, allDay: string): string {
  const fmt = new Intl.DateTimeFormat(locale, { timeZone: "UTC", dateStyle: "full" });
  const first = new Date(`${start}T00:00:00Z`);
  const lastDay = end ? new Date(Date.parse(`${end}T00:00:00Z`) - 86_400_000) : first;
  const range =
    lastDay.getTime() > first.getTime() ? `${fmt.format(first)} – ${fmt.format(lastDay)}` : fmt.format(first);
  return `${range} · ${allDay}`;
}

export default function CalendarEventDetails({ event, onClose, returnFocusTo, fallbackFocus }: Props) {
  const { t, locale } = useTranslation();
  const { preferences, effectiveTimezone } = usePreferences();
  const { enqueueCalendarJob, isEventGenerating, getJobForEvent } = useDossierJobs();
  const ui = useMemo(() => calendarUiLabels(locale), [locale]);

  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const submitting = useRef(false);
  const [genErr, setGenErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });

  // Foco al abrir, Escape y trampa de Tab; al cerrar, el foco vuelve a quien abrió el detalle.
  useEffect(() => {
    const dialog = dialogRef.current;
    dialog?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !dialog) return;
      const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        e.preventDefault();
        dialog.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (!dialog.contains(active) || active === dialog) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      const target = returnFocusTo?.isConnected ? returnFocusTo : (fallbackFocus?.() ?? null);
      target?.focus();
    };
  }, [returnFocusTo, fallbackFocus]);

  const provider = event.provider;
  const eventId = event.eventId;
  const generating = busy || isEventGenerating(eventId, provider);
  const job = getJobForEvent(eventId, provider);
  const providerName = provider === "google" ? ui.providerGoogle : ui.providerOutlook;
  const generateLabel = t(provider === "google" ? "overview.google_generate_dossier" : "overview.microsoft_generate_dossier");
  const generatingLabel = t(provider === "google" ? "overview.google_generating" : "overview.microsoft_generating");

  const when = event.allDay
    ? allDayLabel(event.start, event.end, preferences.locale, ui.allDay)
    : formatMeetingTimeRange(
        event.start,
        event.end ?? undefined,
        { locale: preferences.locale, timezone: effectiveTimezone },
        { allDayLabel: ui.allDay },
      ).fullLabel;

  const result =
    job?.job_type === "calendar_manual" && job.status === "completed" && job.result
      ? (job.result as CalendarGenerarDossierItem)
      : null;
  const research = result?.dossier_persona_research as { warnings?: string[] } | undefined;
  const warnings = Array.isArray(research?.warnings)
    ? research.warnings.filter((w): w is string => typeof w === "string" && w.trim().length > 0)
    : undefined;
  const hasResult = Boolean(
    result && (result.dossier_corporativo?.trim() || result.dossier_persona?.trim() || result.dossier_generado?.trim()),
  );

  async function generate() {
    if (!eventId || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setGenErr(null);
    try {
      await enqueueCalendarJob(provider, { eventId, reunion: event.raw });
    } catch (e) {
      setGenErr(
        e instanceof DossierApiError
          ? e.message
          : t(provider === "google" ? "overview.google_generate_error" : "overview.microsoft_generate_error"),
      );
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center md:items-stretch md:justify-end">
      <div
        className="absolute inset-0"
        style={{ backgroundColor: "rgba(4, 10, 22, 0.55)" }}
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative flex max-h-[92vh] w-full flex-col overflow-y-auto rounded-t-2xl border p-5 shadow-2xl outline-none md:max-h-none md:w-[28rem] md:rounded-none md:rounded-l-2xl"
        style={{ backgroundColor: "var(--bg-page)", borderColor: "var(--border-default)" }}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-subtle)" }}>
              {ui.detailsTitle}
            </p>
            <h2 id={titleId} className="mt-1 break-words text-lg font-semibold" style={{ color: "var(--text-primary)" }}>
              {event.title}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-lg border px-2.5 py-1 text-xs font-medium"
            style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
          >
            {ui.close}
          </button>
        </div>

        <dl className="mt-4 space-y-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          <div>
            <dt className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>{ui.when}</dt>
            <dd>{when}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>{ui.calendarName}</dt>
            <dd className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: PROVIDER_COLOR[provider] }} aria-hidden />
              <span>{providerName}</span>
            </dd>
          </div>
          {event.participants ? (
            <div>
              <dt className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>{ui.participants}</dt>
              <dd className="break-words">{event.participants}</dd>
            </div>
          ) : null}
          {event.location ? (
            <div>
              <dt className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>{ui.location}</dt>
              <dd className="break-words">{event.location}</dd>
            </div>
          ) : null}
        </dl>

        <div className="mt-4">
          <p className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>{ui.description}</p>
          {event.description ? (
            <>
              <pre
                className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border px-2.5 py-2 font-sans text-xs leading-relaxed"
                style={{
                  borderColor: descriptionHasPersonHint(event.description) ? "rgba(52,211,153,0.25)" : "var(--border-default)",
                  backgroundColor: "var(--bg-input)",
                  color: "var(--text-secondary)",
                }}
              >
                {event.description}
              </pre>
              {!descriptionHasPersonHint(event.description) ? (
                <p className="ui-text-warning mt-1 text-xs">{t("overview.calendar_description_no_contact")}</p>
              ) : null}
            </>
          ) : (
            <p className="ui-alert ui-alert-warning mt-1 px-2.5 py-2 text-xs">{t("overview.calendar_description_empty")}</p>
          )}
        </div>

        <div className="mt-5 flex flex-col gap-2">
          <button
            type="button"
            disabled={!eventId || generating}
            onClick={() => void generate()}
            className="self-start rounded-lg px-3.5 py-2 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ backgroundImage: "linear-gradient(135deg, var(--accent-from) 0%, var(--accent-to) 100%)" }}
          >
            {generating ? generatingLabel : generateLabel}
          </button>
          {!eventId ? (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>{ui.noEventId}</p>
          ) : null}
          {genErr ? (
            <p className="ui-alert ui-alert-error px-2.5 py-2 text-xs" role="alert">{genErr}</p>
          ) : null}
          {job?.status === "failed" && job.error_message ? (
            <p className="ui-alert ui-alert-error px-2.5 py-2 text-xs" role="alert">{job.error_message}</p>
          ) : null}
        </div>

        {hasResult && result ? (
          <CalendarDossierPreview
            eventKey={event.key}
            activeEventKey={event.key}
            tema={result.reunion?.tema || event.title}
            corporate={result.dossier_corporativo ?? null}
            person={result.dossier_persona ?? null}
            lushaWarnings={warnings}
            savedCorporate={result.saved_dossiers?.corporate}
            savedPerson={result.saved_dossiers?.person}
            savedFolder={result.saved_dossiers?.folder}
            corporateSkippedFreePlan={result.corporate_skipped_plan_free === true}
          />
        ) : null}
      </div>
    </div>
  );
}
