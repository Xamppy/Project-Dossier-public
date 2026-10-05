"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CALENDAR_MEETING_FORMAT_EXAMPLE,
  CALENDAR_MEETING_SUBJECT_EXAMPLES,
} from "@/lib/calendar-meeting-format";
import { useTranslation } from "@/providers/PreferencesProvider";

type Props = {
  /** Abre el modal al montar (p. ej. aviso de descripción incompleta). */
  defaultOpen?: boolean;
  /** `button`: botón suelto; `inline`: enlace compacto bajo un evento. */
  variant?: "button" | "inline";
};

function GuideContent({
  copied,
  onCopy,
  templateExample,
  compact,
}: {
  copied: boolean;
  onCopy: () => void;
  templateExample: string;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  const subjectExamples = (
    t("calendar.guide.subject_examples") || CALENDAR_MEETING_SUBJECT_EXAMPLES.join("\n")
  )
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return (
    <div
      className={compact ? "space-y-3 text-xs" : "space-y-4 text-sm"}
      style={{ color: "var(--text-muted)" }}
    >
      <p className="leading-relaxed">{t("calendar.guide.intro")}</p>

      <div>
        <p className="mb-1.5 font-medium" style={{ color: "var(--text-secondary)" }}>
          {t("calendar.guide.template_title")}
        </p>
        <pre
          className={
            compact
              ? "overflow-x-auto whitespace-pre-wrap rounded-lg border px-3 py-2 font-mono text-[11px] leading-relaxed"
              : "overflow-x-auto whitespace-pre-wrap rounded-lg border px-3 py-2.5 font-mono text-xs leading-relaxed"
          }
          style={{
            borderColor: "var(--border-default)",
            backgroundColor: "var(--bg-input)",
            color: "var(--text-primary)",
          }}
        >
          {templateExample}
        </pre>
        <button
          type="button"
          onClick={onCopy}
          className={`ui-hover-scale-btn mt-2 inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold ${
            copied ? "" : "ui-hover-surface"
          }`}
          style={{
            borderColor: copied ? "rgba(52,211,153,0.45)" : "var(--border-default)",
            color: copied ? "var(--status-success)" : "var(--text-secondary)",
            backgroundColor: copied ? "var(--alert-success-bg)" : "var(--bg-panel-muted)",
          }}
        >
          {copied ? (
            <>
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-3.5 w-3.5"
                aria-hidden
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
              {t("calendar.guide.copied")}
            </>
          ) : (
            t("calendar.guide.copy")
          )}
        </button>
      </div>

      <div>
        <p className="mb-1.5 font-medium" style={{ color: "var(--text-secondary)" }}>
          {t("calendar.guide.fields_title")}
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>{t("calendar.guide.field_company")}</li>
          <li>{t("calendar.guide.field_contact")}</li>
          <li>{t("calendar.guide.field_contact_multi")}</li>
          <li>{t("calendar.guide.field_job")}</li>
          <li>{t("calendar.guide.field_email")}</li>
          <li>{t("calendar.guide.field_country")}</li>
        </ul>
      </div>

      <div>
        <p className="mb-1.5 font-medium" style={{ color: "var(--text-secondary)" }}>
          {t("calendar.guide.subject_title")}
        </p>
        <p className="leading-relaxed">{t("calendar.guide.subject_hint")}</p>
        <ul className="mt-1.5 list-disc space-y-0.5 pl-5 font-mono text-xs">
          {subjectExamples.map((ex) => (
            <li key={ex}>{ex}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function GuideModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const templateExample =
    t("calendar.guide.template_example") || CALENDAR_MEETING_FORMAT_EXAMPLE;

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(templateExample);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }, [templateExample]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="calendar-guide-title"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/50"
        aria-label={t("calendar.guide.close")}
        onClick={onClose}
      />
      <div
        className="relative z-10 flex max-h-[min(90vh,720px)] w-full max-w-lg flex-col overflow-hidden rounded-xl border shadow-2xl"
        style={{
          borderColor: "var(--border-strong)",
          backgroundColor: "var(--bg-panel)",
          boxShadow: "0 20px 48px rgba(10, 20, 40, 0.28)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="shrink-0 border-b px-5 py-4"
          style={{ borderColor: "var(--border-default)" }}
        >
          <h2
            id="calendar-guide-title"
            className="text-base font-semibold"
            style={{ color: "var(--text-primary)" }}
          >
            {t("calendar.guide.summary")}
          </h2>
        </div>
        <div className="overflow-y-auto px-5 py-4">
          <GuideContent
            copied={copied}
            onCopy={() => void onCopy()}
            templateExample={templateExample}
          />
        </div>
        <div
          className="shrink-0 border-t px-5 py-3 text-right"
          style={{ borderColor: "var(--border-default)" }}
        >
          <button
            type="button"
            onClick={onClose}
            className="ui-hover-scale-btn ui-hover-surface rounded-lg border px-4 py-2 text-sm font-medium"
            style={{
              borderColor: "var(--border-default)",
              color: "var(--text-primary)",
              backgroundColor: "var(--bg-panel-muted)",
            }}
          >
            {t("calendar.guide.close")}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function CalendarMeetingFormatGuide({
  defaultOpen = false,
  variant = "button",
}: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sincroniza el estado abierto/cerrado con el prop defaultOpen cuando este cambia.
    if (defaultOpen) setOpen(true);
  }, [defaultOpen]);

  const trigger =
    variant === "inline" ? (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-1 text-left text-xs font-medium underline-offset-2 hover:underline"
        style={{ color: "var(--alert-info-text)" }}
      >
        {t("calendar.guide.open_inline")}
      </button>
    ) : (
      <span className="group relative inline-flex">
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label={t("calendar.guide.summary")}
          className="flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border-default)] bg-[var(--bg-panel-muted)] text-base font-semibold leading-none text-[var(--text-muted)] transition ui-hover-surface group-hover:border-[var(--accent-from)] group-hover:text-[var(--accent-from)]"
        >
          ?
        </button>
        <span
          role="tooltip"
          className="pointer-events-none absolute right-full top-1/2 z-20 mr-2 -translate-y-1/2 translate-x-1 whitespace-nowrap rounded-lg border px-2.5 py-1.5 text-xs font-medium opacity-0 shadow-lg transition-all duration-150 group-hover:translate-x-0 group-hover:opacity-100"
          style={{
            borderColor: "var(--border-default)",
            backgroundColor: "var(--bg-panel)",
            color: "var(--text-primary)",
            boxShadow: "0 8px 24px rgba(10, 20, 40, 0.18)",
          }}
        >
          {t("calendar.guide.summary")}
        </span>
      </span>
    );

  return (
    <>
      {trigger}
      {open ? <GuideModal onClose={() => setOpen(false)} /> : null}
    </>
  );
}
