"use client";

import type { ReactNode } from "react";
import DashboardCard from "@/components/dashboard/DashboardCard";
import CalendarMeetingFormatGuide from "@/components/dashboard/CalendarMeetingFormatGuide";
import CalendarIntegrationPanel from "@/components/dashboard/CalendarIntegrationPanel";
import { useCalendarProvidersConfigured } from "@/hooks/useCalendarProvidersConfigured";
import type { CalendarProvider } from "@/lib/dossier-api";
import { useTranslation } from "@/providers/PreferencesProvider";

function CalendarSectionIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" aria-hidden>
      <rect x="3" y="4" width="18" height="18" rx="2.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M3 9h18" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 3v3M16 3v3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <rect x="7" y="12" width="3" height="3" rx="0.5" fill="currentColor" opacity="0.85" />
      <rect x="12" y="12" width="3" height="3" rx="0.5" fill="currentColor" opacity="0.45" />
      <rect x="7" y="16.5" width="3" height="3" rx="0.5" fill="currentColor" opacity="0.45" />
    </svg>
  );
}

function OutlookIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" aria-hidden>
      <rect x="3" y="5" width="18" height="14" rx="2" fill="#0078d4" opacity="0.15" />
      <path
        d="M4 8.5 12 13l8-4.5V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v1.5Z"
        fill="#0078d4"
      />
      <rect x="4" y="7" width="16" height="11" rx="1.5" stroke="#0078d4" strokeWidth="1.5" />
    </svg>
  );
}

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden>
      <rect x="3" y="4" width="18" height="18" rx="2" fill="#4285f4" opacity="0.12" />
      <rect x="3" y="4" width="18" height="18" rx="2" stroke="#4285f4" strokeWidth="1.5" fill="none" />
      <path
        d="M12 8v4l3 2"
        stroke="#4285f4"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

function CalendarProviderColumn({
  provider,
  titleKey,
  accent,
  icon,
}: {
  provider: CalendarProvider;
  titleKey: "overview.microsoft_title" | "overview.google_title";
  accent: string;
  icon: ReactNode;
}) {
  const { t } = useTranslation();

  return (
    <div
      className="flex h-full min-w-0 flex-col rounded-xl border p-4"
      style={{
        borderColor: "var(--border-default)",
        backgroundColor: "var(--bg-input)",
      }}
    >
      <div
        className="mb-4 flex items-center gap-2.5 border-b pb-3"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
          style={{
            backgroundColor: "var(--bg-surface-strong)",
            color: accent,
          }}
        >
          {icon}
        </div>
        <h4 className="truncate text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
          {t(titleKey)}
        </h4>
      </div>

      <CalendarIntegrationPanel provider={provider} embedded />
    </div>
  );
}

const COLUMNAS: {
  provider: CalendarProvider;
  titleKey: "overview.microsoft_title" | "overview.google_title";
  accent: string;
  icon: ReactNode;
}[] = [
  { provider: "microsoft", titleKey: "overview.microsoft_title", accent: "#0078d4", icon: <OutlookIcon /> },
  { provider: "google", titleKey: "overview.google_title", accent: "#4285f4", icon: <GoogleIcon /> },
];

export default function OverviewCalendarsSection() {
  const { t } = useTranslation();
  const configurados = useCalendarProvidersConfigured();
  // Se oculta solo si el servidor dice explícitamente que ese OAuth no está configurado.
  const columnas = COLUMNAS.filter((c) => configurados[c.provider] !== false);

  return (
    <section className="mb-8">
      <DashboardCard>
        <div
          className="mb-5 border-b pb-5"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <div className="flex min-w-0 items-start gap-3.5">
            <div
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl"
              style={{
                backgroundImage:
                  "linear-gradient(135deg, var(--accent-from) 0%, var(--accent-to) 100%)",
                color: "#fff",
                boxShadow: "0 4px 14px rgba(10, 20, 40, 0.12)",
              }}
            >
              <CalendarSectionIcon />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-3">
                <h3
                  className="text-lg font-semibold tracking-tight sm:text-xl"
                  style={{ color: "var(--text-primary)" }}
                >
                  {t("overview.calendars_title")}
                </h3>
                <div className="shrink-0 self-center">
                  <CalendarMeetingFormatGuide />
                </div>
              </div>
              <p className="mt-1 text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
                {t("overview.calendars_intro")}
              </p>
            </div>
          </div>
        </div>

        <div className={`grid grid-cols-1 gap-4 ${columnas.length > 1 ? "xl:grid-cols-2" : ""}`}>
          {columnas.map((c) => (
            <CalendarProviderColumn key={c.provider} {...c} />
          ))}
        </div>
      </DashboardCard>
    </section>
  );
}
