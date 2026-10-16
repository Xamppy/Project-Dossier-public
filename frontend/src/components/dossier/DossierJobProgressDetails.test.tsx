import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import { jobAfterFrames, jobFromFinalSnapshot } from "@/test/progress-state";
import type { DossierJobProgressSnapshot } from "@/lib/dossier-api";
import {
  applyProgressEvent,
  mergeProgress,
  normalizeProgressSnapshot,
  parseProgressEvent,
} from "@/lib/dossier-job-progress";
import { JOB_EVENTS, S510_FIXTURES, loadS510Fixture, seededShuffle, type S510Frame } from "@/test/s510-fixtures";
import DossierJobProgressDetails from "./DossierJobProgressDetails";

vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  return { useTranslation: () => ({ t, locale: "es" }) };
});

const t = createTranslator("es");

describe("DossierJobProgressDetails · empresa y asistentes por separado", () => {
  it("CA6 · handles_multiple_people_and_legacy_results · un bloque por asistente además de las búsquedas de la empresa", () => {
    render(<DossierJobProgressDetails progress={jobFromFinalSnapshot("calendario-agente-caido").progress} />);
    expect(screen.getByRole("heading", { name: new RegExp(t("progress.company_title")) })).toBeInTheDocument();
    const people = screen.getByRole("region", { name: t("progress.people_title") });
    const ana = within(people).getByRole("list", { name: t("progress.stages_aria", { name: "Ana Prueba" }) });
    const beto = within(people).getByRole("list", { name: t("progress.stages_aria", { name: "Beto Ficticio" }) });
    expect(within(ana).getByText("Guardar el dossier").closest("li")).toHaveTextContent("Listo");
    expect(within(beto).getByText("Guardar el dossier").closest("li")).toHaveTextContent(
      "Falló · no se obtuvo un informe válido",
    );
  });

  it("CA20 · isolates_person_scopes_and_revisions · los perfiles de un asistente no aparecen en el otro", () => {
    render(<DossierJobProgressDetails progress={jobAfterFrames("calendario-agente-caido", 20).progress} showPreviews />);
    const people = screen.getByRole("region", { name: t("progress.people_title") });
    const blocks = within(people).getAllByRole("article");
    expect(blocks).toHaveLength(2);
    expect(within(blocks[0]).getByRole("region", { name: t("progress.profiles_title") })).toBeInTheDocument();
    expect(within(blocks[1]).queryByRole("region", { name: t("progress.profiles_title") })).not.toBeInTheDocument();
  });

  it("sin progreso (jobs anteriores a S5.4) no muestra nada", () => {
    const { container } = render(<DossierJobProgressDetails progress={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("la variante compacta da una lista corta de la empresa y una línea por asistente", () => {
    render(
      <DossierJobProgressDetails progress={jobAfterFrames("calendario-agente-caido", 32).progress} variant="compact" />,
    );
    expect(screen.getAllByRole("list")).toHaveLength(1);
    expect(screen.getByText("Ana Prueba")).toBeInTheDocument();
    expect(screen.getByText("Beto Ficticio")).toBeInTheDocument();
    expect(screen.getByText("Búsqueda ampliada en PDL · En curso")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: t("progress.profiles_title") })).not.toBeInTheDocument();
  });
});

describe("DossierJobProgressDetails · CA8 misma pantalla en vivo y tras recargar", () => {
  it.each(S510_FIXTURES)("%s: reproducir los frames pinta lo mismo que aplicar solo el GET final", (name) => {
    const live = render(<DossierJobProgressDetails progress={jobAfterFrames(name).progress} showPreviews />);
    const liveHtml = live.container.innerHTML;
    live.unmount();
    const reloaded = render(<DossierJobProgressDetails progress={jobFromFinalSnapshot(name).progress} showPreviews />);
    expect(reloaded.container.innerHTML).toBe(liveHtml);
    expect(liveHtml).not.toBe("");
  });

  it.each(S510_FIXTURES)("%s: frames duplicados y desordenados pintan lo mismo", (name) => {
    const expected = render(<DossierJobProgressDetails progress={jobFromFinalSnapshot(name).progress} showPreviews />)
      .container.innerHTML;
    const { frames } = loadS510Fixture(name);
    const noisy = render(
      <DossierJobProgressDetails progress={replay(seededShuffle([...frames, ...frames], 11))} showPreviews />,
    ).container.innerHTML;
    expect(expected).not.toBe("");
    expect(noisy).toBe(expected);
  });
});

/** Mismo reducer que el proveedor, en el orden dado (no el del archivo). */
function replay(frames: S510Frame[]): DossierJobProgressSnapshot | null {
  let state: DossierJobProgressSnapshot | null | undefined = null;
  for (const frame of frames) {
    if (JOB_EVENTS.has(frame.event)) {
      state = mergeProgress(state, normalizeProgressSnapshot(frame.data.progress));
    } else {
      const event = parseProgressEvent(frame.event, frame.data, "00000000-0000-4000-8000-000000000001");
      if (event) state = applyProgressEvent(state, event);
    }
  }
  return state ?? null;
}
