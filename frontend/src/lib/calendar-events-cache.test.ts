import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  calendarCacheKey,
  clearCalendarEventsCache,
  readCalendarCache,
  writeCalendarCache,
} from "./calendar-events-cache";
import { clearAuthSession, persistAuthToken } from "./dossier-api";

const W = { desde: "2026-10-05T00:00:00-03:00", hasta: "2026-10-12T00:00:00-03:00" };
const resp = (completo = true) => ({
  total: 0,
  reuniones: [],
  mensaje: null,
  rango: null,
  completo,
  motivoIncompleto: completo ? null : ("limite_paginas" as const),
});

beforeEach(() => clearCalendarEventsCache());
afterEach(() => vi.useRealTimers());

describe("caché de eventos de calendario", () => {
  it("la clave distingue proveedor, intervalo y zona horaria", () => {
    const base = calendarCacheKey("google", W, "UTC");
    expect(calendarCacheKey("microsoft", W, "UTC")).not.toBe(base);
    expect(calendarCacheKey("google", { ...W, hasta: "2026-10-13T00:00:00-03:00" }, "UTC")).not.toBe(base);
    expect(calendarCacheKey("google", W, "Europe/London")).not.toBe(base);
  });

  it("guarda y devuelve para la misma sesión", () => {
    const k = calendarCacheKey("google", W, "UTC");
    writeCalendarCache("sesion-ana", k, resp());
    expect(readCalendarCache("sesion-ana", k)).not.toBeNull();
  });

  it("otra sesión no lee lo de la anterior y lo descarta", () => {
    const k = calendarCacheKey("google", W, "UTC");
    writeCalendarCache("sesion-ana", k, resp());
    expect(readCalendarCache("sesion-beto", k)).toBeNull();
    expect(readCalendarCache("sesion-ana", k)).toBeNull(); // ya purgado
  });

  it("no guarda cargas incompletas", () => {
    const k = calendarCacheKey("google", W, "UTC");
    writeCalendarCache("s", k, resp(false));
    expect(readCalendarCache("s", k)).toBeNull();
  });

  it("caduca a los 5 minutos", () => {
    vi.useFakeTimers();
    const k = calendarCacheKey("google", W, "UTC");
    writeCalendarCache("s", k, resp());
    vi.advanceTimersByTime(4 * 60_000);
    expect(readCalendarCache("s", k)).not.toBeNull();
    vi.advanceTimersByTime(2 * 60_000);
    expect(readCalendarCache("s", k)).toBeNull();
  });

  it("acota el tamaño descartando lo más antiguo", () => {
    for (let i = 0; i < 60; i++) {
      writeCalendarCache("s", calendarCacheKey("google", { desde: `d${i}`, hasta: `h${i}` }, "UTC"), resp());
    }
    expect(readCalendarCache("s", calendarCacheKey("google", { desde: "d0", hasta: "h0" }, "UTC"))).toBeNull();
    expect(readCalendarCache("s", calendarCacheKey("google", { desde: "d59", hasta: "h59" }, "UTC"))).not.toBeNull();
  });

  it("cerrar sesión (clearAuthSession) vacía la caché", () => {
    persistAuthToken("jwt-ana", true);
    const k = calendarCacheKey("google", W, "UTC");
    writeCalendarCache("jwt-ana", k, resp());
    clearAuthSession();
    expect(readCalendarCache("jwt-ana", k)).toBeNull();
  });
});
