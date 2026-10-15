import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTranslator } from "@/i18n";
import { authRegister } from "@/lib/dossier-api";
import RegisterPage from "./page";

const t = createTranslator("es");
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/dossier-api", async (original) => ({
  ...await original<typeof import("@/lib/dossier-api")>(),
  authRegister: vi.fn(),
}));
vi.mock("@/providers/PreferencesProvider", () => ({
  useTranslation: () => ({ t: createTranslator("es"), locale: "es" }),
  usePreferences: () => ({ preferences: { locale: "es", timezone: "UTC", timezoneFollowSystem: false } }),
}));
vi.mock("@/components/settings/TimezoneSelect", () => ({ default: () => null }));

beforeEach(() => vi.mocked(authRegister).mockReset());

function fillForm(password: string) {
  const { container } = render(<RegisterPage />);
  const fields = {
    firstName: "Persona", lastName: "Prueba", company: "Empresa Prueba",
    email: "persona@example.com", password, confirmPassword: password,
  };
  for (const [name, value] of Object.entries(fields)) {
    fireEvent.change(container.querySelector(`input[name="${name}"]`)!, { target: { value } });
  }
  fireEvent.click(container.querySelector('input[type="checkbox"]')!);
  fireEvent.submit(container.querySelector("form")!);
}

describe("/register · límite bcrypt en bytes", () => {
  it.each(["a".repeat(73), "é".repeat(37), "🔐".repeat(19)])(
    "bloquea contraseñas que superan 72 bytes: %s", async (password) => {
      fillForm(password);
      expect(await screen.findByText(/72 bytes/)).toBeVisible();
      expect(authRegister).not.toHaveBeenCalled();
    },
  );

  it.each(["a".repeat(72), "é".repeat(36), "🔐".repeat(18)])(
    "envía sin truncar una contraseña de exactamente 72 bytes: %s", async (password) => {
      vi.mocked(authRegister).mockRejectedValue(new Error("API simulada"));
      fillForm(password);
      await waitFor(() => expect(authRegister).toHaveBeenCalledWith(expect.objectContaining({ password })));
    },
  );
});
