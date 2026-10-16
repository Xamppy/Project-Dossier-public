import { describe, expect, it } from "vitest";
import type { DossierGenerationJobApi } from "@/lib/dossier-api";
import { classifyJobOutcome } from "@/lib/dossier-job-outcome";
import {
  applyProgressEvent,
  mergeProgress,
  normalizeProgressSnapshot,
  parseProgressEvent,
} from "@/lib/dossier-job-progress";
import { JOB_EVENTS, S510_FIXTURES, loadS510Fixture, type S510FixtureName } from "@/test/s510-fixtures";

// Clasificación pura del resultado: separada del estado de conexión y de
// job.status, sin deducir éxito de la ausencia en agents_failed.

const D = (n: number) => `00000000-0000-4000-8000-00000000000${n}`;

const EXPECTED: Record<S510FixtureName, ReturnType<typeof classifyJobOutcome>> = {
  "calendario-agente-caido": {
    kind: "partial",
    recovered: false,
    fromCache: false,
    hasPartial: true,
    savedHref: `/dashboard/dossiers/folder/${D(5)}`,
    failedAgents: ["agent_corporate_uk"],
    failedPeople: ["Beto Ficticio"],
  },
  "personas-pdl": {
    kind: "complete",
    recovered: false,
    fromCache: false,
    hasPartial: true,
    savedHref: `/dashboard/dossiers/${D(2)}`,
    failedAgents: [],
    failedPeople: [],
  },
  "personas-pdl-respaldo": {
    kind: "complete",
    recovered: true,
    fromCache: false,
    hasPartial: true,
    savedHref: `/dashboard/dossiers/${D(2)}`,
    failedAgents: [],
    failedPeople: [],
  },
  "personas-pdl-informe-fallido": {
    kind: "failed_with_partial",
    recovered: false,
    fromCache: false,
    hasPartial: true,
    savedHref: null,
    failedAgents: [],
    failedPeople: [],
  },
  "personas-web-publica": {
    kind: "complete",
    recovered: false,
    fromCache: false,
    hasPartial: true,
    savedHref: `/dashboard/dossiers/${D(2)}`,
    failedAgents: [],
    failedPeople: [],
  },
  "personas-web-publica-fallida": {
    kind: "failed",
    recovered: false,
    fromCache: false,
    hasPartial: false,
    savedHref: null,
    failedAgents: [],
    failedPeople: [],
  },
  "personas-cache": {
    kind: "complete",
    recovered: false,
    fromCache: true,
    hasPartial: true,
    savedHref: `/dashboard/dossiers/${D(2)}`,
    failedAgents: [],
    failedPeople: [],
  },
  "personas-cancelada": {
    kind: "cancelled",
    recovered: false,
    fromCache: false,
    hasPartial: false,
    savedHref: null,
    failedAgents: [],
    failedPeople: [],
  },
};

/** El job tal como lo deja el stream: estado del último frame y progreso reproducido. */
function jobFromFrames(name: S510FixtureName): DossierGenerationJobApi {
  const { frames } = loadS510Fixture(name);
  let job = frames[0].data as unknown as DossierGenerationJobApi;
  let progress = null as ReturnType<typeof mergeProgress> | undefined;
  for (const frame of frames) {
    if (JOB_EVENTS.has(frame.event)) {
      job = frame.data as unknown as DossierGenerationJobApi;
      progress = mergeProgress(progress, normalizeProgressSnapshot(frame.data.progress));
    } else {
      const ev = parseProgressEvent(frame.event, frame.data, job.id);
      if (ev) progress = applyProgressEvent(progress, ev);
    }
  }
  return { ...job, progress: progress ?? null };
}

function personJob(over: Partial<DossierGenerationJobApi> = {}): DossierGenerationJobApi {
  return {
    id: "p-1",
    status: "completed",
    job_type: "person_manual",
    result: {
      filters_applied: {},
      search_attempts: [],
      profile_urls: [],
      profiles: [],
      posts_by_url: {},
      llm_analysis_markdown: "# Informe",
      warnings: [],
      saved_dossier: { id: "d-1", organization_id: "o", status: "complete", credits_consumed: 1, generation_duration_ms: 1 },
    },
    ...over,
  };
}

function calendarJob(saved: Record<string, unknown>, over: Partial<DossierGenerationJobApi> = {}) {
  return {
    id: "c-1",
    status: "completed",
    job_type: "calendar_manual",
    calendar_provider: "google",
    result: { reunion: { tema: "Kick-off" }, dossier_generado: "x", saved_dossiers: saved },
    ...over,
  } as DossierGenerationJobApi;
}

describe("classifyJobOutcome · los 8 escenarios de S5.10", () => {
  it.each(S510_FIXTURES)("%s: el GET final se clasifica como corresponde", (name) => {
    expect(classifyJobOutcome(loadS510Fixture(name).snapshot_final)).toEqual(EXPECTED[name]);
  });

  it.each(S510_FIXTURES)("%s: CA8 · lo reproducido por el stream da la misma clasificación", (name) => {
    expect(classifyJobOutcome(jobFromFrames(name))).toEqual(EXPECTED[name]);
  });

  it.each(S510_FIXTURES)("%s: mientras corre es in_progress aunque ya haya parciales", (name) => {
    const { frames } = loadS510Fixture(name);
    const running = frames.filter((f) => f.event === "job_status").at(-1)!;
    expect(classifyJobOutcome(running.data as unknown as DossierGenerationJobApi).kind).toBe("in_progress");
  });
});

describe("classifyJobOutcome · CA4 keeps_usable_result_when_an_agent_fails", () => {
  it("un agente corporativo caído con dossiers válidos es parcial, nunca completo", () => {
    const final = loadS510Fixture("calendario-agente-caido").snapshot_final;
    const result = final.result as Record<string, unknown>;
    const saved = result.saved_dossiers as { persons: { status: string }[] };
    saved.persons[1].status = "complete"; // Beto también sale bien: solo falla UK
    const outcome = classifyJobOutcome(final);
    expect(outcome.kind).toBe("partial");
    expect(outcome.failedAgents).toEqual(["agent_corporate_uk"]);
  });

  it("sin progreso, corporate_agents_failed de S4.9 también marca la parcialidad", () => {
    const outcome = classifyJobOutcome(
      calendarJob(
        { corporate: { id: "c", status: "complete" }, person: { id: "p", status: "complete" } },
        { result: { reunion: { tema: "x" }, dossier_generado: "x", saved_dossiers: { corporate: { id: "c", status: "complete" } }, corporate_agents_failed: ["agent_news"] } as never },
      ),
    );
    expect(outcome.kind).toBe("partial");
    expect(outcome.failedAgents).toEqual(["agent_news"]);
  });
});

describe("classifyJobOutcome · CA5 does_not_confuse_preview_with_saved_dossier", () => {
  it("un saved_dossier con ID y status failed no es un éxito ni da enlace", () => {
    const job = personJob();
    (job.result as { saved_dossier: { status: string } }).saved_dossier.status = "failed";
    const outcome = classifyJobOutcome(job);
    expect(outcome.kind).toBe("failed");
    expect(outcome.savedHref).toBeNull();
  });

  it("con perfiles en el progreso, el mismo caso es fallido con información disponible", () => {
    const final = loadS510Fixture("personas-pdl-informe-fallido").snapshot_final;
    const outcome = classifyJobOutcome({ ...final, status: "completed" });
    expect(outcome.kind).toBe("failed_with_partial");
    expect(outcome.savedHref).toBeNull();
  });

  it("en Calendario, si todos los dossiers guardados fallaron no hay éxito aunque haya vistas previas", () => {
    const final = loadS510Fixture("calendario-agente-caido").snapshot_final;
    const saved = (final.result as unknown as { saved_dossiers: Record<string, { status: string }[] | { status: string }> })
      .saved_dossiers;
    (saved.corporate as { status: string }).status = "failed";
    (saved.person as { status: string }).status = "failed";
    for (const p of saved.persons as { status: string }[]) p.status = "failed";
    const outcome = classifyJobOutcome(final);
    expect(outcome.kind).toBe("failed_with_partial");
    expect(outcome.savedHref).toBeNull();
  });

  it("un job fallido sin vistas previas es fallido a secas", () => {
    expect(classifyJobOutcome(personJob({ status: "failed", result: null })).kind).toBe("failed");
  });
});

describe("classifyJobOutcome · CA6 handles_multiple_people_and_legacy_results", () => {
  it("recorre toda la lista persons: una persona fallida y otra completa es parcial", () => {
    const outcome = classifyJobOutcome(
      calendarJob({
        corporate: { id: "c", status: "complete" },
        person: { id: "p1", status: "complete", subject_name: "Ana" },
        persons: [
          { id: "p1", status: "complete", subject_name: "Ana" },
          { id: "p2", status: "failed", subject_name: "Beto" },
        ],
      }),
    );
    expect(outcome.kind).toBe("partial");
    expect(outcome.failedPeople).toEqual(["Beto"]);
  });

  it("sin lista persons usa el campo legado person", () => {
    expect(
      classifyJobOutcome(
        calendarJob({ corporate: { id: "c", status: "complete" }, person: { id: "p", status: "failed", subject_name: "Ana" } }),
      ).kind,
    ).toBe("partial");
    expect(
      classifyJobOutcome(calendarJob({ person: { id: "p", status: "complete" }, folder: { id: "f", title: "t" } })),
    ).toMatchObject({ kind: "complete", savedHref: "/dashboard/dossiers/folder/f" });
  });

  it("un calendario que no guardó nada es fallido (comportamiento de S5.1)", () => {
    expect(classifyJobOutcome(calendarJob({})).kind).toBe("failed");
  });

  it("sin resultado se conserva el comportamiento anterior: listo", () => {
    expect(classifyJobOutcome(calendarJob({}, { result: null })).kind).toBe("complete");
  });
});

describe("classifyJobOutcome · CA7 handles_skipped_cached_and_unknown_progress", () => {
  it("agentes omitidos y sin coincidencias no son fallos", () => {
    const final = loadS510Fixture("calendario-agente-caido").snapshot_final;
    const progress = final.progress!;
    const corporate = progress.scopes[0] as { agents: { agent_name: string; status: string; reason_code: string | null }[] };
    const uk = corporate.agents.find((a) => a.agent_name === "agent_corporate_uk")!;
    uk.status = "skipped";
    uk.reason_code = "out_of_scope";
    const saved = (final.result as { saved_dossiers: { persons: { status: string }[] } }).saved_dossiers;
    saved.persons[1].status = "complete";
    (final.result as { corporate_agents_failed: string[] }).corporate_agents_failed = [];
    expect(classifyJobOutcome(final).kind).toBe("complete");
  });

  it("un agents_failed vacío no demuestra éxito si no se guardó nada", () => {
    expect(
      classifyJobOutcome(calendarJob({}, { result: { reunion: { tema: "x" }, dossier_generado: "", saved_dossiers: {}, corporate_agents_failed: [] } as never }))
        .kind,
    ).toBe("failed");
  });

  it("sin progreso (jobs anteriores a S5.4) se mantienen las reglas de antes: un aviso crítico es parcial", () => {
    const job = personJob();
    (job.result as { warnings: string[] }).warnings = ["DEEPSEEK_API_KEY no configurada"];
    expect(classifyJobOutcome(job).kind).toBe("partial");
    expect(classifyJobOutcome(personJob()).kind).toBe("complete");
  });

  it("con progreso, un aviso de texto no convierte en parcial un informe completo", () => {
    const final = loadS510Fixture("personas-pdl").snapshot_final;
    (final.result as { warnings: string[] }).warnings = ["PDL respondió con un aviso"];
    expect(classifyJobOutcome(final).kind).toBe("complete");
  });

  it("una etapa fallida sin recuperar deja el informe como parcial", () => {
    const final = loadS510Fixture("personas-pdl").snapshot_final;
    const scope = final.progress!.scopes[0] as { stages: { stage_id: string; status: string; reason_code: string | null }[] };
    const search = scope.stages.find((s) => s.stage_id === "person.pdl_search")!;
    search.status = "failed";
    search.reason_code = "provider_rate_limit";
    expect(classifyJobOutcome(final).kind).toBe("partial");
  });
});

describe("classifyJobOutcome · CA9 separates_transport_cancellation_and_generation_errors", () => {
  it("cancelado conserva los parciales pero no es éxito ni fallo", () => {
    const final = loadS510Fixture("personas-pdl-informe-fallido").snapshot_final;
    const outcome = classifyJobOutcome({ ...final, status: "cancelled" });
    expect(outcome.kind).toBe("cancelled");
    expect(outcome.hasPartial).toBe(true);
    expect(outcome.savedHref).toBeNull();
  });

  it("el corporativo manual sigue sus reglas: con id es completo, sin id es fallido", () => {
    const base = { id: "x", job_type: "corporate_manual", status: "completed" as const };
    expect(classifyJobOutcome({ ...base, result: { id: "corp-1" } as never })).toMatchObject({
      kind: "complete",
      savedHref: "/dashboard/dossiers/corp-1",
    });
    expect(classifyJobOutcome({ ...base, result: {} as never }).kind).toBe("failed");
  });
});
