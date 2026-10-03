"use client";

import { useCallback, useEffect, useState } from "react";
import AutomationCalendarPreview from "@/components/dashboard/AutomationCalendarPreview";
import CalendarFormatGuideAnyAction from "@/components/dashboard/CalendarFormatGuideAnyAction";
import DashboardCard from "@/components/dashboard/DashboardCard";
import UiAlert from "@/components/ui/UiAlert";
import TopBar from "@/components/dashboard/TopBar";
import {
  DossierApiError,
  fetchAuthMe,
  fetchCalendarAutomationStatus,
  getStoredAccessToken,
  patchCalendarAutomationSettings,
} from "@/lib/dossier-api";
import { normalizePlanTier } from "@/lib/plans";
import { calendarUiLabels } from "@/i18n/calendar-ui-labels";
import { useTranslation } from "@/providers/PreferencesProvider";
import MutatorGuard from "@/components/auth/MutatorGuard";
import type { TranslationKey } from "@/i18n/types";

const BEFORE_OPTIONS: { value: string; key: TranslationKey }[] = [
  { value: "15", key: "time.15_min" },
  { value: "20", key: "time.20_min" },
  { value: "30", key: "time.30_min" },
  { value: "60", key: "time.1_hour" },
  { value: "1440", key: "time.1_day" },
];

const selectClass =
  "w-full max-w-xs rounded-lg border px-3.5 py-2.5 text-sm outline-none focus:ring-2";

const selectStyle = {
  backgroundColor: "var(--bg-input)",
  borderColor: "var(--border-default)",
  color: "var(--text-primary)",
};

export default function AutomationPage() {
  const { t, locale } = useTranslation();
  const ui = calendarUiLabels(locale);
  const [beforeMinutes, setBeforeMinutes] = useState("20");
  const [externalOnly, setExternalOnly] = useState(false);
  const [hasCalendars, setHasCalendars] = useState(false);
  const [scheduledEvents, setScheduledEvents] = useState(0);
  const [nextDue, setNextDue] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [planAllowsAutomation, setPlanAllowsAutomation] = useState(true);
  const [load, setLoad] = useState<"idle" | "loading" | "ready">("idle");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    if (!getStoredAccessToken()) {
      setLoad("idle");
      return;
    }
    setLoad("loading");
    setErr(null);
    try {
      const [st, me] = await Promise.all([
        fetchCalendarAutomationStatus(),
        fetchAuthMe().catch(() => null),
      ]);
      const plan = normalizePlanTier(me?.organization_plan);
      setPlanAllowsAutomation(plan !== "free");
      setEnabled(st.enabled);
      setHasCalendars(Boolean(st.has_calendars ?? (st.integrations?.length ?? 0) > 0));
      const stored = st.advance_minutes_stored ?? st.advance_minutes;
      setBeforeMinutes(String(stored));
      setExternalOnly(Boolean(st.skip_internal_meetings));
      setScheduledEvents(st.scheduled_events);
      setNextDue(st.next_due);
      setLoad("ready");
    } catch (e) {
      setErr(e instanceof DossierApiError ? e.message : String(e));
      setLoad("ready");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void loadStatus());
  }, [loadStatus]);

  async function handleAdvanceChange(value: string) {
    if (!hasCalendars) return;
    setBeforeMinutes(value);
    setSaveMsg(null);
    setSaving(true);
    setErr(null);
    try {
      const res = await patchCalendarAutomationSettings({ advance_minutes: Number(value) });
      setSaveMsg(res.message);
      void loadStatus();
    } catch (e) {
      setErr(e instanceof DossierApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function handleExternalOnlyChange(checked: boolean) {
    if (!hasCalendars) return;
    setExternalOnly(checked);
    setSaveMsg(null);
    setSaving(true);
    setErr(null);
    try {
      const res = await patchCalendarAutomationSettings({ skip_internal_meetings: checked });
      setSaveMsg(res.message);
      void loadStatus();
    } catch (e) {
      setExternalOnly(!checked);
      setErr(e instanceof DossierApiError ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const selectDisabled =
    saving || load === "loading" || !hasCalendars || !planAllowsAutomation;

  return (
    <MutatorGuard>
      <>
      <TopBar title={t("automation.title")} subtitle={t("automation.subtitle")} />

      {!planAllowsAutomation && load === "ready" ? (
        <UiAlert variant="warning" className="mb-4" role="status">
          {t("billing.automation_requires_pro")}
        </UiAlert>
      ) : null}

      {err ? (
        <UiAlert variant="warning" className="mb-4" role="alert">
          {err}
        </UiAlert>
      ) : null}

      <DashboardCard
        title={t("automation.connected_calendars")}
        action={<CalendarFormatGuideAnyAction />}
      >
        <AutomationCalendarPreview />
      </DashboardCard>

      <details
        className="group mt-6 rounded-xl border"
        style={{ borderColor: "var(--border-default)" }}
      >
        <summary
          className="flex cursor-pointer list-none items-center justify-between gap-3 px-6 py-4 text-base font-semibold"
          style={{ color: "var(--text-primary)" }}
        >
          <span>{ui.rulesToggleSummary}</span>
          <span className="flex items-center gap-3 text-xs font-normal" style={{ color: "var(--text-muted)" }}>
            {load === "ready" ? (enabled ? t("automation.status_on") : t("automation.status_off")) : null}
            <span aria-hidden className="transition-transform group-open:rotate-180">▾</span>
          </span>
        </summary>
        <div className="px-6 pb-6">
          <div className="flex flex-col gap-4">
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              {t("automation.rules_desc")}
            </p>

            <p
              className="rounded-lg border px-3 py-2 text-xs leading-relaxed"
              style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}
            >
              {t("automation.work_meetings_hint")}
            </p>

            {!hasCalendars && load === "ready" ? (
              <p
                className="rounded-lg border border-dashed px-3 py-2 text-xs"
                style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}
              >
                {t("automation.connect_calendar_hint")}
              </p>
            ) : null}

            <label className="flex flex-col gap-1.5 text-sm">
              <span style={{ color: "var(--text-secondary)" }}>
                {t("automation.before_meeting")}
              </span>
              <select
                value={beforeMinutes}
                disabled={selectDisabled}
                onChange={(e) => void handleAdvanceChange(e.target.value)}
                className={selectClass}
                style={selectStyle}
              >
                {BEFORE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(opt.key)}
                  </option>
                ))}
              </select>
            </label>

            <label
              className={`flex items-start gap-3 text-sm ${!hasCalendars ? "opacity-50" : ""}`}
            >
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border"
                style={{ borderColor: "var(--border-default)" }}
                checked={externalOnly}
                disabled={selectDisabled}
                onChange={(e) => void handleExternalOnlyChange(e.target.checked)}
              />
              <span className="flex flex-col gap-1">
                <span style={{ color: "var(--text-secondary)" }}>{t("automation.skip_internal")}</span>
                <span className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>
                  {t("automation.skip_internal_hint")}
                </span>
              </span>
            </label>

            {saving ? (
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {t("automation.saving")}
              </p>
            ) : null}
            {saveMsg ? (
              <p className="text-xs" style={{ color: "#34d399" }}>
                {saveMsg}
              </p>
            ) : null}

            {load === "ready" && hasCalendars ? (
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                {t("automation.advance_effective", { minutes: beforeMinutes })}
              </p>
            ) : null}

            {load === "ready" ? (
              <div
                className="rounded-lg border px-3 py-3 text-xs"
                style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}
              >
                <p>
                  {enabled ? t("automation.status_on") : t("automation.status_off")}
                </p>
                <p className="mt-1">
                  {t("automation.queue_summary", {
                    count: String(scheduledEvents),
                    next: nextDue
                      ? new Date(nextDue).toLocaleString(undefined, {
                          dateStyle: "short",
                          timeStyle: "short",
                        })
                      : "—",
                  })}
                </p>
              </div>
            ) : null}
          </div>
        </div>
      </details>
    </>
    </MutatorGuard>
  );
}
