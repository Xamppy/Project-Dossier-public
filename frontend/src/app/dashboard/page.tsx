"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import DashboardCard from "@/components/dashboard/DashboardCard";
import OverviewCalendarsSection from "@/components/dashboard/OverviewCalendarsSection";
import OverviewKpiCards from "@/components/dashboard/OverviewKpiCards";
import TopBar from "@/components/dashboard/TopBar";
import UiAlert from "@/components/ui/UiAlert";
import {
  DossierApiError,
  fetchAuthMe,
  fetchDossiersFromApi,
  getStoredAccessToken,
  readDossierUserPreview,
  type AuthUser,
  type DossierListEntry,
  isDossierFolderEntry,
} from "@/lib/dossier-api";
import { getCalendarMeetingLabel, getCalendarMeetingSubject } from "@/lib/calendar-dossier-meta";
import { formatDossierStatusLabel } from "@/lib/dossier-list-utils";
import { canMutateDossiers } from "@/lib/org-role";
import { normalizePlanTier, planAllowsCorporateDossier } from "@/lib/plans";
import { stripHtmlToPlainLine } from "@/lib/strip-html";
import { useDashboardSummary } from "@/hooks/useDashboardSummary";
import { useDossierJobs } from "@/providers/DossierJobsProvider";
import { useTranslation } from "@/providers/PreferencesProvider";
import type { Locale, TranslationKey } from "@/i18n/types";

const quickActions: {
  href: string;
  labelKey: TranslationKey;
  descKey: TranslationKey;
  icon: ReactNode;
}[] = [
  {
    href: "/dashboard/automation",
    labelKey: "quick.email_label",
    descKey: "quick.email_desc",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
        <polyline points="22,6 12,13 2,6" />
      </svg>
    ),
  },
  {
    href: "/dashboard/dossiers",
    labelKey: "quick.search_label",
    descKey: "quick.search_desc",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
    ),
  },
  {
    href: "/dashboard/person-research",
    labelKey: "quick.person_research_label",
    descKey: "quick.person_research_desc",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
        <circle cx="12" cy="7" r="4" />
      </svg>
    ),
  },
  {
    href: "/dashboard/corporate",
    labelKey: "quick.corporate_label",
    descKey: "quick.corporate_desc",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
        <path d="M3 21h18" />
        <path d="M5 21V7l8-4v18" />
        <path d="M19 21V11l-6-4" />
        <path d="M9 9v.01" />
        <path d="M9 12v.01" />
        <path d="M9 15v.01" />
        <path d="M9 18v.01" />
      </svg>
    ),
  },
  {
    href: "/dashboard/settings",
    labelKey: "quick.addressbook_label",
    descKey: "quick.addressbook_desc",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
      </svg>
    ),
  },
];

function firstDisplayName(fullName: string, email: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts[0]) return parts[0];
  const local = email.split("@")[0]?.trim();
  return local || email;
}

function localeToDateLocale(locale: Locale): string {
  return locale === "en-gb" ? "en-GB" : locale;
}

function formatActivityDate(iso: string | null, locale: Locale): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString(localeToDateLocale(locale), {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export default function OverviewPage() {
  const { t, preferences } = useTranslation();
  const [welcomeName, setWelcomeName] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    const p = readDossierUserPreview();
    return p ? firstDisplayName(p.full_name, p.email) : "";
  });

  const [me, setMe] = useState<AuthUser | null>(null);
  const [dossierRows, setDossierRows] = useState<DossierListEntry[]>([]);
  const [dashError, setDashError] = useState<string | null>(null);
  const [dashLoad, setDashLoad] = useState<"idle" | "loading" | "ready">("idle");
  const { jobs } = useDossierJobs();
  // Cambia cuando termina una generación: los indicadores se vuelven a consultar.
  const completedJobsKey = useMemo(
    () => jobs.filter((j) => j.status === "completed").map((j) => j.id).sort().join(","),
    [jobs],
  );
  const hasSession = typeof window !== "undefined" && !!getStoredAccessToken();
  const kpi = useDashboardSummary({ enabled: hasSession, refreshKey: completedJobsKey });
  const [msOAuthBanner, setMsOAuthBanner] = useState<
    null | { kind: "ok" } | { kind: "error"; detail?: string }
  >(null);
  const [googleOAuthBanner, setGoogleOAuthBanner] = useState<
    null | { kind: "ok" } | { kind: "error"; detail?: string }
  >(null);

  useEffect(() => {
    let cancelled = false;

    async function loadWelcome() {
      const preview = readDossierUserPreview();
      if (preview) {
        if (!cancelled) setWelcomeName(firstDisplayName(preview.full_name, preview.email));
        return;
      }
      const token = getStoredAccessToken();
      if (token) {
        try {
          const u = await fetchAuthMe();
          if (!cancelled) setWelcomeName(firstDisplayName(u.full_name, u.email));
        } catch {
          if (!cancelled) setWelcomeName(t("overview.anonymous"));
        }
        return;
      }
      if (!cancelled) setWelcomeName(t("overview.anonymous"));
    }

    void loadWelcome();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const sp = new URLSearchParams(window.location.search);
    const ms = sp.get("calendar_microsoft");
    const g = sp.get("calendar_google");
    if (ms !== "ok" && ms !== "error" && g !== "ok" && g !== "error") return;
    const reason = sp.get("reason") || undefined;
    if (ms === "ok" || ms === "error") {
      sp.delete("calendar_microsoft");
    }
    if (g === "ok" || g === "error") {
      sp.delete("calendar_google");
    }
    sp.delete("reason");
    const rest = sp.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}`);
    queueMicrotask(() => {
      if (ms === "ok") setMsOAuthBanner({ kind: "ok" });
      else if (ms === "error") setMsOAuthBanner({ kind: "error", detail: reason });
      if (g === "ok") setGoogleOAuthBanner({ kind: "ok" });
      else if (g === "error") setGoogleOAuthBanner({ kind: "error", detail: reason });
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const token = getStoredAccessToken();
      if (!token) {
        setMe(null);
        setDossierRows([]);
        setDashLoad("idle");
        setDashError(null);
        return;
      }
      setDashLoad("loading");
      setDashError(null);
      void Promise.all([fetchAuthMe(), fetchDossiersFromApi(80)])
        .then(([user, list]) => {
          if (cancelled) return;
          setMe(user);
          setDossierRows(list.items);
          setDashLoad("ready");
        })
        .catch((e) => {
          if (cancelled) return;
          setMe(null);
          setDossierRows([]);
          setDashError(e instanceof DossierApiError ? e.message : t("overview.dashboard_load_error"));
          setDashLoad("ready");
        });
    });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const activityItems = useMemo(() => {
    return [...dossierRows]
      .sort((a, b) => {
        const ta = new Date(a.updated_at || a.created_at || 0).getTime();
        const tb = new Date(b.updated_at || b.created_at || 0).getTime();
        return tb - ta;
      })
      .slice(0, 6)
      .map((row) => {
        if (isDossierFolderEntry(row)) {
          const title =
            getCalendarMeetingSubject({
              calendar_meeting: row.calendar_meeting,
              dossier_data: row.dossiers[0]?.dossier_data,
            }) || stripHtmlToPlainLine(row.title) || "—";
          return {
            id: row.id,
            title,
            subtitle: getCalendarMeetingLabel(row) || formatDossierStatusLabel(row.status, t),
            dateLabel: formatActivityDate(row.updated_at || row.created_at, preferences.locale),
            href: `/dashboard/dossiers/folder/${row.id}`,
          };
        }
        const title =
          stripHtmlToPlainLine(row.subject_name || row.subject_email) || "—";
        return {
          id: row.id,
          title,
          subtitle: getCalendarMeetingLabel(row) || formatDossierStatusLabel(row.status, t),
          dateLabel: formatActivityDate(row.updated_at || row.created_at, preferences.locale),
          href: `/dashboard/dossiers/${row.id}`,
        };
      });
  }, [dossierRows, t, preferences.locale]);

  const titleName = welcomeName || t("overview.anonymous");
  const visibleQuickActions = useMemo(
    () => {
      const showCorporate = planAllowsCorporateDossier(normalizePlanTier(me?.organization_plan));
      const base = canMutateDossiers(me?.role)
        ? quickActions
        : quickActions.filter(
            (a) =>
              a.href !== "/dashboard/person-research" &&
              a.href !== "/dashboard/corporate" &&
              a.href !== "/dashboard/automation"
          );
      return showCorporate ? base : base.filter((a) => a.href !== "/dashboard/corporate");
    },
    [me?.role, me?.organization_plan]
  );
  return (
    <>
      <TopBar title={t("overview.title", { name: titleName })} subtitle={t("overview.subtitle")} />

      {dashError && (
        <UiAlert variant="warning" className="mb-4" role="alert">
          {dashError}
        </UiAlert>
      )}

      {msOAuthBanner && (
        <UiAlert
          variant={msOAuthBanner.kind === "ok" ? "success" : "error"}
          className="mb-4 flex flex-wrap items-start justify-between gap-2"
          role="status"
        >
          <span>
            {msOAuthBanner.kind === "ok"
              ? t("overview.microsoft_oauth_ok")
              : `${t("overview.microsoft_oauth_error")}${
                  msOAuthBanner.detail ? ` (${msOAuthBanner.detail.slice(0, 120)})` : ""
                }`}
          </span>
          <button
            type="button"
            className="shrink-0 underline underline-offset-2"
            onClick={() => setMsOAuthBanner(null)}
          >
            {t("overview.microsoft_banner_close")}
          </button>
        </UiAlert>
      )}

      {googleOAuthBanner && (
        <UiAlert
          variant={googleOAuthBanner.kind === "ok" ? "success" : "error"}
          className="mb-4 flex flex-wrap items-start justify-between gap-2"
          role="status"
        >
          <span>
            {googleOAuthBanner.kind === "ok"
              ? t("overview.google_oauth_ok")
              : `${t("overview.google_oauth_error")}${
                  googleOAuthBanner.detail ? ` (${googleOAuthBanner.detail.slice(0, 120)})` : ""
                }`}
          </span>
          <button
            type="button"
            className="shrink-0 underline underline-offset-2"
            onClick={() => setGoogleOAuthBanner(null)}
          >
            {t("overview.google_banner_close")}
          </button>
        </UiAlert>
      )}

      <OverviewKpiCards
        summary={kpi.summary}
        status={kpi.status}
        fallbackCredits={me ? { balance: me.credits_balance, limit: me.credits_monthly_limit } : null}
      />

      {canMutateDossiers(me?.role) ? <OverviewCalendarsSection /> : null}

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <DashboardCard title={t("activity.title")}>
          {dashLoad === "loading" ? (
            <p className="px-3 py-6 text-sm" style={{ color: "var(--text-muted)" }}>
              {t("dossiers.database_loading")}
            </p>
          ) : !getStoredAccessToken() ? (
            <p className="px-3 py-6 text-sm" style={{ color: "var(--text-muted)" }}>
              {t("overview.activity_login_hint")}
            </p>
          ) : activityItems.length === 0 ? (
            <p className="px-3 py-6 text-sm" style={{ color: "var(--text-muted)" }}>
              {t("overview.activity_empty")}
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {activityItems.map((item) => (
                <li key={item.id}>
                  <Link
                    href={item.href}
                    className="group flex min-w-0 items-center gap-3 rounded-lg border border-transparent px-3 py-2.5 transition-all duration-200 ease-out ui-hover-surface hover:border-[var(--border-default)]"
                    style={{ backgroundColor: "var(--bg-surface)" }}
                  >
                    <div
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors duration-200 group-hover:text-[var(--brand-cyan)]"
                      style={{
                        backgroundColor: "var(--bg-surface-strong)",
                        color: "var(--text-muted)",
                      }}
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                        <line x1="16" y1="13" x2="8" y2="13" />
                        <line x1="16" y1="17" x2="8" y2="17" />
                        <polyline points="10 9 9 9 8 9" />
                      </svg>
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span
                        className="truncate text-sm font-medium transition-colors duration-200 group-hover:text-[var(--brand-cyan)]"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {item.title}
                      </span>
                      <span
                        className="text-xs capitalize transition-colors duration-200 group-hover:text-[var(--text-secondary)]"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {item.subtitle}
                      </span>
                    </div>
                    <span
                      className="shrink-0 text-xs transition-colors duration-200 group-hover:text-[var(--text-muted)]"
                      style={{ color: "var(--text-subtle)" }}
                    >
                      {item.dateLabel}
                    </span>
                    <svg
                      viewBox="0 0 24 24"
                      width="14"
                      height="14"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      className="shrink-0 opacity-0 transition-opacity duration-200 group-hover:opacity-60"
                      style={{ color: "var(--text-subtle)" }}
                      aria-hidden
                    >
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </DashboardCard>

        <DashboardCard title={t("quick.title")}>
          <ul className="flex flex-col gap-2">
            {visibleQuickActions.map((action) => (
              <li key={action.labelKey}>
                <Link
                  href={action.href}
                  className="ui-dashboard-action-link group flex min-w-0 items-center gap-3 rounded-lg px-3 py-3"
                >
                  <span className="ui-dashboard-action-link__icon flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors duration-200" style={{ backgroundColor: "var(--bg-surface-strong)", color: "var(--accent-from)" }}>
                    {action.icon}
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="ui-dashboard-action-link__title text-sm font-semibold transition-colors duration-200" style={{ color: "var(--text-primary)" }}>
                      {t(action.labelKey)}
                    </span>
                    <span className="ui-dashboard-action-link__desc text-xs transition-colors duration-200" style={{ color: "var(--text-muted)" }}>
                      {t(action.descKey)}
                    </span>
                  </div>
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    className="ui-dashboard-action-link__chevron shrink-0 opacity-60 transition-all duration-200"
                    style={{ color: "var(--text-subtle)" }}
                    aria-hidden
                  >
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                </Link>
              </li>
            ))}
          </ul>
        </DashboardCard>
      </section>
    </>
  );
}
