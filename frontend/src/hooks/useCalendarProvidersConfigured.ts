"use client";

import { useEffect, useState } from "react";

import { fetchCalendarProviderConfigured, type CalendarProvider } from "@/lib/dossier-api";

/** `null` = todavía no se sabe o la consulta falló: en ese caso no se oculta nada. */
export type CalendarProvidersConfigured = Record<CalendarProvider, boolean | null>;

const PROVEEDORES: CalendarProvider[] = ["google", "microsoft"];

/** Qué calendarios tienen OAuth configurado en el servidor, para ocultar los que no. */
export function useCalendarProvidersConfigured(): CalendarProvidersConfigured {
  const [estado, setEstado] = useState<CalendarProvidersConfigured>({ google: null, microsoft: null });

  useEffect(() => {
    let vigente = true;
    for (const proveedor of PROVEEDORES) {
      fetchCalendarProviderConfigured(proveedor)
        .then((configurado) => {
          if (vigente) setEstado((previo) => ({ ...previo, [proveedor]: configurado }));
        })
        .catch(() => {
          // Sin respuesta no se oculta: un botón que falla es mejor que uno que desaparece.
        });
    }
    return () => {
      vigente = false;
    };
  }, []);

  return estado;
}
