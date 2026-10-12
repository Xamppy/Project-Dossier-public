import { describe, expect, it } from "vitest";

import { formatTimezoneOffset } from "./timezones";

describe("formatTimezoneOffset", () => {
  // La coincidencia servidor/cliente la resuelve TimezoneSelect (etiquetas sin
  // offset hasta hidratar); aquí solo se calcula el offset vía Intl.
  it("calcula el offset real de la zona", () => {
    expect(formatTimezoneOffset("America/New_York", "en")).toMatch(/^GMT-\d+$/);
  });
});
