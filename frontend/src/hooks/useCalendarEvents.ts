"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import {
  calendarCacheKey,
  readCalendarCache,
  writeCalendarCache,
} from "@/lib/calendar-events-cache";
import { adaptMeetings, type CalendarEventModel, type CalendarWindow } from "@/lib/calendar-events";
import {
  DossierApiError,
  fetchCalendarEventosPorIntervalo,
  getStoredAccessToken,
  type CalendarEventosRangoResponse,
  type CalendarIncompleteReason,
  type CalendarProvider,
} from "@/lib/dossier-api";

export type ProviderStatus = "idle" | "loading" | "ready" | "disconnected" | "error";

export type ProviderState = {
  status: ProviderStatus;
  error: { status: number; message: string } | null;
  /** Motivo por el que el servidor devolvió solo una parte del intervalo. */
  incomplete: CalendarIncompleteReason | null;
};

type Slot = ProviderState & { response: CalendarEventosRangoResponse | null };

type State = Record<CalendarProvider, Slot>;

type Action =
  | { type: "reset" }
  | { type: "loading"; provider: CalendarProvider }
  | { type: "result"; provider: CalendarProvider; response: CalendarEventosRangoResponse }
  | { type: "failure"; provider: CalendarProvider; status: number; message: string };

const PROVIDERS: CalendarProvider[] = ["google", "microsoft"];

const IDLE: Slot = { status: "idle", error: null, incomplete: null, response: null };
const INITIAL: State = { google: IDLE, microsoft: IDLE };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "reset":
      return INITIAL;
    case "loading":
      // Se conservan los eventos anteriores mientras llegan los nuevos: no hay parpadeo.
      return { ...state, [action.provider]: { ...state[action.provider], status: "loading", error: null } };
    case "result":
      return {
        ...state,
        [action.provider]: {
          status: "ready",
          error: null,
          incomplete: action.response.completo ? null : (action.response.motivoIncompleto ?? "error_proveedor"),
          response: action.response,
        },
      };
    case "failure":
      return {
        ...state,
        [action.provider]: {
          // 404/403: no hay integración activa. Cualquier otro fallo es un error de la consulta.
          status: action.status === 404 || action.status === 403 ? "disconnected" : "error",
          error: { status: action.status, message: action.message },
          incomplete: null,
          response: null,
        },
      };
  }
}

type Options = {
  /** Intervalo visible; `null` mientras el calendario aún no sabe qué muestra. */
  window: CalendarWindow | null;
  timezone: string;
  fallbackTitle: string;
};

export type UseCalendarEvents = {
  google: ProviderState;
  microsoft: ProviderState;
  events: CalendarEventModel[];
  /** Registros que el proveedor devolvió sin inicio válido. */
  discarded: number;
  loading: boolean;
  refresh: () => void;
};

function publicState({ status, error, incomplete }: Slot): ProviderState {
  return { status, error, incomplete };
}

export function useCalendarEvents({ window: range, timezone, fallbackTitle }: Options): UseCalendarEvents {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const [nonce, setNonce] = useState(0);
  const forceRef = useRef(false);

  const desde = range?.desde ?? null;
  const hasta = range?.hasta ?? null;

  useEffect(() => {
    const session = getStoredAccessToken();
    if (!desde || !hasta || !session) {
      dispatch({ type: "reset" });
      return;
    }
    const w = { desde, hasta };
    const force = forceRef.current;
    forceRef.current = false;
    const controllers = PROVIDERS.map(() => new AbortController());

    PROVIDERS.forEach((provider, i) => {
      const { signal } = controllers[i];
      const key = calendarCacheKey(provider, w, timezone);
      const cached = force ? null : readCalendarCache(session, key);
      if (cached) {
        dispatch({ type: "result", provider, response: cached });
        return;
      }
      dispatch({ type: "loading", provider });
      fetchCalendarEventosPorIntervalo(provider, w, { signal }).then(
        (response) => {
          if (signal.aborted) return; // respuesta tardía de un intervalo que ya no es el visible
          writeCalendarCache(session, key, response);
          dispatch({ type: "result", provider, response });
        },
        (e: unknown) => {
          if (signal.aborted) return;
          dispatch({
            type: "failure",
            provider,
            status: e instanceof DossierApiError ? e.status : -1,
            message: e instanceof DossierApiError ? e.message : "",
          });
        },
      );
    });

    return () => controllers.forEach((c) => c.abort());
  }, [desde, hasta, timezone, nonce]);

  const refresh = useCallback(() => {
    forceRef.current = true;
    setNonce((n) => n + 1);
  }, []);

  const adapted = useMemo(() => {
    const events: CalendarEventModel[] = [];
    let discarded = 0;
    for (const provider of PROVIDERS) {
      const response = state[provider].response;
      if (!response) continue;
      const a = adaptMeetings(provider, response.reuniones, timezone, fallbackTitle);
      events.push(...a.events);
      discarded += a.discarded;
    }
    events.sort((a, b) => a.start.localeCompare(b.start));
    return { events, discarded };
  }, [state, timezone, fallbackTitle]);

  return {
    google: publicState(state.google),
    microsoft: publicState(state.microsoft),
    events: adapted.events,
    discarded: adapted.discarded,
    loading: PROVIDERS.some((p) => state[p].status === "loading"),
    refresh,
  };
}
