"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import CalendarEventDetails from "@/components/dashboard/CalendarEventDetails";
import MeetingsCalendar, { type RangeChange } from "@/components/dashboard/MeetingsCalendar";
import PrimaryButton from "@/components/PrimaryButton";
import UiAlert from "@/components/ui/UiAlert";
import { useCalendarEvents, type ProviderState } from "@/hooks/useCalendarEvents";
import { useCalendarProvidersConfigured } from "@/hooks/useCalendarProvidersConfigured";
import { calendarUiLabels, fillLabel } from "@/i18n/calendar-ui-labels";
import { initialViewForWidth, type CalendarEventModel } from "@/lib/calendar-events";
import {
  DossierApiError,
  fetchCalendarDiagnostico,
  fetchGoogleIntegrationStartAsJson,
  fetchMicrosoftIntegrationStartAsJson,
  getStoredAccessToken,
  type CalendarIncompleteReason,
  type CalendarProvider,
} from "@/lib/dossier-api";
import { usePreferences, useTranslation } from "@/providers/PreferencesProvider";

type ProviderFilter = "all" | CalendarProvider;

const PROVIDERS: CalendarProvider[] = ["google", "microsoft"];
const PROVIDER_COLOR: Record<CalendarProvider, string> = {
  google: "var(--dossier-google, #0f9d58)",
  microsoft: "var(--dossier-outlook, #2a7de1)",
};

const INCOMPLETE_KEY = {
  limite_paginas: "incompleteLimit",
  tiempo_agotado: "incompleteTimeout",
  error_proveedor: "incompleteError",
} as const satisfies Record<CalendarIncompleteReason, string>;

/** Los mensajes internos de red no se enseñan al usuario. */
function usableDetail(message: string): string {
  return !message || message === "NETWORK" || message.startsWith("__dossier") ? "" : message;
}

export default function MeetingsCalendarSection() {
  const { t, locale } = useTranslation();
  const { effectiveTimezone, ready } = usePreferences();
  const ui = useMemo(() => calendarUiLabels(locale), [locale]);

  const [filter, setFilter] = useState<ProviderFilter>("all");
  const [range, setRange] = useState<RangeChange | null>(null);
  const [selected, setSelected] = useState<{ event: CalendarEventModel; trigger: HTMLElement } | null>(null);
  const [connecting, setConnecting] = useState<CalendarProvider | null>(null);
  const [connectErr, setConnectErr] = useState<string | null>(null);
  const [diagnose, setDiagnose] = useState<{ loading: boolean; text: string | null }>({ loading: false, text: null });
  const regionRef = useRef<HTMLDivElement | null>(null);

  const calendar = useCalendarEvents({
    window: ready ? (range?.window ?? null) : null,
    timezone: effectiveTimezone,
    fallbackTitle: "—",
  });
  const states: Record<CalendarProvider, ProviderState> = { google: calendar.google, microsoft: calendar.microsoft };
  const name = (p: CalendarProvider) => (p === "google" ? ui.providerGoogle : ui.providerOutlook);
  const configurados = useCalendarProvidersConfigured();
  // Sin OAuth en el servidor no se ofrece conectar ni filtrar; si ya hay conexión, se muestra igual.
  const offered = PROVIDERS.filter((p) => configurados[p] !== false || states[p].status !== "disconnected");

  const visibleEvents = useMemo(
    () => (filter === "all" ? calendar.events : calendar.events.filter((e) => e.provider === filter)),
    [calendar.events, filter],
  );
  const eventsByKey = useMemo(() => new Map(calendar.events.map((e) => [e.key, e])), [calendar.events]);

  // Vista inicial según el ancho real del calendario; se mide una vez, antes de montarlo.
  const [width, setWidth] = useState<number | null>(null);
  const attachRegion = useCallback((el: HTMLDivElement | null) => {
    regionRef.current = el;
    if (el) setWidth((w) => w ?? el.clientWidth);
  }, []);
  const initialView = initialViewForWidth(width ?? 0);

  const handleSelect = useCallback(
    (key: string, trigger: HTMLElement) => {
      const event = eventsByKey.get(key);
      if (event) setSelected({ event, trigger });
    },
    [eventsByKey],
  );

  async function connect(provider: CalendarProvider) {
    setConnecting(provider);
    setConnectErr(null);
    try {
      const { authorize_url } =
        provider === "google" ? await fetchGoogleIntegrationStartAsJson() : await fetchMicrosoftIntegrationStartAsJson();
      window.location.assign(authorize_url);
    } catch (e) {
      setConnecting(null);
      setConnectErr(e instanceof DossierApiError ? e.message : t("automation.calendar_load_error"));
    }
  }

  async function runDiagnose(provider: CalendarProvider) {
    setDiagnose({ loading: true, text: null });
    try {
      setDiagnose({ loading: false, text: JSON.stringify(await fetchCalendarDiagnostico(provider), null, 2) });
    } catch (e) {
      setDiagnose({
        loading: false,
        text: e instanceof DossierApiError ? e.message : t("overview.calendar_diagnose_error"),
      });
    }
  }

  if (!ready) {
    return <div style={{ minHeight: 540 }} aria-busy="true" />;
  }
  if (!getStoredAccessToken()) {
    return (
      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
        {t("overview.activity_login_hint")}
      </p>
    );
  }

  const readyProviders = PROVIDERS.filter((p) => states[p].status === "ready");
  const incomplete = PROVIDERS.filter((p) => states[p].incomplete);
  const allDisconnected = PROVIDERS.every((p) => states[p].status === "disconnected");
  const emptyPeriod =
    !calendar.loading && readyProviders.length > 0 && visibleEvents.length === 0 && incomplete.length === 0;

  const filters: { id: ProviderFilter; label: string }[] = [
    { id: "all", label: ui.filterAll },
    ...offered.map((p) => ({ id: p, label: name(p) })),
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {offered.map((p) =>
          states[p].status === "disconnected" ? (
            <span key={p} className="inline-flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: PROVIDER_COLOR[p] }} aria-hidden />
              {fillLabel(ui.providerDisconnected, { provider: name(p) })}
              <PrimaryButton
                type="button"
                className="!px-3 !py-1.5 !text-xs"
                loading={connecting === p}
                onClick={() => void connect(p)}
              >
                {t(p === "google" ? "overview.google_connect" : "overview.microsoft_connect")}
              </PrimaryButton>
            </span>
          ) : (
            <span
              key={p}
              className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs"
              style={{
                borderColor: states[p].status === "ready" ? PROVIDER_COLOR[p] : "var(--border-default)",
                color: states[p].status === "ready" ? "var(--text-primary)" : "var(--text-muted)",
              }}
            >
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: PROVIDER_COLOR[p] }} aria-hidden />
              {name(p)} {states[p].status === "ready" ? "✓" : "—"}
            </span>
          ),
        )}
        <button
          type="button"
          disabled={calendar.loading}
          onClick={calendar.refresh}
          className="ml-auto rounded-lg border px-3 py-1.5 text-xs font-medium transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-50"
          style={{ borderColor: "var(--border-default)", color: "var(--text-primary)", backgroundColor: "var(--bg-surface)" }}
        >
          {calendar.loading ? ui.loading : ui.refresh}
        </button>
      </div>

      <div role="group" aria-label={ui.filterGroupLabel} className="flex flex-wrap gap-1.5">
        {filters.map((f) => {
          const active = filter === f.id;
          return (
            <button
              key={f.id}
              type="button"
              aria-pressed={active}
              onClick={() => setFilter(f.id)}
              className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition"
              style={{
                borderColor: active ? "var(--accent-from)" : "var(--border-default)",
                backgroundColor: active ? "rgba(0, 180, 216, 0.1)" : "var(--bg-surface)",
                color: active ? "var(--accent-from)" : "var(--text-muted)",
              }}
            >
              {f.id !== "all" ? (
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: PROVIDER_COLOR[f.id] }} aria-hidden />
              ) : null}
              {f.label}
            </button>
          );
        })}
      </div>

      {connectErr ? <UiAlert variant="error" role="alert">{connectErr}</UiAlert> : null}
      {allDisconnected ? (
        <div
          className="rounded-xl border border-dashed px-4 py-4 text-center text-sm"
          style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}
        >
          {t("automation.calendars_empty")}
        </div>
      ) : null}

      {PROVIDERS.filter((p) => states[p].status === "error").map((p) => {
        const detail = usableDetail(states[p].error?.message ?? "");
        return (
          <UiAlert key={p} variant="warning" role="alert" className="flex flex-wrap items-center gap-3">
            <span>
              {fillLabel(ui.providerError, { provider: name(p) })}
              {detail ? ` ${detail}` : ""}
            </span>
            <button type="button" onClick={calendar.refresh} className="text-xs font-semibold underline underline-offset-2">
              {ui.retry}
            </button>
          </UiAlert>
        );
      })}

      {incomplete.map((p) => (
        <UiAlert key={p} variant="warning" role="status">
          {fillLabel(ui[INCOMPLETE_KEY[states[p].incomplete as CalendarIncompleteReason]], { provider: name(p) })}
        </UiAlert>
      ))}

      {calendar.discarded > 0 ? (
        <UiAlert variant="info" role="status">
          {fillLabel(ui.discarded, { n: calendar.discarded })}
        </UiAlert>
      ) : null}

      {emptyPeriod ? (
        <div
          className="rounded-xl border px-4 py-3 text-center text-sm"
          style={{ borderColor: "var(--border-default)", color: "var(--text-muted)" }}
          role="status"
        >
          {ui.emptyPeriod}
          <div className="mt-2">
            <button
              type="button"
              disabled={diagnose.loading}
              onClick={() => void runDiagnose(readyProviders[0])}
              className="text-xs font-medium underline-offset-2 hover:underline disabled:opacity-50"
              style={{ color: "var(--accent-from)" }}
            >
              {diagnose.loading ? t("overview.calendar_diagnose_loading") : t("overview.calendar_diagnose")}
            </button>
          </div>
          {diagnose.text ? (
            <pre
              className="mx-auto mt-3 max-h-40 max-w-lg overflow-auto rounded-lg border p-2 text-left text-[11px]"
              style={{ borderColor: "var(--border-default)", backgroundColor: "var(--bg-surface)", color: "var(--text-muted)" }}
            >
              {diagnose.text}
            </pre>
          ) : null}
        </div>
      ) : null}

      <div ref={attachRegion} data-calendar-container tabIndex={-1} className="outline-none">
        {width !== null ? (
          <MeetingsCalendar
            events={visibleEvents}
            locale={locale}
            timezone={effectiveTimezone}
            labels={ui}
            initialView={initialView}
            onRangeChange={setRange}
            onSelectEvent={handleSelect}
          />
        ) : null}
      </div>

      {selected ? (
        <CalendarEventDetails
          event={selected.event}
          onClose={() => setSelected(null)}
          returnFocusTo={selected.trigger}
          fallbackFocus={() => regionRef.current}
        />
      ) : null}
    </div>
  );
}
