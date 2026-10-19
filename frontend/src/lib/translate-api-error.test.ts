import { describe, expect, it } from "vitest";
import { createTranslator } from "@/i18n";
import { SUPPORTED_LOCALES } from "@/i18n/types";
import { DossierApiError } from "@/lib/dossier-api";
import { translateApiErrorMessage } from "@/lib/translate-backend-message";

function passwordError() {
  return new DossierApiError(422, "body.password: La contraseña supera 72 bytes.", {
    detail: [{ type: "password_too_long_bytes", loc: ["body", "password"], ctx: { max_bytes: 72 } }],
  });
}

describe("validación de contraseña de la API", () => {
  it.each(SUPPORTED_LOCALES)("muestra un mensaje comprensible en %s", (locale) => {
    const t = createTranslator(locale);
    const message = translateApiErrorMessage(passwordError(), t);
    expect(message).toContain("72");
    expect(message).not.toBe(t("errors.server_generic"));
    expect(message).not.toContain("body.password");
    expect(message).not.toContain("password_too_long_bytes");
  });
});
