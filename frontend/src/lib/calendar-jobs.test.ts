import { describe, expect, it } from "vitest";
import { findJobForEvent, isEventJobActive } from "./calendar-jobs";

type J = {
  id: string;
  status: string;
  external_event_id?: string | null;
  calendar_provider?: string | null;
  job_type?: string | null;
};

function job(over: Partial<J> & { id: string }): J {
  return { status: "queued", external_event_id: "ev1", calendar_provider: "google", job_type: "calendar_manual", ...over };
}

describe("asociación de jobs a eventos por proveedor e id original", () => {
  it("el mismo id en Google y Outlook no cruza jobs", () => {
    const jobs = [
      job({ id: "g", calendar_provider: "google", status: "running" }),
      job({ id: "m", calendar_provider: "microsoft", status: "completed" }),
    ];
    expect(findJobForEvent(jobs, "ev1", "google")?.id).toBe("g");
    expect(findJobForEvent(jobs, "ev1", "microsoft")?.id).toBe("m");
    expect(isEventJobActive(jobs, "ev1", "google")).toBe(true);
    expect(isEventJobActive(jobs, "ev1", "microsoft")).toBe(false);
  });

  it("un job sin proveedor conocido no se atribuye a un proveedor concreto", () => {
    const jobs = [job({ id: "x", calendar_provider: null, status: "running" })];
    expect(findJobForEvent(jobs, "ev1", "google")).toBeUndefined();
    expect(isEventJobActive(jobs, "ev1", "google")).toBe(false);
  });

  it("sin proveedor conserva el comportamiento anterior (cualquiera)", () => {
    const jobs = [job({ id: "m", calendar_provider: "microsoft", status: "running" })];
    expect(findJobForEvent(jobs, "ev1")?.id).toBe("m");
    expect(isEventJobActive(jobs, "ev1")).toBe(true);
  });

  it("prefiere el job activo y, si no hay, el más reciente", () => {
    const jobs = [
      job({ id: "viejo", status: "completed" }),
      job({ id: "activo", status: "running" }),
      job({ id: "nuevo", status: "completed" }),
    ];
    expect(findJobForEvent(jobs, "ev1", "google")?.id).toBe("activo");
    expect(findJobForEvent([jobs[0], jobs[2]], "ev1", "google")?.id).toBe("nuevo");
  });

  it("id vacío o de otro evento no coincide", () => {
    const jobs = [job({ id: "a", external_event_id: "otro" })];
    expect(findJobForEvent(jobs, "ev1", "google")).toBeUndefined();
    expect(findJobForEvent(jobs, "", "google")).toBeUndefined();
    expect(findJobForEvent(jobs, null, "google")).toBeUndefined();
    expect(isEventJobActive(jobs, undefined, "google")).toBe(false);
  });

  it("solo queued y running cuentan como generando", () => {
    for (const status of ["completed", "failed", "cancelled"]) {
      expect(isEventJobActive([job({ id: "a", status })], "ev1", "google")).toBe(false);
    }
    expect(isEventJobActive([job({ id: "a", status: "queued" })], "ev1", "google")).toBe(true);
  });
});
