import { describe, expect, it } from "vitest";

import {
  canMutateDossiers,
  isOrgAdmin,
  isViewer,
  normalizeOrgRole,
} from "./org-role";

/**
 * Plantilla viva de prueba unitaria de frontend.
 *
 * Se eligió `org-role` a propósito y no un ejemplo inventado: decide quién puede
 * modificar dossiers en la interfaz, así que un error aquí es un error de control
 * de acceso visible para el usuario. Hasta hoy no tenía ninguna prueba.
 *
 * Fíjate en la estructura: cada bloque cubre los tres casos que exige la
 * política — normal, borde y error. Ver docs/dev/testing-policy.md §2.
 */

describe("normalizeOrgRole", () => {
  // Caso normal
  it.each(["admin", "user", "viewer", "api_user"] as const)(
    "acepta el rol conocido %s",
    (rol) => {
      expect(normalizeOrgRole(rol)).toBe(rol);
    },
  );

  // Casos borde
  it("normaliza mayúsculas y espacios", () => {
    expect(normalizeOrgRole("  ADMIN  ")).toBe("admin");
    expect(normalizeOrgRole("Viewer")).toBe("viewer");
  });

  it("trata null, undefined y cadena vacía como 'user'", () => {
    expect(normalizeOrgRole(null)).toBe("user");
    expect(normalizeOrgRole(undefined)).toBe("user");
    expect(normalizeOrgRole("")).toBe("user");
    expect(normalizeOrgRole("   ")).toBe("user");
  });

  // Caso de error
  it("cae a 'user' ante un rol desconocido, sin lanzar", () => {
    expect(normalizeOrgRole("superadmin")).toBe("user");
    expect(normalizeOrgRole("root")).toBe("user");
    expect(normalizeOrgRole("<script>")).toBe("user");
  });

  it("nunca devuelve algo fuera del conjunto conocido", () => {
    const conocidos = ["admin", "user", "viewer", "api_user"];
    for (const entrada of ["", "x", "ADMIN", null, undefined, "vIeWeR"]) {
      expect(conocidos).toContain(normalizeOrgRole(entrada));
    }
  });
});

describe("canMutateDossiers", () => {
  it("permite a admin, user y api_user", () => {
    expect(canMutateDossiers("admin")).toBe(true);
    expect(canMutateDossiers("user")).toBe(true);
    expect(canMutateDossiers("api_user")).toBe(true);
  });

  // La aserción que más importa de este archivo: viewer es de solo lectura.
  it("NO permite a viewer", () => {
    expect(canMutateDossiers("viewer")).toBe(false);
    expect(canMutateDossiers("VIEWER")).toBe(false);
    expect(canMutateDossiers(" viewer ")).toBe(false);
  });

  it("ante un rol desconocido aplica el de por omisión, que sí puede mutar", () => {
    // Documenta la conducta actual: lo desconocido cae a "user".
    // Si alguna vez se decide que lo desconocido debe ser de solo lectura,
    // esta prueba falla y obliga a tomar la decisión a conciencia.
    expect(canMutateDossiers("desconocido")).toBe(true);
  });
});

describe("isViewer e isOrgAdmin", () => {
  it("distinguen viewer de los demás roles", () => {
    expect(isViewer("viewer")).toBe(true);
    expect(isViewer("admin")).toBe(false);
    expect(isViewer(null)).toBe(false);
  });

  it("distinguen admin de los demás roles", () => {
    expect(isOrgAdmin("admin")).toBe(true);
    expect(isOrgAdmin("user")).toBe(false);
    expect(isOrgAdmin("api_user")).toBe(false);
    expect(isOrgAdmin(null)).toBe(false);
  });

  it("viewer y admin se excluyen entre sí para cualquier entrada", () => {
    for (const rol of ["admin", "user", "viewer", "api_user", "raro", null]) {
      expect(isViewer(rol) && isOrgAdmin(rol)).toBe(false);
    }
  });
});
