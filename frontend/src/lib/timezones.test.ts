import { describe, expect, it } from "vitest";

import { formatTimezoneOffset } from "./timezones";

describe("formatTimezoneOffset", () => {
  // UTC es literal (offset 0): Node ("GMT") y los navegadores ("GMT+0")
  // difieren en el string que devuelve Intl, lo que causaba un hydration
  // mismatch en el selector de zona horaria del registro. Debe ser fijo.
  it("devuelve un valor fijo para UTC en cualquier locale", () => {
    expect(formatTimezoneOffset("UTC", "es")).toBe("GMT");
    expect(formatTimezoneOffset("UTC", "en")).toBe("GMT");
  });

  // Caso normal: zonas con offset real siguen calculándose vía Intl.
  it("calcula el offset real para otras zonas", () => {
    expect(formatTimezoneOffset("America/New_York", "en")).toMatch(/^GMT-\d+$/);
  });
});
