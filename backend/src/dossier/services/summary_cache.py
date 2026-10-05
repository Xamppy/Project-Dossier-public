"""
Caché en proceso del resumen de Resumen (UX-KPI-01): una entrada por (usuario, organización),
vencimiento breve, una sola consulta en vuelo por clave y descarte de resultados obsoletos.

Es de un solo proceso a propósito: no hay Redis garantizado y el vencimiento corto acota la
desactualización entre instancias. Solo guarda lo que depende del calendario; los créditos
nunca pasan por aquí.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

TTL_SEGUNDOS = 60.0
TTL_ERROR_SEGUNDOS = 15.0
ESPERA_MAXIMA_SEGUNDOS = 30.0

Clave = tuple[UUID, UUID]
Reloj = Callable[[], float]


class SummaryCache:
    def __init__(self, reloj: Reloj = time.monotonic):
        self._reloj = reloj
        self._lock = threading.Lock()
        self._entradas: dict[Clave, tuple[float, bool, Any]] = {}
        self._versiones: dict[UUID, int] = {}
        self._candados: dict[Clave, threading.Lock] = {}

    def _candado(self, clave: Clave) -> threading.Lock:
        with self._lock:
            return self._candados.setdefault(clave, threading.Lock())

    def _vigente(self, clave: Clave) -> tuple[bool, Any]:
        with self._lock:
            e = self._entradas.get(clave)
            if e is not None and e[0] > self._reloj():
                return True, e[2]
            self._entradas.pop(clave, None)
            return False, None

    def get_or_compute(
        self,
        clave: Clave,
        calcular: Callable[[], tuple[Any, bool]],
    ) -> Any:
        """Valor vigente o resultado de ``calcular`` (que devuelve ``(valor, es_error)``).

        Las peticiones simultáneas de la misma clave esperan a la primera y comparten su
        resultado. Si la clave se invalida mientras se calcula, el resultado se devuelve
        pero no se guarda: podría haberse leído antes del cambio.
        """
        ok, valor = self._vigente(clave)
        if ok:
            return valor
        candado = self._candado(clave)
        if not candado.acquire(timeout=ESPERA_MAXIMA_SEGUNDOS):
            valor, _ = calcular()
            return valor
        try:
            ok, valor = self._vigente(clave)
            if ok:
                return valor
            with self._lock:
                version = self._versiones.get(clave[0], 0)
            valor, es_error = calcular()
            with self._lock:
                if self._versiones.get(clave[0], 0) == version:
                    ttl = TTL_ERROR_SEGUNDOS if es_error else TTL_SEGUNDOS
                    self._entradas[clave] = (self._reloj() + ttl, es_error, valor)
            return valor
        finally:
            candado.release()

    def invalidate(self, user_id: UUID) -> None:
        """Descarta todo lo del usuario (cualquier organización) y los cálculos en vuelo."""
        with self._lock:
            self._versiones[user_id] = self._versiones.get(user_id, 0) + 1
            for clave in [k for k in self._entradas if k[0] == user_id]:
                del self._entradas[clave]

    def expire_errors(self) -> None:
        with self._lock:
            for clave in [k for k, e in self._entradas.items() if e[1]]:
                del self._entradas[clave]

    def clear(self) -> None:
        with self._lock:
            self._entradas.clear()
            self._candados.clear()


SUMMARY_CACHE = SummaryCache()
