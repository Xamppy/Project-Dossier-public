"""Caché Redis para investigación de persona (misma org + filtros → mismo informe)."""
from __future__ import annotations

import json
import logging
from typing import Any

from dossier.cache.corporate_dossier_redis import (
    dossier_redis_shared_client,
    redis_corporate_cache_available,
    redis_ttl_seconds,
)

logger = logging.getLogger(__name__)

_PERSON_PAYLOAD_PREFIX = "dossier:person:payload"
_PERSON_LOCK_PREFIX = "dossier:person:lock"


def redis_person_cache_available() -> bool:
    return redis_corporate_cache_available()


def person_cache_redis_key(fingerprint_hex: str) -> str:
    return f"{_PERSON_PAYLOAD_PREFIX}:{fingerprint_hex}"


def _payload_key(fingerprint_hex: str) -> str:
    return person_cache_redis_key(fingerprint_hex)


def _person_lock_key(fingerprint_hex: str) -> str:
    return f"{_PERSON_LOCK_PREFIX}:{fingerprint_hex}"


def get_person_cached_payload(fingerprint_hex: str) -> dict[str, Any] | None:
    r = dossier_redis_shared_client()
    if r is None:
        return None
    try:
        raw = r.get(_payload_key(fingerprint_hex))
        if not raw:
            return None
        data = json.loads(str(raw))
        if not isinstance(data, dict) or not data.get("markdown"):
            return None
        return data
    except Exception as e:  # noqa: BLE001 - Redis opcional: cualquier fallo degrada a sin cache
        logger.warning("Redis GET dossier persona: %s", e)
        return None


def set_person_cached_payload(fingerprint_hex: str, payload: dict[str, Any]) -> None:
    r = dossier_redis_shared_client()
    if r is None:
        return
    try:
        r.setex(
            _payload_key(fingerprint_hex),
            redis_ttl_seconds(),
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception as e:  # noqa: BLE001 - Redis opcional: cualquier fallo degrada a sin cache
        logger.warning("Redis SETEX dossier persona: %s", e)


def run_with_person_cache_lock(fingerprint_hex: str, fn) -> Any:
    r = dossier_redis_shared_client()
    if r is None:
        return fn()
    try:
        with r.lock(_person_lock_key(fingerprint_hex), timeout=300, blocking_timeout=120):
            return fn()
    except Exception as e:  # noqa: BLE001 - Redis opcional: cualquier fallo degrada a sin lock
        logger.warning("Redis lock dossier persona: %s. Ejecutando sin lock.", e)
        return fn()
