"use client";

import { useEffect, useState } from "react";
import CalendarMeetingFormatGuide from "@/components/dashboard/CalendarMeetingFormatGuide";
import {
  fetchGoogleCalendarEventos,
  fetchOutlookCalendarEventos,
  getStoredAccessToken,
} from "@/lib/dossier-api";

/** Muestra la guía si al menos un calendario (Outlook o Google) está conectado. */
export default function CalendarFormatGuideAnyAction() {
  const [connected, setConnected] = useState(false);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!getStoredAccessToken()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- corta segun el token de sesion (sistema externo: localStorage), sin trabajo async.
      setConnected(false);
      setChecked(true);
      return;
    }

    void Promise.allSettled([
      fetchOutlookCalendarEventos({ top: 1 }),
      fetchGoogleCalendarEventos({ top: 1 }),
    ]).then((results) => {
      setConnected(results.some((r) => r.status === "fulfilled"));
      setChecked(true);
    });
  }, []);

  if (!checked || !connected) return null;
  return <CalendarMeetingFormatGuide />;
}
