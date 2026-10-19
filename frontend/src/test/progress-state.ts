/**
 * Estado del progreso tal como lo deja el proveedor a partir de los ejemplos de
 * S5.10: reproduciendo frames (stream en vivo) o aplicando solo el GET final
 * (recarga o conexión tardía). Usa el mismo reducer que la aplicación.
 */
import type {
  DossierCorporateProgressScope,
  DossierGenerationJobApi,
  DossierJobProgressSnapshot,
  DossierPersonProgressScope,
} from "@/lib/dossier-api";
import {
  applyProgressEvent,
  mergeProgress,
  normalizeProgressSnapshot,
  parseProgressEvent,
} from "@/lib/dossier-job-progress";
import { JOB_EVENTS, loadS510Fixture, type S510FixtureName } from "@/test/s510-fixtures";

export type ReplayedJob = DossierGenerationJobApi & { progress: DossierJobProgressSnapshot | null };

/** Job tras los primeros `count` frames (todos si se omite), como lo ve el proveedor. */
export function jobAfterFrames(name: S510FixtureName, count?: number): ReplayedJob {
  const { frames } = loadS510Fixture(name);
  let job = frames[0].data as unknown as DossierGenerationJobApi;
  let progress: DossierJobProgressSnapshot | null | undefined = null;
  for (const frame of frames.slice(0, count ?? frames.length)) {
    if (JOB_EVENTS.has(frame.event)) {
      job = frame.data as unknown as DossierGenerationJobApi;
      progress = mergeProgress(progress, normalizeProgressSnapshot(frame.data.progress));
    } else {
      const event = parseProgressEvent(frame.event, frame.data, job.id);
      if (event) progress = applyProgressEvent(progress, event);
    }
  }
  return { ...job, progress: progress ?? null };
}

/** Job a partir solo del GET final (recarga o conexión tardía). */
export function jobFromFinalSnapshot(name: S510FixtureName): ReplayedJob {
  const final = loadS510Fixture(name).snapshot_final;
  return { ...final, progress: mergeProgress(null, normalizeProgressSnapshot(final.progress)) };
}

export function corporateScopeOf(job: ReplayedJob): DossierCorporateProgressScope {
  const scope = job.progress?.scopes.find((s) => s.kind === "corporate");
  if (!scope || scope.kind !== "corporate") throw new Error("sin scope corporativo");
  return scope;
}

export function personScopeOf(job: ReplayedJob, scopeId = "person:0"): DossierPersonProgressScope {
  const scope = job.progress?.scopes.find((s) => s.scope_id === scopeId);
  if (!scope || scope.kind !== "person") throw new Error(`sin scope ${scopeId}`);
  return scope;
}
