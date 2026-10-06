import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import GoogleLoginReturnPage from "./page";

const replace = vi.fn();
const persist = vi.fn();
const me = vi.fn();
const preview = vi.fn();
const clear = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));
vi.mock("@/lib/dossier-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dossier-api")>();
  return {
    ...actual,
    persistAuthToken: (...a: unknown[]) => persist(...a),
    fetchAuthMe: () => me(),
    writeDossierUserPreview: (...a: unknown[]) => preview(...a),
    clearAuthSession: () => clear(),
  };
});
vi.mock("@/providers/PreferencesProvider", () => ({
  useTranslation: () => ({ t: createTranslator("es"), locale: "es" }),
}));

beforeEach(() => {
  [replace, persist, me, preview, clear].forEach((f) => f.mockReset());
  me.mockResolvedValue({
    email: "ana@example.test",
    full_name: "Ana",
    company_name: "Personal",
    workspace_kind: "personal",
    organization_plan: "free",
    is_platform_admin: false,
  });
});

describe("/auth/google", () => {
  it("guarda el token del fragmento, lo borra de la URL y entra al dashboard", async () => {
    window.history.replaceState(null, "", "/auth/google#token=jwt-de-la-app");
    render(<GoogleLoginReturnPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(persist).toHaveBeenCalledWith("jwt-de-la-app", true);
    expect(preview).toHaveBeenCalledWith(expect.objectContaining({ email: "ana@example.test" }), "local");
    expect(window.location.hash).toBe("");
  });

  it("sin token vuelve al login con error", async () => {
    window.history.replaceState(null, "", "/auth/google");
    render(<GoogleLoginReturnPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?error=google"));
    expect(persist).not.toHaveBeenCalled();
  });

  it("si la API rechaza el token, limpia la sesión y vuelve al login", async () => {
    me.mockRejectedValue(new Error("401"));
    window.history.replaceState(null, "", "/auth/google#token=caducado");
    render(<GoogleLoginReturnPage />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?error=google"));
    expect(clear).toHaveBeenCalled();
  });
});
