import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import { getApiBaseUrl } from "@/lib/dossier-api";
import LoginPage from "./page";

const t = createTranslator("es");

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("@/lib/dossier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-api")>();
  return { ...actual, getStoredAccessToken: () => null };
});
vi.mock("@/providers/PreferencesProvider", () => ({
  useTranslation: () => ({ t: createTranslator("es"), locale: "es" }),
}));

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("/login · proveedores externos", () => {
  it("Google lleva al inicio de sesión de la API", () => {
    render(<LoginPage />);
    expect(screen.getByRole("link", { name: "Google" })).toHaveAttribute(
      "href",
      `${getApiBaseUrl()}/auth/google/login`,
    );
  });

  it("Microsoft aparece deshabilitado", () => {
    render(<LoginPage />);
    const boton = screen.getByRole("button", { name: "Microsoft" });
    expect(boton).toBeDisabled();
    expect(boton).toHaveAttribute("title", t("auth.login.microsoft_soon"));
  });

  it("muestra el error cuando Google devuelve al login", async () => {
    window.history.replaceState(null, "", "/login?error=google");
    render(<LoginPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(t("auth.error.google"));
  });
});
