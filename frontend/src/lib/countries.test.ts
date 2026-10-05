import { describe, expect, it } from "vitest";
import {
  COUNTRY_CODES,
  countryCodeFromName,
  countryNameForApi,
  getCountryOptions,
} from "./countries";

describe("country options", () => {
  it("contains the full country list with localized, sorted labels", () => {
    const options = getCountryOptions("es");

    expect(COUNTRY_CODES).toHaveLength(249);
    expect(options).toHaveLength(COUNTRY_CODES.length);
    expect(options.map(({ label }) => label)).toEqual(
      [...options.map(({ label }) => label)].sort((a, b) => a.localeCompare(b, "es")),
    );
    expect(options).toContainEqual({ code: "CL", label: "Chile" });
  });

  it("maps legacy country names and submits the English country name", () => {
    expect(countryCodeFromName("United Kingdom")).toBe("GB");
    expect(countryCodeFromName("España")).toBe("ES");
    expect(countryNameForApi("GB")).toBe("United Kingdom");
    expect(countryNameForApi("")).toBe("");
  });
});
