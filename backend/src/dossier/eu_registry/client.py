"""Cliente HTTP de las fuentes europeas decididas en ADR 0003 (Francia, Alemania).

Solo hace la llamada HTTP y devuelve el JSON crudo del proveedor (misma
responsabilidad que ``companies_house/cli.py`` o ``sec_edgar/cli.py`` para sus
jurisdicciones). Normalizar esa respuesta a ``RegistroCorporativo`` (S1.9) es
tarea de S2.1 (agente europeo) y S2.3, no de este modulo.
"""
from __future__ import annotations

import os
from typing import Any

import requests

FRANCE_SEARCH_URL = "https://recherche-entreprises.api.gouv.fr/search"

# OffeneRegister.de publica el Handelsregister via una API SQL estilo Datasette
# (ver ADR 0003). El nombre de la base de datos varia entre snapshots del
# proyecto y el servicio devolvio 502 al verificar el esquema en 2026-09-12
# (detalle en .harness/progress.md, tarea S1.8): se deja configurable por
# variable de entorno para no tener que tocar codigo si cambia.
GERMANY_API_BASE = os.getenv("EU_REGISTRY_DE_API_BASE", "https://db.offeneregister.de")
GERMANY_DATABASE = os.getenv("EU_REGISTRY_DE_DATABASE", "openregister")
GERMANY_TABLE = os.getenv("EU_REGISTRY_DE_TABLE", "company")

DEFAULT_TIMEOUT = 20


class RegistroEuropeoError(RuntimeError):
    """Error al consultar una fuente corporativa europea (HTTP, timeout, formato inesperado)."""


def search_france_companies(query: str, *, limite: int = 5) -> list[dict[str, Any]]:
    """Busca empresas francesas por nombre y devuelve la lista cruda de ``results``.

    Fuente: API Recherche d'entreprises (data.gouv.fr), Open Data sin API key.
    """
    q = (query or "").strip()
    if not q:
        return []

    try:
        resp = requests.get(
            FRANCE_SEARCH_URL,
            params={"q": q, "per_page": max(1, min(limite, 25))},  # type: ignore[arg-type]  # valores str/int validos para requests; mypy infiere dict[str, object]
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RegistroEuropeoError(f"Error al consultar Recherche d'entreprises: {e}") from e

    return list(data.get("results") or [])


def search_germany_companies(query: str, *, limite: int = 5) -> list[dict[str, Any]]:
    """Busca empresas alemanas por nombre en el Handelsregister (OffeneRegister.de).

    Pendiente de verificacion en vivo del esquema exacto de la tabla (el servicio
    respondio 502 al intentarlo, ver docstring del modulo). Usa la convencion
    estandar de la API de tablas de Datasette; si la base/tabla real difiere,
    ajustar EU_REGISTRY_DE_API_BASE / _DATABASE / _TABLE, no este codigo.
    """
    q = (query or "").strip()
    if not q:
        return []

    url = f"{GERMANY_API_BASE}/{GERMANY_DATABASE}/{GERMANY_TABLE}.json"
    try:
        resp = requests.get(
            url,
            params={"name__contains": q, "_shape": "array", "_size": max(1, min(limite, 25))},  # type: ignore[arg-type]  # valores str/int validos para requests; mypy infiere dict[str, object]
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RegistroEuropeoError(f"Error al consultar OffeneRegister.de: {e}") from e

    if not isinstance(data, list):
        raise RegistroEuropeoError(
            "Forma de respuesta inesperada de OffeneRegister.de (se esperaba una lista)"
        )
    return data
