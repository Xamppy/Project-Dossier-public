import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTranslator } from "@/i18n";
import OverviewCalendarsSection from "./OverviewCalendarsSection";

const configurados: { google: boolean | null; microsoft: boolean | null } = {
  google: null,
  microsoft: null,
};

vi.mock("@/hooks/useCalendarProvidersConfigured", () => ({
  useCalendarProvidersConfigured: () => configurados,
}));

vi.mock("@/components/dashboard/CalendarIntegrationPanel", () => ({
  default: ({ provider }: { provider: string }) => <div data-testid={`panel-${provider}`} />,
}));

vi.mock("@/components/dashboard/CalendarMeetingFormatGuide", () => ({ default: () => null }));

vi.mock("@/providers/PreferencesProvider", () => {
  const t = createTranslator("es");
  return { useTranslation: () => ({ t, locale: "es" }) };
});

beforeEach(() => {
  configurados.google = null;
  configurados.microsoft = null;
});

describe("OverviewCalendarsSection", () => {
  it("oculta Outlook si su OAuth no está configurado en el servidor", () => {
    configurados.google = true;
    configurados.microsoft = false;

    render(<OverviewCalendarsSection />);

    expect(screen.queryByTestId("panel-microsoft")).toBeNull();
    expect(screen.queryByText("Microsoft Outlook")).toBeNull();
    expect(screen.getByTestId("panel-google")).toBeInTheDocument();
  });

  it("mientras no se sabe (null) muestra ambos proveedores", () => {
    render(<OverviewCalendarsSection />);

    expect(screen.getByTestId("panel-microsoft")).toBeInTheDocument();
    expect(screen.getByTestId("panel-google")).toBeInTheDocument();
  });
});
