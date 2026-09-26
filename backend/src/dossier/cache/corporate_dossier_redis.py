"""
Caché Redis para dossiers corporativos (mismo brief público → reutilizar Markdown).

La clave **no** incluye el contexto de organización del cliente: el grafo se invoca con
``descripcion`` neutra y el contexto de org se anexa **después** al recuperar o generar.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from dossier.schemas.dossier_generation import CreateCorporateDossierRequest

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "dossier:corporate:md"
_LOCK_PREFIX = "dossier:corporate:lock"

_redis_singleton: Any = None
_redis_singleton_lock = threading.Lock()


def _redis_url() -> str:
    return (os.getenv("REDIS_URL") or "").strip()


def redis_corporate_cache_available() -> bool:
    if os.getenv("DOSSIER_REDIS_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        return False
    return bool(_redis_url())


def redis_ttl_seconds() -> int:
    ttl = int(os.getenv("DOSSIER_REDIS_TTL_SECONDS", "86400"))
    return max(60, min(ttl, 2592000))


def _redis_log_target(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.hostname or "?"
        port = f":{p.port}" if p.port else ""
        db = p.path or ""
        return f"{host}{port}{db}"
    except Exception:  # noqa: BLE001 - solo para log, nunca debe romper la app
        return "?"


def _normalize_cache_text(s: str) -> str:
    t = (s or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t.casefold()


def dossier_corporate_redis_health() -> dict[str, bool | str]:
    """Resumen sin secretos para diagnóstico (p. ej. GET /health)."""
    if not redis_corporate_cache_available():
        return {"enabled": False, "client_ok": False, "target": ""}
    url = _redis_url()
    c = _client()
    return {
        "enabled": True,
        "client_ok": c is not None,
        "target": _redis_log_target(url),
    }


def warmup_corporate_dossier_redis() -> None:
    """Fuerza conexión+PING al arrancar la API."""
    if not redis_corporate_cache_available():
        logger.info("Redis dossier: desactivado o sin REDIS_URL.")
        return
    if _client() is not None:
        logger.info(
            "Redis dossier: comprobación al arranque OK (%s).",
            _redis_log_target(_redis_url()),
        )


def dossier_redis_shared_client():
    """Cliente Redis singleton (caché corporativa y de persona)."""
    return _client()


def _client():
    global _redis_singleton
    if not redis_corporate_cache_available():
        return None
    if _redis_singleton is not None:
        return _redis_singleton
    with _redis_singleton_lock:
        if _redis_singleton is not None:
            return _redis_singleton
        try:
            from redis import Redis

            url = _redis_url()
            r = Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=5.0,
            )
            r.ping()
            _redis_singleton = r
            logger.info("Redis dossier: cliente listo (%s).", _redis_log_target(url))
            return r
        except Exception as e:  # noqa: BLE001 - Redis opcional: cualquier fallo degrada a sin cache
            logger.warning(
                "Redis dossier: no se pudo conectar (%s). Reintento en el siguiente uso.",
                e,
            )
            return None


def _pipeline_version() -> str:
    return (os.getenv("DOSSIER_CACHE_PIPELINE_VERSION") or "1").strip()


def build_corporate_cache_key_hash(
    *,
    body: CreateCorporateDossierRequest,
    participantes: str,
    jurisdiction_scope: str,
    output_language: str = "es",
) -> str:
    """Hash estable para POST /dossiers/corporate/generate."""
    from dossier.services.output_language import normalize_output_language

    resolution = body.resolution.model_dump(mode="json") if body.resolution is not None else None
    payload: dict[str, Any] = {
        "depth": body.depth,
        "jurisdiction_scope": jurisdiction_scope,
        "participantes": _normalize_cache_text(participantes),
        "pipeline_version": _pipeline_version(),
        "resolution": resolution,
        "subject_email": (body.subject_email or "").strip().lower() or None,
        "subject_query": _normalize_cache_text(body.subject_query),
        "output_language": normalize_output_language(output_language or body.output_language),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_corporate_langgraph_cache_key_hash(
    *,
    participantes: str,
    jurisdiction_scope: str,
    depth: str = "standard",
    output_language: str = "es",
) -> str:
    """Hash estable para generación corporativa desde calendario/automatización."""
    from dossier.services.output_language import normalize_output_language

    payload: dict[str, Any] = {
        "depth": depth,
        "jurisdiction_scope": jurisdiction_scope,
        "participantes": _normalize_cache_text(participantes),
        "pipeline_version": _pipeline_version(),
        "resolution": None,
        "subject_email": None,
        "subject_query": None,
        "source": "calendar",
        "output_language": normalize_output_language(output_language),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def corporate_cache_redis_key(key_hash: str) -> str:
    return f"{_CACHE_PREFIX}:{key_hash}"


def cached_until_from_now() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=redis_ttl_seconds())


def _cache_key(key_hash: str) -> str:
    return corporate_cache_redis_key(key_hash)


def _lock_key(key_hash: str) -> str:
    return f"{_LOCK_PREFIX}:{key_hash}"


def get_corporate_cached_markdown(key_hash: str) -> str | None:
    r = _client()
    if r is None:
        return None
    try:
        raw = r.get(_cache_key(key_hash))
        if not raw:
            return None
        return str(raw)
    except Exception as e:  # noqa: BLE001 - Redis opcional: cualquier fallo degrada a sin cache
        logger.warning("Redis GET dossier corporativo: %s", e)
        return None


def set_corporate_cached_markdown(key_hash: str, markdown: str) -> None:
    r = _client()
    if r is None:
        return
    try:
        r.setex(_cache_key(key_hash), redis_ttl_seconds(), markdown)
    except Exception as e:  # noqa: BLE001 - Redis opcional: cualquier fallo degrada a sin cache
        logger.warning("Redis SETEX dossier corporativo: %s", e)


def run_with_corporate_cache_lock(key_hash: str, fn) -> Any:
    r = _client()
    if r is None:
        return fn()
    try:
        with r.lock(_lock_key(key_hash), timeout=300, blocking_timeout=120):
            return fn()
    except Exception as e:  # noqa: BLE001 - Redis opcional: cualquier fallo degrada a sin lock
        logger.warning("Redis lock dossier corporativo: %s. Ejecutando sin lock.", e)
        return fn()


def delete_dossier_redis_cache(redis_key: str) -> bool:
    """Elimina una clave Redis de caché (corporativa o persona) por clave completa."""
    key = (redis_key or "").strip()
    if not key:
        return False
    r = _client()
    if r is None:
        return False
    try:
        deleted = int(r.delete(key))
        if deleted:
            logger.debug("Redis DELETE dossier cache: %s", key)
        return deleted > 0
    except Exception as e:  # noqa: BLE001 - Redis opcional: cualquier fallo degrada a sin cache
        logger.warning("Redis DELETE dossier cache (%s): %s", key, e)
        return False
