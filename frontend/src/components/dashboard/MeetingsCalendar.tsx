"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import FullCalendar, { type CalendarRef } from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/react/daygrid";
import timeGridPlugin from "@fullcalendar/react/timegrid";
import classicTheme from "@fullcalendar/react/themes/classic";
import deLocale from "@fullcalendar/react/locales/de";
import enGbLocale from "@fullcalendar/react/locales/en-gb";
import esLocale from "@fullcalendar/react/locales/es";
import frLocale from "@fullcalendar/react/locales/fr";
import itLocale from "@fullcalendar/react/locales/it";
import ptLocale from "@fullcalendar/react/locales/pt";
import "@fullcalendar/react/skeleton.css";
import "@fullcalendar/react/themes/classic/theme.css";
import "./meetings-calendar.css";
import { fillLabel, type CalendarUiLabels } from "@/i18n/calendar-ui-labels";
import type { Locale } from "@/i18n/types";
import {
  toFullCalendarEvent,
  windowFromCivilDates,
  type CalendarEventModel,
  type CalendarViewType,
  type CalendarWindow,
} from "@/lib/calendar-events";
import type { CalendarProvider } from "@/lib/dossier-api";

// `en` es el idioma por defecto de FullCalendar; el resto se registra explícitamente.
const FC_LOCALES = {
  en: undefined,
  "en-gb": enGbLocale,
  es: esLocale,
  pt: ptLocale,
  it: itLocale,
  fr: frLocale,
  de: deLocale,
} as const;

export type RangeChange = { window: CalendarWindow; view: CalendarViewType; title: string };

type Props = {
  events: CalendarEventModel[];
  locale: Locale;
  timezone: string;
  labels: CalendarUiLabels;
  initialView: CalendarViewType;
  onRangeChange: (change: RangeChange) => void;
  /** Recibe la clave del evento y el elemento pulsado (para devolver el foco al cerrar el detalle). */
  onSelectEvent: (key: string, trigger: HTMLElement) => void;
};

const VIEWS: { type: CalendarViewType; label: keyof Pick<CalendarUiLabels, "viewDay" | "viewWeek" | "viewMonth"> }[] = [
  { type: "timeGridDay", label: "viewDay" },
  { type: "timeGridWeek", label: "viewWeek" },
  { type: "dayGridMonth", label: "viewMonth" },
];

function providerLabel(provider: CalendarProvider, labels: CalendarUiLabels) {
  return provider === "google" ? labels.providerGoogle : labels.providerOutlook;
}

const toolbarButton =
  "rounded-lg border px-3 py-1.5 text-xs font-medium transition hover:opacity-95 focus-visible:outline-2 focus-visible:outline-offset-2";

export default function MeetingsCalendar({
  events,
  locale,
  timezone,
  labels,
  initialView,
  onRangeChange,
  onSelectEvent,
}: Props) {
  const ref = useRef<CalendarRef>(null);
  const [view, setView] = useState<CalendarViewType>(initialView);
  const [title, setTitle] = useState("");

  const latest = useRef({ onRangeChange, onSelectEvent, timezone });
  useEffect(() => {
    latest.current = { onRangeChange, onSelectEvent, timezone };
  });

  const fcEvents = useMemo(() => events.map(toFullCalendarEvent), [events]);
  const api = () => ref.current?.getApi();

  // Último intervalo visible en fechas civiles: si cambia la zona horaria, las fechas son las
  // mismas pero los instantes de consulta no, así que se vuelve a informar.
  const visible = useRef<{ start: string; end: string; view: CalendarViewType; title: string } | null>(null);

  const emit = useCallback((tz: string) => {
    const v = visible.current;
    if (!v) return;
    latest.current.onRangeChange({
      window: windowFromCivilDates(v.start, v.end, tz),
      view: v.view,
      title: v.title,
    });
  }, []);

  const handleDatesSet = useCallback(
    (info: { startStr: string; endStr: string; view: { type: string; title: string } }) => {
      const type = info.view.type as CalendarViewType;
      setView(type);
      setTitle(info.view.title);
      visible.current = { start: info.startStr, end: info.endStr, view: type, title: info.view.title };
      emit(latest.current.timezone);
    },
    [emit],
  );

  useEffect(() => {
    emit(timezone);
  }, [timezone, emit]);

  return (
    <div className="dossier-cal flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label={labels.navLabel} className="flex items-center gap-1.5">
          <button type="button" className={toolbarButton} data-variant="nav" onClick={() => api()?.prev()}>
            <span aria-hidden>‹</span>
            <span className="sr-only">{labels.previous}</span>
          </button>
          <button type="button" className={toolbarButton} data-variant="nav" onClick={() => api()?.today()}>
            {labels.today}
          </button>
          <button type="button" className={toolbarButton} data-variant="nav" onClick={() => api()?.next()}>
            <span aria-hidden>›</span>
            <span className="sr-only">{labels.next}</span>
          </button>
        </div>

        <h3
          aria-live="polite"
          className="order-first w-full text-base font-semibold capitalize sm:order-none sm:w-auto"
          style={{ color: "var(--text-primary)" }}
        >
          {title}
        </h3>

        <div role="group" aria-label={labels.viewSelectorLabel} className="flex items-center gap-1.5">
          {VIEWS.map((v) => (
            <button
              key={v.type}
              type="button"
              className={toolbarButton}
              data-variant="view"
              aria-pressed={view === v.type}
              onClick={() => api()?.changeView(v.type)}
            >
              {labels[v.label]}
            </button>
          ))}
        </div>
      </div>

      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
        {fillLabel(labels.timezoneLabel, { tz: timezone })}
      </p>

      <div className="dossier-cal__surface" role="region" aria-label={labels.calendarRegion}>
        <FullCalendar
          ref={ref}
          plugins={[timeGridPlugin, dayGridPlugin, classicTheme]}
          initialView={initialView}
          locale={FC_LOCALES[locale]}
          timeZone={timezone}
          headerToolbar={false}
          height="100%"
          expandRows
          nowIndicator
          scrollTime="07:00:00"
          dayMaxEvents={3}
          slotEventOverlap
          events={fcEvents}
          datesSet={handleDatesSet}
          eventClick={(info) => latest.current.onSelectEvent(info.event.id, info.el)}
          eventContent={(arg) => {
            const provider = arg.event.extendedProps.provider as CalendarProvider;
            const name = providerLabel(provider, labels);
            return (
              <div className="dossier-ev__inner">
                <span className="dossier-ev__tag" aria-hidden title={name}>
                  {name.charAt(0)}
                </span>
                <span className="dossier-ev__text">
                  {arg.timeText ? <span className="dossier-ev__time">{arg.timeText} </span> : null}
                  <span className="dossier-ev__title">{arg.event.title}</span>
                </span>
                <span className="sr-only">{name}</span>
              </div>
            );
          }}
        />
      </div>
    </div>
  );
}
