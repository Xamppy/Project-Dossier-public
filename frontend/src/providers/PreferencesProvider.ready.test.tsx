import { render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PreferencesProvider, usePreferences } from "./PreferencesProvider";

function Probe() {
  const { ready, effectiveTimezone, locale } = usePreferences();
  return <p data-testid="p">{`${ready}|${effectiveTimezone}|${locale}`}</p>;
}

describe("PreferencesProvider · ready", () => {
  it("en el servidor (sin localStorage) no está listo", () => {
    const html = renderToString(
      <PreferencesProvider>
        <Probe />
      </PreferencesProvider>,
    );
    expect(html).toContain("false|");
  });

  it("tras montar en el cliente está listo y ya expone las preferencias guardadas", () => {
    localStorage.setItem(
      "dossier-preferences",
      JSON.stringify({ locale: "fr", timezone: "Europe/London", timezoneFollowSystem: false }),
    );
    render(
      <PreferencesProvider>
        <Probe />
      </PreferencesProvider>,
    );
    expect(screen.getByTestId("p").textContent).toBe("true|Europe/London|fr");
  });
});
