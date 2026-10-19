import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import type { DossierPersonProgressScope } from "@/lib/dossier-api";
import { jobAfterFrames, jobFromFinalSnapshot, personScopeOf } from "@/test/progress-state";
import PersonResearchPartialResults from "./PersonResearchPartialResults";

vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  return { useTranslation: () => ({ t, locale: "es" }) };
});

const t = createTranslator("es");

describe("PersonResearchPartialResults · vistas previas de una persona", () => {
  it("CA16 · keeps_person_profiles_when_report_fails · el perfil se ve con nombre, cargo, empresa y enlaces, como provisional", () => {
    const { container } = render(
      <PersonResearchPartialResults scope={personScopeOf(jobFromFinalSnapshot("personas-pdl-informe-fallido"))} />,
    );
    const profiles = screen.getByRole("region", { name: t("progress.profiles_title") });
    const card = within(profiles).getByRole("listitem");
    expect(within(card).getByText("Ana Prueba")).toBeInTheDocument();
    expect(within(card).getByText(/Directora general/)).toBeInTheDocument();
    expect(within(card).getByText(/Empresa de Prueba SA/)).toBeInTheDocument();
    const link = within(card).getByRole("link");
    expect(link).toHaveAttribute("href", "https://www.linkedin.com/in/ana-prueba-ficticia");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(within(profiles).getByText(t("progress.preview_badge"))).toBeInTheDocument();
    expect(within(profiles).getByText(t("progress.profiles_provenance"))).toBeInTheDocument();
    // Nada fuera de la proyección: ni IDs del proveedor ni contactos del resultado completo.
    expect(container.textContent).not.toMatch(/pdl-ficticio|ana@example\.com|likelihood/);
  });

  it("los perfiles aparecen antes de que exista el informe", () => {
    render(<PersonResearchPartialResults scope={personScopeOf(jobAfterFrames("personas-pdl", 8))} />);
    expect(screen.getByRole("region", { name: t("progress.profiles_title") })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: t("progress.report_title") })).not.toBeInTheDocument();
  });

  it("CA15 · Web pública: el texto llega solo cuando vuelve y declara que no hubo fuentes consultadas", () => {
    const { container, rerender } = render(
      <PersonResearchPartialResults scope={personScopeOf(jobAfterFrames("personas-web-publica", 4))} />,
    );
    expect(container).toBeEmptyDOMElement();

    rerender(<PersonResearchPartialResults scope={personScopeOf(jobFromFinalSnapshot("personas-web-publica"))} />);
    const report = screen.getByRole("region", { name: t("progress.report_title") });
    expect(within(report).getByRole("heading", { name: "Informe con IA" })).toBeInTheDocument();
    expect(within(report).getByText(t("progress.provenance.model_only"))).toBeInTheDocument();
    expect(within(report).queryByRole("link")).not.toBeInTheDocument();
    // El análisis de contexto idéntico al informe no se repite.
    expect(screen.queryByRole("region", { name: t("progress.context_report_title") })).not.toBeInTheDocument();
  });

  it("CA22 · Web pública con el modelo caído no inventa contenido", () => {
    const { container } = render(
      <PersonResearchPartialResults scope={personScopeOf(jobFromFinalSnapshot("personas-web-publica-fallida"))} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("CA19 · caché antigua: resultado guardado sin inventar perfiles", () => {
    render(<PersonResearchPartialResults scope={personScopeOf(jobFromFinalSnapshot("personas-cache"))} />);
    expect(screen.queryByRole("region", { name: t("progress.profiles_title") })).not.toBeInTheDocument();
    expect(screen.getByText(t("progress.from_cache_profiles", { count: 2 }))).toBeInTheDocument();
    const report = screen.getByRole("region", { name: t("progress.report_title") });
    expect(within(report).getByText(t("progress.provenance.unknown"))).toBeInTheDocument();
  });

  it("showReport={false} deja solo los perfiles (Calendario muestra el informe guardado al terminar)", () => {
    render(
      <PersonResearchPartialResults scope={personScopeOf(jobFromFinalSnapshot("personas-pdl"))} showReport={false} />,
    );
    expect(screen.getByRole("region", { name: t("progress.profiles_title") })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: t("progress.report_title") })).not.toBeInTheDocument();
  });

  it("CA21 · una URL insegura nunca se convierte en enlace y un texto recortado lo avisa", () => {
    const scope = personScopeOf(jobFromFinalSnapshot("personas-pdl"));
    const hostile: DossierPersonProgressScope = {
      ...scope,
      partial_results: scope.partial_results.map((p) =>
        p.format === "person_profiles"
          ? {
              ...p,
              data: {
                ...p.data,
                profiles: [{ ...p.data.profiles[0], full_name: null, profile_urls: ["javascript:alert(1)", "http://x.test"] }],
              },
            }
          : { ...p, truncated: true },
      ),
    };
    render(<PersonResearchPartialResults scope={hostile} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText(t("progress.no_profile_name"))).toBeInTheDocument();
    expect(screen.getByText(t("progress.preview_truncated"))).toBeInTheDocument();
  });
});
