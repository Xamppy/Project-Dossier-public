import { describe, expect, it } from "vitest";
import type {
  DossierJobProgressSnapshot,
  DossierPersonProgressScope,
  DossierCorporateProgressScope,
} from "@/lib/dossier-api";
import {
  applyProgressEvent,
  mergeProgress,
  normalizeProgressSnapshot,
  parseProgressEvent,
  type DossierJobProgressEvent,
} from "@/lib/dossier-job-progress";
import {
  JOB_EVENTS,
  S510_FIXTURES,
  loadS510Fixture,
  seededShuffle,
  type S510Frame,
} from "@/test/s510-fixtures";

// Reducer del progreso (ADR 0009) contra los 8 escenarios reales de S5.10. Lo
// que manda es la revisión por entidad; el orden de llegada no debe importar.

const JOB_ID = "00000000-0000-4000-8000-000000000001";

type State = DossierJobProgressSnapshot | null | undefined;

function applyFrame(state: State, frame: S510Frame): State {
  if (JOB_EVENTS.has(frame.event)) {
    return mergeProgress(state, normalizeProgressSnapshot(frame.data.progress));
  }
  const event = parseProgressEvent(frame.event, frame.data, JOB_ID);
  return event ? applyProgressEvent(state, event) : state;
}

function replay(frames: S510Frame[], initial: State = null): State {
  return frames.reduce(applyFrame, initial);
}

function finalOnly(name: (typeof S510_FIXTURES)[number]): State {
  return mergeProgress(null, normalizeProgressSnapshot(loadS510Fixture(name).snapshot_final.progress));
}

function personScope(state: State, scopeId = "person:0"): DossierPersonProgressScope {
  const scope = state?.scopes.find((s) => s.scope_id === scopeId);
  if (!scope || scope.kind !== "person") throw new Error(`sin scope ${scopeId}`);
  return scope;
}

function corporateScope(state: State): DossierCorporateProgressScope {
  const scope = state?.scopes.find((s) => s.kind === "corporate");
  if (!scope || scope.kind !== "corporate") throw new Error("sin scope corporativo");
  return scope;
}

function progressFrames(name: (typeof S510_FIXTURES)[number]) {
  return loadS510Fixture(name).frames.filter((f) => !JOB_EVENTS.has(f.event));
}

function eventOf(frame: S510Frame): DossierJobProgressEvent {
  const event = parseProgressEvent(frame.event, frame.data, JOB_ID);
  if (!event) throw new Error(`frame ${frame.id} no es válido`);
  return event;
}

describe("dossier-job-progress · los 8 escenarios de S5.10", () => {
  it.each(S510_FIXTURES)("%s: todos sus eventos de progreso cumplen el contrato", (name) => {
    for (const frame of progressFrames(name)) {
      expect(parseProgressEvent(frame.event, frame.data, JOB_ID), `frame ${frame.id}`).not.toBeNull();
    }
  });

  it.each(S510_FIXTURES)(
    "%s: CA8 · reproducir todos los frames da el mismo progreso que solo el snapshot final",
    (name) => {
      const { frames } = loadS510Fixture(name);
      const fromFrames = replay(frames);
      expect(fromFrames).not.toBeNull();
      expect(fromFrames).toEqual(finalOnly(name));
    },
  );

  it.each(S510_FIXTURES)(
    "%s: CA2/CA20 · frames duplicados y desordenados no cambian el resultado",
    (name) => {
      const { frames } = loadS510Fixture(name);
      const expected = finalOnly(name);
      for (const seed of [1, 7, 42, 2026]) {
        const noisy = seededShuffle([...frames, ...frames.slice(0, frames.length / 2)], seed);
        expect(replay(noisy), `semilla ${seed}`).toEqual(expected);
      }
      expect(replay([...frames].reverse())).toEqual(expected);
    },
  );

  it.each(S510_FIXTURES)(
    "%s: CA8 · conectar tarde (snapshot final) y recibir el buffer viejo no cambia nada",
    (name) => {
      const late = finalOnly(name);
      const { frames } = loadS510Fixture(name);
      const replayed = replay(frames, late);
      expect(replayed).toEqual(late);
    },
  );
});

describe("dossier-job-progress · CA2 applies_agent_revisions_idempotently", () => {
  it("un evento duplicado o más viejo devuelve el mismo estado (misma referencia)", () => {
    const { frames } = loadS510Fixture("calendario-agente-caido");
    const upToUk = replay(frames.slice(0, 8)); // UK falla en el frame 8
    expect(corporateScope(upToUk).agents.find((a) => a.agent_name === "agent_corporate_uk")?.status).toBe(
      "failed",
    );
    const ukFailed = eventOf(frames[7]);
    const ukRunning = eventOf(frames[3]);
    expect(applyProgressEvent(upToUk, ukFailed)).toBe(upToUk);
    expect(applyProgressEvent(upToUk, ukRunning)).toBe(upToUk);
  });

  it("un terminal no vuelve a running aunque llegue con una revisión mayor", () => {
    const { frames } = loadS510Fixture("calendario-agente-caido");
    const state = replay(frames.slice(0, 13)); // síntesis completada
    const revive: DossierJobProgressEvent = {
      ...(eventOf(frames[10]) as Extract<DossierJobProgressEvent, { type: "agent_progress" }>),
      revision: 999,
    };
    const after = applyProgressEvent(state, revive);
    const synth = corporateScope(after).agents.find((a) => a.agent_name === "synthesize_llm");
    expect(synth?.status).toBe("completed");
  });

  it("un terminal gana metadatos: el fallo de la síntesis queda recuperado por el respaldo", () => {
    const { frames } = loadS510Fixture("personas-pdl-respaldo");
    const beforeRecovery = replay(frames.slice(0, 14));
    const synthesis = () =>
      personScope(state).stages.find((s) => s.stage_id === "person.profile_synthesis");
    let state = beforeRecovery;
    expect(synthesis()).toMatchObject({ status: "failed", reason_code: "structured_output_invalid" });
    expect(synthesis()?.recovered_by).toBeUndefined();
    state = applyFrame(state, frames[14]);
    expect(synthesis()).toMatchObject({
      status: "failed",
      reason_code: "structured_output_invalid",
      recovered_by: "person.markdown_fallback",
    });
  });

  it("el estado final del agente caído es failed con su motivo y el resto completa", () => {
    const state = finalOnly("calendario-agente-caido");
    const byName = Object.fromEntries(corporateScope(state).agents.map((a) => [a.agent_name, a]));
    expect(byName.agent_corporate_uk).toMatchObject({ status: "failed", reason_code: "provider_error" });
    expect(byName.agent_corporate_eu).toMatchObject({ status: "completed", reason_code: "no_matches" });
    expect(byName.agent_news).toMatchObject({ status: "completed", reason_code: "no_matches" });
    expect(byName.synthesize_llm).toMatchObject({ status: "completed", reason_code: null });
  });
});

describe("dossier-job-progress · snapshots", () => {
  it("acepta progress null o ausente sin perder lo que ya había", () => {
    const state = finalOnly("personas-pdl");
    expect(normalizeProgressSnapshot(null)).toBeNull();
    expect(normalizeProgressSnapshot(undefined)).toBeNull();
    expect(mergeProgress(state, null)).toBe(state);
    expect(mergeProgress(undefined, null)).toBeNull();
    expect(mergeProgress(null, null)).toBeNull();
  });

  it("rechaza otra versión del esquema y estructuras que no son un snapshot", () => {
    const raw = loadS510Fixture("personas-pdl").snapshot_final.progress as unknown as Record<string, unknown>;
    expect(normalizeProgressSnapshot({ ...raw, schema_version: 2 })).toBeNull();
    expect(normalizeProgressSnapshot({ ...raw, scopes: "no" })).toBeNull();
    expect(normalizeProgressSnapshot("progreso")).toBeNull();
    expect(normalizeProgressSnapshot([])).toBeNull();
  });

  it("un snapshot más viejo no pisa estados ni campos del scope más nuevos", () => {
    const { frames } = loadS510Fixture("calendario-agente-caido");
    const final = finalOnly("calendario-agente-caido");
    const old = normalizeProgressSnapshot(frames[13].data.progress); // revisión 13
    const merged = mergeProgress(final, old);
    expect(merged).toEqual(final);
  });

  it("el catálogo y el orden de las etapas son los que declara el servidor", () => {
    const pdl = personScope(finalOnly("personas-pdl"));
    const web = personScope(finalOnly("personas-web-publica"));
    expect(pdl.stages.map((s) => s.stage_id)).toEqual([
      "person.cache_lookup",
      "person.pdl_enrich",
      "person.pdl_search",
      "person.profile_normalization",
      "person.context_analysis",
      "person.profile_synthesis",
      "person.markdown_fallback",
      "person.report_finalize",
      "person.persist",
    ]);
    expect(web.stages.map((s) => s.stage_id)).toEqual([
      "person.cache_lookup",
      "person.context_analysis",
      "person.report_finalize",
      "person.persist",
    ]);
    expect(web).toMatchObject({ research_source: "gemini_web", live_web_search: false });
  });

  it("la caché antigua conserva profiles_count sin inventar perfiles", () => {
    const scope = personScope(finalOnly("personas-cache"));
    expect(scope).toMatchObject({ origin: "redis_cache", profiles_count: 2 });
    expect(scope.partial_results.some((p) => p.section === "person_profiles")).toBe(false);
  });

  it("la cancelación deja el progreso cerrado: lo que corría queda cancelled y lo pendiente sin alcanzar", () => {
    const scope = personScope(finalOnly("personas-cancelada"));
    const byId = Object.fromEntries(scope.stages.map((s) => [s.stage_id, s]));
    expect(byId["person.pdl_enrich"]).toMatchObject({ status: "cancelled" });
    expect(byId["person.persist"]).toMatchObject({ status: "skipped", reason_code: "not_reached" });
  });

  it("un perfil con campos de más en el snapshot se reduce a la proyección permitida", () => {
    const raw = loadS510Fixture("personas-pdl-informe-fallido").snapshot_final.progress as unknown as {
      scopes: { partial_results: { data: { profiles: Record<string, unknown>[] } }[] }[];
    };
    const profile = raw.scopes[0].partial_results[0].data.profiles[0];
    profile.emails = ["ana@example.com"];
    profile.data = { phone: "+56 9 0000 0000" };
    profile.profile_urls = ["http://inseguro.test/ana", "https://www.linkedin.com/in/ana-prueba-ficticia"];
    const scope = personScope(mergeProgress(null, normalizeProgressSnapshot(raw)));
    const partial = scope.partial_results.find((p) => p.section === "person_profiles");
    expect(partial?.format).toBe("person_profiles");
    if (partial?.format !== "person_profiles") return;
    expect(partial.data.profiles[0]).toEqual({
      record_key: "profile:0",
      full_name: "Ana Prueba",
      job_title: "Directora general",
      company: "Empresa de Prueba SA",
      profile_urls: ["https://www.linkedin.com/in/ana-prueba-ficticia"],
    });
  });
});

describe("dossier-job-progress · CA10 normalizes_legacy_agent_events_and_validates_new_contract", () => {
  const base = { schema_version: 1, job_id: JOB_ID, scope_id: "corporate:0", revision: 5 };

  it("descarta el agent_progress legado de S4.9 (job ID en dossier_id)", () => {
    expect(
      parseProgressEvent("agent_progress", { dossier_id: JOB_ID, agent: "uk", status: "failed" }, JOB_ID),
    ).toBeNull();
  });

  it.each([
    ["otra versión del esquema", { schema_version: 2 }],
    ["job ajeno", { job_id: "otro-job" }],
    ["scope malformado", { scope_id: "empresa" }],
    ["revisión cero", { revision: 0 }],
    ["revisión no entera", { revision: 1.5 }],
    ["estado desconocido", { status: "paused" }],
    ["agente desconocido", { agent_name: "agent_corporate_mx" }],
    ["agente en un scope de persona", { scope_id: "person:0" }],
  ])("agent_progress con %s se descarta", (_caso, over) => {
    const data = { ...base, agent_name: "agent_corporate_eu", status: "running", timestamp: null, reason_code: null, ...over };
    expect(parseProgressEvent("agent_progress", data, JOB_ID)).toBeNull();
  });

  it("un motivo desconocido o que no corresponde al estado no llega a la interfaz", () => {
    const unknown = parseProgressEvent(
      "agent_progress",
      { ...base, agent_name: "agent_corporate_eu", status: "failed", timestamp: null, reason_code: "Traceback: boom" },
      JOB_ID,
    );
    expect(unknown).toMatchObject({ status: "failed", reason_code: null });
    const mismatch = parseProgressEvent(
      "agent_progress",
      { ...base, agent_name: "agent_corporate_eu", status: "completed", timestamp: null, reason_code: "provider_error" },
      JOB_ID,
    );
    expect(mismatch).toMatchObject({ status: "completed", reason_code: null });
  });

  it("JSON que no es objeto se descarta", () => {
    expect(parseProgressEvent("stage_progress", "texto", JOB_ID)).toBeNull();
    expect(parseProgressEvent("partial_result", null, JOB_ID)).toBeNull();
    expect(parseProgressEvent("evento_nuevo", { ...base }, JOB_ID)).toBeNull();
  });
});

describe("dossier-job-progress · CA21 validates_person_progress_and_partial_projection", () => {
  const stage = {
    schema_version: 1,
    job_id: JOB_ID,
    scope_id: "person:0",
    revision: 3,
    research_source: "gemini_web",
    stage_id: "person.context_analysis",
    status: "running",
    timestamp: "2026-10-15T12:00:00+00:00",
    reason_code: null,
  };

  it.each([
    ["etapa de PDL en Web pública (modo incompatible)", { stage_id: "person.pdl_enrich" }],
    ["etapa desconocida", { stage_id: "person.web_search" }],
    ["modalidad desconocida", { research_source: "google" }],
    ["etapa en un scope corporativo", { scope_id: "corporate:0" }],
    ["nombre de agente corporativo como etapa", { stage_id: "agent_news" }],
  ])("stage_progress con %s se descarta", (_caso, over) => {
    expect(parseProgressEvent("stage_progress", { ...stage, ...over }, JOB_ID)).toBeNull();
  });

  it("un evento de una modalidad no se aplica a un scope de otra", () => {
    const pdlState = replay(loadS510Fixture("personas-pdl").frames.slice(0, 2));
    const webEvent = parseProgressEvent("stage_progress", { ...stage, revision: 50 }, JOB_ID)!;
    expect(webEvent).not.toBeNull();
    expect(applyProgressEvent(pdlState, webEvent)).toBe(pdlState);
  });

  it("un evento corporativo no se aplica a un scope de persona ni a un scope inexistente", () => {
    const pdlState = replay(loadS510Fixture("personas-pdl").frames.slice(0, 2));
    const corp = parseProgressEvent(
      "agent_progress",
      { schema_version: 1, job_id: JOB_ID, scope_id: "corporate:0", revision: 9, agent_name: "agent_news", status: "running", timestamp: null, reason_code: null },
      JOB_ID,
    )!;
    expect(applyProgressEvent(pdlState, corp)).toBe(pdlState);
    expect(applyProgressEvent(null, corp)).toBeNull();
  });

  it("el DTO de perfiles solo conserva campos permitidos y URLs https (máximo 3)", () => {
    const frame = loadS510Fixture("personas-pdl").frames[7];
    const data = frame.data as Record<string, unknown> & { data: { profiles: Record<string, unknown>[] } };
    data.data.profiles[0] = {
      ...data.data.profiles[0],
      emails: ["ana@example.com"],
      phone_numbers: ["+56 9 0000 0000"],
      verified_facts: { emails: ["x@y.z"] },
      profile_urls: [
        "javascript:alert(1)",
        "http://www.linkedin.com/in/ana",
        "https://usuario:clave@example.com/ana",
        "https://a.example/1",
        "https://b.example/2",
        "https://c.example/3",
        "https://d.example/4",
      ],
    };
    const event = parseProgressEvent("partial_result", data, JOB_ID);
    expect(event?.type).toBe("partial_result");
    if (event?.type !== "partial_result" || event.partial.format !== "person_profiles") return;
    expect(event.partial.data.profiles[0]).toEqual({
      record_key: "profile:0",
      full_name: "Ana Prueba",
      job_title: "Directora general",
      company: "Empresa de Prueba SA",
      profile_urls: ["https://a.example/1", "https://b.example/2", "https://c.example/3"],
    });
    expect(JSON.stringify(event)).not.toMatch(/example\.com|\+56|verified_facts/);
  });

  it.each([
    ["sección de UK (sin vista previa por el ADR 0009)", { section: "corporate_uk", agent_name: "agent_corporate_uk" }],
    ["texto vacío", { content: "   " }],
    ["texto de error interno", { content: "# Error\nTraceback…" }],
    ["formato desconocido", { format: "html" }],
  ])("partial_result corporativo con %s se descarta", (_caso, over) => {
    const ok = loadS510Fixture("calendario-agente-caido").frames[11].data;
    expect(parseProgressEvent("partial_result", ok, JOB_ID)).not.toBeNull();
    expect(parseProgressEvent("partial_result", { ...ok, ...over }, JOB_ID)).toBeNull();
  });

  it("perfiles que no son una lista invalidan el parcial", () => {
    const frame = loadS510Fixture("personas-pdl").frames[7];
    expect(
      parseProgressEvent("partial_result", { ...frame.data, data: { profiles: "Ana" } }, JOB_ID),
    ).toBeNull();
  });

  it("un parcial de persona de otra modalidad no se aplica al scope", () => {
    const { frames } = loadS510Fixture("personas-web-publica");
    const state = replay(frames.slice(0, 4));
    const pdlPartial = parseProgressEvent(
      "partial_result",
      { ...loadS510Fixture("personas-pdl").frames[7].data, revision: 99 },
      JOB_ID,
    )!;
    expect(pdlPartial).not.toBeNull();
    expect(applyProgressEvent(state, pdlPartial)).toBe(state);
  });
});

describe("dossier-job-progress · CA20 isolates_person_scopes_and_revisions", () => {
  it("un evento de un asistente no cambia el scope del otro ni el corporativo", () => {
    const { frames } = loadS510Fixture("calendario-agente-caido");
    const before = replay(frames.slice(0, 30)); // person:1 empieza en el frame 29
    const after = applyFrame(before, frames[30]); // person:1 · pdl_enrich completed (no_matches)
    expect(personScope(after, "person:0")).toBe(personScope(before, "person:0"));
    expect(corporateScope(after)).toBe(corporateScope(before));
    expect(
      personScope(after, "person:1").stages.find((s) => s.stage_id === "person.pdl_enrich"),
    ).toMatchObject({ status: "completed", reason_code: "no_matches" });
    expect(
      personScope(after, "person:0").stages.find((s) => s.stage_id === "person.pdl_enrich"),
    ).toMatchObject({ status: "completed", reason_code: null });
  });

  it("los eventos que llegan antes del catálogo se descartan sin crear scopes", () => {
    const { frames } = loadS510Fixture("personas-pdl");
    expect(replay(frames.slice(2, 6))).toBeNull();
  });
});
