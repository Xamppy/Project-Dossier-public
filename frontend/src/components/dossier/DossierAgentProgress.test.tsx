import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import type { DossierCorporateProgressScope } from "@/lib/dossier-api";
import { corporateScopeOf, jobAfterFrames, jobFromFinalSnapshot } from "@/test/progress-state";
import DossierAgentProgress from "./DossierAgentProgress";

vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  return { useTranslation: () => ({ t, locale: "es" }) };
});

const t = createTranslator("es");

function rowOf(name: string): HTMLElement {
  const row = screen.getByText(name).closest("li");
  if (!row) throw new Error(`sin fila para ${name}`);
  return row as HTMLElement;
}

describe("DossierAgentProgress · búsquedas de la empresa", () => {
  it("CA7 · handles_skipped_cached_and_unknown_progress · cada agente con su estado y motivo, en el orden del servidor", () => {
    render(<DossierAgentProgress scope={corporateScopeOf(jobFromFinalSnapshot("calendario-agente-caido"))} />);
    const list = screen.getByRole("list", {
      name: t("progress.agents_aria", { name: "Empresa de Prueba SA" }),
    });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((r) => r.querySelector("[data-agent-label]")?.textContent)).toEqual([
      "Reino Unido",
      "EE. UU.",
      "Registros Europa",
      "Noticias",
      "Resumen",
    ]);
    expect(within(rowOf("Reino Unido")).getByText("Falló · error del proveedor")).toBeInTheDocument();
    expect(within(rowOf("EE. UU.")).getByText("Listo")).toBeInTheDocument();
    // Sin coincidencias es un resultado, no un error.
    expect(within(rowOf("Registros Europa")).getByText("Sin coincidencias")).toBeInTheDocument();
    expect(within(rowOf("Noticias")).getByText("Sin coincidencias")).toBeInTheDocument();
    expect(within(rowOf("Resumen")).getByText("Listo")).toBeInTheDocument();
  });

  it("CA2 · mientras corre muestra «Consultando» y la síntesis «Preparando resumen», sin porcentajes", () => {
    const { rerender, container } = render(
      <DossierAgentProgress scope={corporateScopeOf(jobAfterFrames("calendario-agente-caido", 6))} />,
    );
    for (const name of ["Reino Unido", "EE. UU.", "Registros Europa", "Noticias"]) {
      expect(within(rowOf(name)).getByText(t("progress.status.running_agent"))).toBeInTheDocument();
    }
    expect(within(rowOf("Resumen")).getByText(t("progress.status.pending"))).toBeInTheDocument();
    expect(rowOf("Reino Unido")).toHaveAttribute("aria-current", "step");

    rerender(<DossierAgentProgress scope={corporateScopeOf(jobAfterFrames("calendario-agente-caido", 11))} />);
    expect(within(rowOf("Resumen")).getByText(t("progress.status.running_synthesis"))).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/%/);
  });

  it("CA3 · renders_partial_modules_during_generation · la vista previa del resumen llega antes del terminal y se marca provisional", () => {
    render(
      <DossierAgentProgress
        scope={corporateScopeOf(jobAfterFrames("calendario-agente-caido", 12))}
        showPreviews
      />,
    );
    const preview = screen.getByRole("group", { name: /Resumen/ });
    expect(within(preview).getByText(t("progress.preview_badge"))).toBeInTheDocument();
    expect(within(preview).getByRole("heading", { name: "Dossier corporativo" })).toBeInTheDocument();
    expect(within(preview).getByText("Resumen ficticio.")).toBeInTheDocument();
  });

  it("UK y USA no tienen vista previa: no se muestra hueco ni error por eso", () => {
    render(
      <DossierAgentProgress scope={corporateScopeOf(jobFromFinalSnapshot("calendario-agente-caido"))} showPreviews />,
    );
    const previews = screen.getAllByRole("group");
    expect(previews).toHaveLength(1);
    expect(previews[0]).toHaveAccessibleName(/Resumen/);
    expect(screen.queryByText(/sin vista previa|no disponible/i)).not.toBeInTheDocument();
  });

  it("omitido muestra su motivo sin pintarlo como fallo; caché lo dice explícitamente", () => {
    const scope = corporateScopeOf(jobFromFinalSnapshot("calendario-agente-caido"));
    const skipped: DossierCorporateProgressScope = {
      ...scope,
      origin: "redis_cache",
      agents: scope.agents.map((a) =>
        a.agent_name === "agent_corporate_uk" ? { ...a, status: "skipped", reason_code: "out_of_scope" } : a,
      ),
    };
    render(<DossierAgentProgress scope={skipped} />);
    expect(within(rowOf("Reino Unido")).getByText("Omitido · no aplica a esta empresa")).toBeInTheDocument();
    expect(rowOf("Reino Unido")).toHaveAttribute("data-status", "skipped");
    expect(screen.getByText(t("progress.from_cache"))).toBeInTheDocument();
  });

  it("el Markdown de la vista previa no ejecuta HTML crudo y respeta truncated", () => {
    const scope = corporateScopeOf(jobFromFinalSnapshot("calendario-agente-caido"));
    const hostile: DossierCorporateProgressScope = {
      ...scope,
      partial_results: [
        {
          ...scope.partial_results[0],
          content: '## Resumen\n\n<img src="x" onerror="alert(1)"><script>alert(2)</script>[enlace](javascript:alert(3))',
          truncated: true,
        },
      ],
    };
    const { container } = render(<DossierAgentProgress scope={hostile} showPreviews />);
    expect(container.querySelector("img, script")).toBeNull();
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
    expect(screen.getByText(t("progress.preview_truncated"))).toBeInTheDocument();
  });

  it("la variante compacta no incluye vistas previas", () => {
    render(
      <DossierAgentProgress
        scope={corporateScopeOf(jobFromFinalSnapshot("calendario-agente-caido"))}
        variant="compact"
        showPreviews
      />,
    );
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });
});
