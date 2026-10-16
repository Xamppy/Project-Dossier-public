import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import type { DossierPersonProgressScope } from "@/lib/dossier-api";
import { jobAfterFrames, jobFromFinalSnapshot, personScopeOf } from "@/test/progress-state";
import PersonResearchProgress from "./PersonResearchProgress";

vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  return { useTranslation: () => ({ t, locale: "es" }) };
});

const t = createTranslator("es");

function stageRow(label: string): HTMLElement {
  const row = screen.getByText(label).closest("li");
  if (!row) throw new Error(`sin fila para ${label}`);
  return row as HTMLElement;
}

const stageText = (label: string) => stageRow(label).querySelector("[data-stage-status]")?.textContent;
const CORPORATE_NAMES = /Reino Unido|EE\. UU\.|Registros Europa|Noticias|Preparando resumen/;

describe("PersonResearchProgress · etapas que declara el servidor", () => {
  it("CA14 · renders_real_pdl_stages · PDL muestra sus etapas reales en orden, sin nombres corporativos", () => {
    const { container } = render(<PersonResearchProgress scope={personScopeOf(jobFromFinalSnapshot("personas-pdl"))} />);
    const list = screen.getByRole("list", { name: t("progress.stages_aria", { name: "Ana Prueba" }) });
    expect(within(list).getAllByRole("listitem").map((li) => li.querySelector("[data-stage-label]")?.textContent)).toEqual([
      "Buscar un resultado guardado",
      "Buscar el perfil en PDL",
      "Búsqueda ampliada en PDL",
      "Preparar los perfiles encontrados",
      "Análisis de contexto con IA",
      "Redactar el informe con los perfiles",
      "Informe de respaldo (plan B)",
      "Revisar el informe",
      "Guardar el dossier",
    ]);
    expect(stageText("Buscar un resultado guardado")).toBe("Omitido · caché no disponible");
    expect(stageText("Buscar el perfil en PDL")).toBe("Listo");
    expect(stageText("Búsqueda ampliada en PDL")).toBe("Omitido · ya había perfiles suficientes");
    expect(stageText("Guardar el dossier")).toBe("Listo");
    expect(screen.getByText(t("progress.mode_label", { mode: t("person_research.source_pdl") }))).toBeInTheDocument();
    expect(container.textContent).not.toMatch(CORPORATE_NAMES);
  });

  it("CA14 · sin coincidencias en enrich y en search no es un error; lo que no aplica queda omitido", () => {
    render(<PersonResearchProgress scope={personScopeOf(jobFromFinalSnapshot("calendario-agente-caido"), "person:1")} />);
    expect(stageText("Buscar el perfil en PDL")).toBe("Sin coincidencias");
    expect(stageText("Búsqueda ampliada en PDL")).toBe("Sin coincidencias");
    expect(stageText("Preparar los perfiles encontrados")).toBe("Omitido · no hubo perfiles");
    expect(stageRow("Buscar el perfil en PDL")).toHaveAttribute("data-status", "completed");
    expect(stageText("Guardar el dossier")).toBe("Falló · no se obtuvo un informe válido");
  });

  it("CA15 · renders_model_only_progress_truthfully · Web pública: un paso de IA, sin búsquedas ni porcentajes", () => {
    const { container, rerender } = render(
      <PersonResearchProgress scope={personScopeOf(jobAfterFrames("personas-web-publica", 4))} />,
    );
    expect(stageText("Elaborar el informe con IA")).toBe(t("progress.status.running_ai_report"));
    expect(screen.getByText(t("progress.no_live_web_search"))).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(container.textContent).not.toMatch(/PDL|perfil|%|página|navega/i);

    rerender(<PersonResearchProgress scope={personScopeOf(jobFromFinalSnapshot("personas-web-publica"))} />);
    expect(stageText("Elaborar el informe con IA")).toBe("Listo");
  });

  it("CA17 · renders_actual_synthesis_fallback · el JSON inválido recuperado por el plan B no se presenta como fallo total", () => {
    render(<PersonResearchProgress scope={personScopeOf(jobFromFinalSnapshot("personas-pdl-respaldo"))} />);
    expect(stageText("Redactar el informe con los perfiles")).toBe(t("progress.status.recovered"));
    expect(stageRow("Redactar el informe con los perfiles")).toHaveAttribute("data-tone", "warning");
    expect(stageText("Informe de respaldo (plan B)")).toBe("Listo");
  });

  it("CA17 · sin respaldo ejecutado no se inventa: el plan B queda «no hizo falta» u omitido", () => {
    render(<PersonResearchProgress scope={personScopeOf(jobFromFinalSnapshot("personas-pdl-informe-fallido"))} />);
    expect(stageText("Redactar el informe con los perfiles")).toBe("Omitido · servicio no configurado");
    expect(stageText("Informe de respaldo (plan B)")).toBe("Omitido · no hizo falta");
  });

  it("CA22 · distinguishes_person_stage_and_transport_failures · el modelo caído es un fallo con su causa", () => {
    render(<PersonResearchProgress scope={personScopeOf(jobFromFinalSnapshot("personas-web-publica-fallida"))} />);
    expect(stageText("Elaborar el informe con IA")).toBe("Falló · error del proveedor");
    expect(stageText("Revisar el informe")).toBe("Omitido · no hubo texto que revisar");
    expect(stageText("Guardar el dossier")).toBe("Falló · no se obtuvo un informe válido");
  });

  it("CA23 · renders_context_analysis_selection · un análisis que terminó pero no se usó no es un error", () => {
    const scope = personScopeOf(jobFromFinalSnapshot("personas-pdl"));
    const always: DossierPersonProgressScope = {
      ...scope,
      stages: scope.stages.map((s) =>
        s.stage_id === "person.context_analysis"
          ? { ...s, status: "completed", reason_code: null, used_in_final: false }
          : s,
      ),
    };
    render(<PersonResearchProgress scope={always} />);
    expect(stageText("Análisis de contexto con IA")).toBe(t("progress.status.not_used_in_final"));
    expect(stageRow("Análisis de contexto con IA")).toHaveAttribute("data-tone", "success");
  });

  it("CA19 · renders_cached_person_result_without_fabricated_steps · la caché no parece una ejecución nueva", () => {
    render(<PersonResearchProgress scope={personScopeOf(jobFromFinalSnapshot("personas-cache"))} />);
    expect(stageText("Buscar un resultado guardado")).toBe("Resultado guardado encontrado");
    for (const label of ["Buscar el perfil en PDL", "Búsqueda ampliada en PDL", "Redactar el informe con los perfiles"]) {
      expect(stageText(label)).toBe("Omitido · se usó un resultado guardado");
    }
    expect(screen.getByText(t("progress.from_cache"))).toBeInTheDocument();
  });

  it("cancelación: lo que corría queda cancelado y lo demás sin alcanzar", () => {
    render(<PersonResearchProgress scope={personScopeOf(jobFromFinalSnapshot("personas-cancelada"))} />);
    expect(stageText("Buscar el perfil en PDL")).toBe("Cancelado");
    expect(stageText("Guardar el dossier")).toBe("Omitido · no se llegó a este paso");
    expect(screen.queryByRole("listitem", { current: "step" })).not.toBeInTheDocument();
  });

  it("la variante compacta resume en una línea la etapa en curso o el guardado", () => {
    const { rerender } = render(
      <PersonResearchProgress scope={personScopeOf(jobAfterFrames("personas-pdl", 11))} variant="compact" />,
    );
    expect(screen.getByText("Ana Prueba")).toBeInTheDocument();
    expect(screen.getByText("Redactar el informe con los perfiles · En curso")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();

    rerender(
      <PersonResearchProgress
        scope={personScopeOf(jobFromFinalSnapshot("calendario-agente-caido"), "person:1")}
        variant="compact"
      />,
    );
    expect(screen.getByText("Guardar el dossier · Falló · no se obtuvo un informe válido")).toBeInTheDocument();
  });
});
