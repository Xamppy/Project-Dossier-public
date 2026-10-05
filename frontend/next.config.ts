import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /** Servidor autocontenido en .next/standalone para la imagen Docker (deploy/). */
  output: "standalone",
  // Cada aplicación se construye desde su propia carpeta del repositorio.
  turbopack: { root: __dirname },
  outputFileTracingRoot: __dirname,
  /** Playwright y dev en 127.0.0.1 (Next bloquea HMR cross-origin por defecto). */
  allowedDevOrigins: ["127.0.0.1"],
  /** La raíz del sitio debe abrir inicio de sesión (sin landing intermedia). */
  async redirects() {
    return [{ source: "/", destination: "/login", permanent: false }];
  },
};

export default nextConfig;
