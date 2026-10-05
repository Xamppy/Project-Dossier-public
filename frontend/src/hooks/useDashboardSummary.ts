"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchDashboardSummary, getStoredAccessToken, type DashboardSummary } from "@/lib/dossier-api";
import { AUTH_ME_CHANGED_EVENT } from "@/hooks/useAuthMe";
import type { KpiStatus } from "@/lib/dashboard-kpis";

type Options = {
  /** Sin sesión no se consulta. */
  enabled: boolean;
  /** Cambia cuando termina una generación del usuario: fuerza una nueva consulta. */
  refreshKey: string;
};

/**
 * Indicadores de Resumen. Se refrescan al entrar, al volver a la pestaña, al cambiar de
 * sesión u organización y cuando `refreshKey` cambia (una generación terminó). Sin sondeo.
 *
 * - Una sola petición en vuelo: los refrescos simultáneos comparten la misma promesa.
 * - Si algo cambió mientras había una petición en vuelo, se repite al terminar: esa
 *   respuesta pudo haberse leído antes del cambio.
 * - Una respuesta de otra sesión u organización (otro JWT) se descarta.
 */
export function useDashboardSummary({ enabled, refreshKey }: Options) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [status, setStatus] = useState<KpiStatus>(enabled ? "loading" : "idle");
  const inflight = useRef<Promise<void> | null>(null);
  const dirty = useRef(false);
  /** Sube con cada cambio de sesión/organización: lo anterior queda obsoleto. */
  const epoch = useRef(0);
  const alive = useRef(true);
  const enabledRef = useRef(enabled);
  const refreshRef = useRef<() => Promise<void>>(() => Promise.resolve());
  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  const refresh = useCallback((): Promise<void> => {
    if (!enabledRef.current) return Promise.resolve();
    if (inflight.current) {
      dirty.current = true;
      return inflight.current;
    }
    const tokenAtStart = getStoredAccessToken();
    const epochAtStart = epoch.current;
    const obsoleta = () =>
      !alive.current ||
      !enabledRef.current ||
      epoch.current !== epochAtStart ||
      getStoredAccessToken() !== tokenAtStart;
    const run: Promise<void> = (async () => {
      try {
        const data = await fetchDashboardSummary();
        if (obsoleta()) return;
        setSummary(data);
        setStatus("ready");
      } catch {
        if (obsoleta()) return;
        setSummary(null);
        setStatus("error");
      }
    })().finally(() => {
      if (inflight.current !== run) return; // otra consulta tomó su lugar tras un cambio de sesión
      inflight.current = null;
      if (dirty.current && alive.current) {
        dirty.current = false;
        void refreshRef.current();
      }
    });
    inflight.current = run;
    return run;
  }, []);
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  // Alta y baja de sesión.
  useEffect(() => {
    alive.current = true;
    if (!enabled) {
      queueMicrotask(() => {
        if (!alive.current) return;
        setSummary(null);
        setStatus("idle");
      });
      return;
    }
    queueMicrotask(() => {
      if (alive.current) setStatus((s) => (s === "ready" ? s : "loading"));
    });
    void refresh();
    return () => {
      alive.current = false;
    };
  }, [enabled, refresh]);

  // Una generación terminó (o cambió otra cosa relevante): consulta de nuevo.
  const primeraClave = useRef(refreshKey);
  useEffect(() => {
    if (primeraClave.current === refreshKey) return;
    primeraClave.current = refreshKey;
    void refresh();
  }, [refreshKey, refresh]);

  // Volver a la pestaña o cambiar de sesión/organización.
  useEffect(() => {
    if (!enabled) return;
    const alVolver = () => {
      if (document.visibilityState !== "hidden") void refresh();
    };
    const alCambiarSesion = () => {
      epoch.current += 1; // lo que esté en vuelo es de la sesión anterior y se descarta
      inflight.current = null;
      dirty.current = false;
      setSummary(null);
      setStatus("loading");
      void refresh();
    };
    document.addEventListener("visibilitychange", alVolver);
    window.addEventListener(AUTH_ME_CHANGED_EVENT, alCambiarSesion);
    return () => {
      document.removeEventListener("visibilitychange", alVolver);
      window.removeEventListener(AUTH_ME_CHANGED_EVENT, alCambiarSesion);
    };
  }, [enabled, refresh]);

  // Sin sesión no se muestra nada del usuario anterior, ni siquiera un instante.
  return { summary: enabled ? summary : null, status: enabled ? status : ("idle" as KpiStatus), refresh };
}
