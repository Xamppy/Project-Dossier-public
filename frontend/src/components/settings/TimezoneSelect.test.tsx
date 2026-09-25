import { act } from "react";
import { renderToString } from "react-dom/server";
import { hydrateRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import TimezoneSelect from "./TimezoneSelect";

describe("TimezoneSelect hydration", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("hydrates when Intl returns different UTC labels on server and client", async () => {
    const realFormatToParts = Intl.DateTimeFormat.prototype.formatToParts;
    let utcOffset = "GMT";
    vi.spyOn(Intl.DateTimeFormat.prototype, "formatToParts").mockImplementation(
      function (this: Intl.DateTimeFormat, date?: Date | number) {
        const parts = realFormatToParts.call(this, date);
        if (this.resolvedOptions().timeZone !== "UTC") return parts;
        return parts.map((part) =>
          part.type === "timeZoneName" ? { ...part, value: utcOffset } : part,
        );
      },
    );

    const props = {
      timezone: "America/Santiago",
      followSystem: true,
      onChange: vi.fn(),
      locale: "es" as const,
      systemLabel: "Automática ({hint})",
      t: (key: string) => key === "timezone.utc" ? "UTC" : key,
    };
    const serverHtml = renderToString(<TimezoneSelect {...props} />);
    const container = document.createElement("div");
    container.innerHTML = serverHtml;
    document.body.appendChild(container);

    utcOffset = "GMT+0";
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    let root: ReturnType<typeof hydrateRoot> | undefined;
    await act(async () => {
      root = hydrateRoot(container, <TimezoneSelect {...props} />);
    });

    expect(error.mock.calls.flat().join(" ")).not.toMatch(/hydration|server rendered text/i);
    expect(container.querySelector('option[value="UTC"]')).toHaveTextContent("UTC (GMT+0)");

    await act(async () => root?.unmount());
  });

  it("hydrates when the browser and server have different system timezones", async () => {
    const realResolvedOptions = Intl.DateTimeFormat.prototype.resolvedOptions;
    let systemTimezone = "UTC";
    vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(
      function (this: Intl.DateTimeFormat) {
        return { ...realResolvedOptions.call(this), timeZone: systemTimezone };
      },
    );

    const props = {
      timezone: "UTC",
      followSystem: true,
      onChange: vi.fn(),
      locale: "es" as const,
      systemLabel: "Automática ({hint})",
      t: (key: string) => key,
    };
    const serverHtml = renderToString(<TimezoneSelect {...props} />);
    const container = document.createElement("div");
    container.innerHTML = serverHtml;
    document.body.appendChild(container);
    expect(container.querySelector('option[value="__system__"]')).toHaveTextContent("Automática");

    systemTimezone = "America/Santiago";
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    let root: ReturnType<typeof hydrateRoot> | undefined;
    await act(async () => {
      root = hydrateRoot(container, <TimezoneSelect {...props} />);
    });

    expect(error.mock.calls.flat().join(" ")).not.toMatch(/hydration|server rendered text/i);
    expect(container.querySelector('option[value="__system__"]')).toHaveTextContent("Santiago");

    await act(async () => root?.unmount());
  });
});
