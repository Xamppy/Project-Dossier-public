import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// Cada prueba arranca con el DOM limpio. Sin esto, un componente montado en una
// prueba aparece en la siguiente y los fallos se vuelven imposibles de leer.
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

// Ninguna prueba sale a la red. Misma regla que en el backend: una prueba que
// depende de internet no es una prueba. Si un componente llama a fetch, simula
// la respuesta explícitamente en esa prueba.
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => {
      throw new Error(
        "Esta prueba intentó llamar a fetch. Simula la respuesta con " +
          "vi.stubGlobal('fetch', vi.fn().mockResolvedValue(...)) dentro de la prueba.",
      );
    }),
  );
});

// jsdom no implementa estas dos y varios componentes de Tailwind las usan.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }),
});

globalThis.ResizeObserver =
  globalThis.ResizeObserver ??
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
