import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import StatCard from "./StatCard";

describe("StatCard", () => {
  it("conserva el uso heredado: valor, rótulo y tendencia", () => {
    render(<StatCard value={7} label="Activos" trend="↑" />);
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Activos")).toBeInTheDocument();
    expect(screen.getByText("↑")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("muestra líneas de detalle y las enlaza como descripción accesible, sin acciones", () => {
    render(
      <StatCard value="75 %" label="Preparadas a tiempo" details={["6 de 8 reuniones", "11 dossiers"]}
        description="Explicación accesible de la diferencia." />,
    );
    const grupo = screen.getByRole("group", { name: /Preparadas a tiempo/ });
    expect(screen.getByText("6 de 8 reuniones")).toBeInTheDocument();
    expect(screen.getByText("11 dossiers")).toBeInTheDocument();
    const descripcion = grupo.getAttribute("aria-describedby") ?? "";
    expect(descripcion.length).toBeGreaterThan(0);
    expect(document.getElementById(descripcion.split(" ")[0])).toHaveTextContent("Explicación accesible");
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("marca la tarjeta como ocupada mientras carga", () => {
    render(<StatCard value="—" label="Cobertura" busy />);
    expect(screen.getByRole("group", { name: /Cobertura/ })).toHaveAttribute("aria-busy", "true");
  });
});
