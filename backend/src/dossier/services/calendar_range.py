"""
Lectura de calendario por intervalo (UX-CAL-02): validación del rango, presupuesto
de paginación y resultado parcial explícito. Lo comparten los clientes de Google y
Microsoft Graph; ninguno de los dos conoce las reglas del otro.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

MAX_DIAS_RANGO = 62
POR_PAGINA = 250
MAX_PAGINAS = 10
PRESUPUESTO_SEGUNDOS = 20.0
TIMEOUT_PETICION_SEGUNDOS = 30.0

MOTIVO_LIMITE_PAGINAS = "limite_paginas"
MOTIVO_TIEMPO_AGOTADO = "tiempo_agotado"
MOTIVO_ERROR_PROVEEDOR = "error_proveedor"

Reloj = Callable[[], float]


class RangoInvalido(ValueError):
    """``desde``/``hasta`` ausentes, mal formados, sin offset, invertidos o demasiado largos."""


class ErrorProveedorCalendario(Exception):
    """El proveedor no entregó ninguna página válida (502 error remoto, 504 timeout)."""

    def __init__(self, status_code: int, detalle: str):
        super().__init__(detalle)
        self.status_code = status_code
        self.detalle = detalle


@dataclass(frozen=True)
class RangoConsulta:
    desde: datetime  # inclusivo, UTC
    hasta: datetime  # exclusivo, UTC

    def como_dict(self) -> dict[str, str]:
        return {"desde": _iso_z(self.desde), "hasta": _iso_z(self.hasta)}


@dataclass
class ResultadoRango:
    reuniones: list[dict] = field(default_factory=list)
    completo: bool = True
    motivo_incompleto: str | None = None


class Presupuesto:
    """Tiempo total disponible para recorrer las páginas de un proveedor."""

    def __init__(self, reloj: Reloj = time.monotonic, total: float = PRESUPUESTO_SEGUNDOS):
        self._reloj = reloj
        self._fin = reloj() + total

    def restante(self) -> float:
        return self._fin - self._reloj()

    def agotado(self) -> bool:
        return self.restante() <= 0

    def timeout_peticion(self) -> float:
        """Timeout de la próxima petición: nunca más que lo que queda del presupuesto."""
        return min(TIMEOUT_PETICION_SEGUNDOS, max(self.restante(), 0.001))


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_instante_con_offset(valor: str | None, nombre: str) -> datetime:
    if valor is None or not str(valor).strip():
        raise RangoInvalido(f"Falta «{nombre}»: indica ambos extremos del intervalo.")
    s = str(valor).strip()
    if s[-1] in "zZ":
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise RangoInvalido(f"«{nombre}» no es una fecha RFC3339 válida.") from e
    if "T" not in s and " " not in s:
        raise RangoInvalido(f"«{nombre}» debe incluir hora y offset (RFC3339).")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise RangoInvalido(f"«{nombre}» debe incluir zona u offset (por ejemplo «Z» o «-03:00»).")
    return dt.astimezone(UTC)


def parse_rango(desde: str | None, hasta: str | None) -> RangoConsulta:
    """Valida ``desde`` (inclusivo) y ``hasta`` (exclusivo); máximo 62 días."""
    if (desde is None or not str(desde).strip()) != (hasta is None or not str(hasta).strip()):
        raise RangoInvalido("«desde» y «hasta» deben enviarse juntos.")
    d = _parse_instante_con_offset(desde, "desde")
    h = _parse_instante_con_offset(hasta, "hasta")
    if d >= h:
        raise RangoInvalido("«desde» debe ser anterior a «hasta».")
    if h - d > timedelta(days=MAX_DIAS_RANGO):
        raise RangoInvalido(f"El intervalo no puede superar {MAX_DIAS_RANGO} días.")
    return RangoConsulta(desde=d, hasta=h)
