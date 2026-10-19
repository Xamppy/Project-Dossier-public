import { describe, expect, it } from "vitest";
import {
  CALENDAR_MEETING_FORMAT_EXAMPLE,
  descriptionHasCompanyHint,
  descriptionHasPersonHint,
} from "./calendar-meeting-format";

describe("plantilla de ejemplo del formato de reunión", () => {
  it("la reconocen los detectores de empresa y de persona", () => {
    expect(descriptionHasCompanyHint(CALENDAR_MEETING_FORMAT_EXAMPLE)).toBe(true);
    expect(descriptionHasPersonHint(CALENDAR_MEETING_FORMAT_EXAMPLE)).toBe(true);
  });

  it("solo usa datos ficticios: todos los correos son de example.com", () => {
    const correos = CALENDAR_MEETING_FORMAT_EXAMPLE.match(/[\w.+-]+@[\w.-]+/g) ?? [];
    expect(correos.length).toBeGreaterThan(0);
    for (const correo of correos) {
      expect(correo.endsWith("@example.com")).toBe(true);
    }
  });
});
