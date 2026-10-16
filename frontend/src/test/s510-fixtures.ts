/**
 * Ejemplos reales de S5.10 (specs/fixtures/S5.10-progreso/): frames que publicó
 * el backend con proveedores simulados y el GET final del job. Las pruebas los
 * leen tal cual, sin copiarlos ni editarlos; cada lectura devuelve un objeto nuevo.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { DossierGenerationJobApi } from "@/lib/dossier-api";

export const S510_FIXTURES = [
  "calendario-agente-caido",
  "personas-pdl",
  "personas-pdl-respaldo",
  "personas-pdl-informe-fallido",
  "personas-web-publica",
  "personas-web-publica-fallida",
  "personas-cache",
  "personas-cancelada",
] as const;

export type S510FixtureName = (typeof S510_FIXTURES)[number];

export type S510Frame = { id: number; event: string; data: Record<string, unknown> };

export type S510Fixture = {
  escenario: string;
  descripcion: string;
  frames: S510Frame[];
  snapshot_final: DossierGenerationJobApi;
};

// Vitest corre desde frontend/ (npm test y scripts/qa.py); en jsdom import.meta.url no es file://.
const DIR = resolve(process.cwd(), "../specs/fixtures/S5.10-progreso");

export function loadS510Fixture(name: S510FixtureName): S510Fixture {
  return JSON.parse(readFileSync(resolve(DIR, `${name}.json`), "utf-8")) as S510Fixture;
}

export const JOB_EVENTS = new Set(["job_status", "job_completed", "job_failed"]);

/** Frame tal como lo escribiría el servidor en el cuerpo SSE. */
export function frameToSse(frame: S510Frame): string {
  return `id: ${frame.id}\nevent: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`;
}

/** Orden pseudoaleatorio reproducible (LCG) para desordenar frames sin azar real. */
export function seededShuffle<T>(items: readonly T[], seed: number): T[] {
  const out = [...items];
  let state = seed >>> 0 || 1;
  for (let i = out.length - 1; i > 0; i -= 1) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    const j = state % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}
