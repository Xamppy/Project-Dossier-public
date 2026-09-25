"""Cliente HTTP del proveedor de noticias decidido en ADR 0004 (GDELT + NewsAPI).

Solo hace la llamada HTTP y devuelve la lista cruda de articulos del proveedor
(misma responsabilidad que ``eu_registry/client.py`` para sus fuentes). Deduplicar
articulos entre proveedores (S3.2), filtrar homonimos (S3.3) y registrar
procedencia completa (S3.4) es tarea del agente de noticias, no de este modulo.
"""
from __future__ import annotations

import os
from typing import Any

import requests

GDELT_SEARCH_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_SEARCH_URL = "https://newsapi.org/v2/everything"

DEFAULT_TIMEOUT = 20


class ProveedorNoticiasError(RuntimeError):
    """Error al consultar un proveedor de noticias (HTTP, timeout, formato inesperado)."""


def search_gdelt_articles(query: str, *, limite: int = 10) -> list[dict[str, Any]]:
    """Busca articulos en GDELT DOC 2.0 de los ultimos 30 dias (fuente base, ADR 0004).

    Sin costo ni API key. ``query`` ya debe venir compuesta por el llamador
    (p.ej. ``'"Nombre Participante" AND "Empresa"'``, formato que exige el ADR).
    """
    q = (query or "").strip()
    if not q:
        return []

    try:
        resp = requests.get(
            GDELT_SEARCH_URL,
            params={
                "query": q,
                "mode": "artlist",
                "format": "json",
                "timespan": "30d",
                "maxrecords": max(1, min(limite, 250)),
            },
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise ProveedorNoticiasError(f"Error al consultar GDELT: {e}") from e

    if not isinstance(data, dict):
        raise ProveedorNoticiasError(
            "Forma de respuesta inesperada de GDELT (se esperaba un objeto)"
        )
    return list(data.get("articles") or [])


def search_newsapi_articles(query: str, *, limite: int = 10) -> list[dict[str, Any]]:
    """Busca articulos en NewsAPI.org (conector secundario configurable del ADR 0004).

    Requiere ``NEWS_API_KEY`` en el entorno; sin ella no hay suscripcion que
    consultar y se marca como error, no como lista vacia silenciosa.
    """
    q = (query or "").strip()
    if not q:
        return []

    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        raise ProveedorNoticiasError("Falta NEWS_API_KEY para consultar NewsAPI")

    try:
        resp = requests.get(
            NEWSAPI_SEARCH_URL,
            params={"q": q, "pageSize": max(1, min(limite, 100))},
            headers={"X-Api-Key": api_key},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise ProveedorNoticiasError(f"Error al consultar NewsAPI: {e}") from e

    if not isinstance(data, dict):
        raise ProveedorNoticiasError(
            "Forma de respuesta inesperada de NewsAPI (se esperaba un objeto)"
        )
    return list(data.get("articles") or [])
