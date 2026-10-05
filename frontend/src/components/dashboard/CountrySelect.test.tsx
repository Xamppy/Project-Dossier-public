import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import CountrySelect from "./CountrySelect";

describe("CountrySelect", () => {
  it("offers all countries in the active language and returns the selected code", () => {
    const onChange = vi.fn();
    render(
      <CountrySelect
        label="País / región"
        name="country"
        placeholder="Selecciona un país"
        value=""
        locale="es"
        onChange={onChange}
      />,
    );

    const select = screen.getByRole("combobox", { name: "País / región" });
    expect(select.querySelectorAll("option").length).toBeGreaterThan(200);
    expect(screen.getByRole("option", { name: "Chile" })).toHaveValue("CL");
    expect(screen.getByRole("option", { name: "Alemania" })).toHaveValue("DE");

    fireEvent.change(select, { target: { value: "CL" } });
    expect(onChange).toHaveBeenCalledWith("CL");
  });
});
