"""Progreso por scopes de un job de generación (S5.10, ADR 0009).

Funciones puras sobre el dict que se guarda en ``result_payload["_progress"]``:
sin base de datos ni bus, para probar las reglas por separado. El coordinador
(``dossier_job_progress.py``) las aplica dentro de una transacción.

Un scope es una ejecución dentro del job: ``corporate:N`` (agentes del grafo
corporativo) o ``person:N`` (etapas de la investigación de una persona).
Las listas mantienen el orden del catálogo: JSONB no conserva el de las claves.
"""
from __future__ import annotations

import copy
import re
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
PREVIEW_MAX_BYTES = 32 * 1024

CORPORATE_AGENTS: tuple[str, ...] = (
    "agent_corporate_uk",
    "agent_corporate_usa",
    "agent_corporate_eu",
    "agent_news",
    "synthesize_llm",
)

# El orden es el de ejecución real; con DEEPSEEK_PERSON_WEB_ALWAYS el análisis
# contextual corre antes de la síntesis de perfiles, como hoy.
PERSON_STAGES: dict[str, tuple[str, ...]] = {
    "pdl": (
        "person.cache_lookup",
        "person.pdl_enrich",
        "person.pdl_search",
        "person.profile_normalization",
        "person.context_analysis",
        "person.profile_synthesis",
        "person.markdown_fallback",
        "person.report_finalize",
        "person.persist",
    ),
    # Web pública: una llamada a DeepSeek sin buscador; no hay etapas de búsqueda.
    "gemini_web": (
        "person.cache_lookup",
        "person.context_analysis",
        "person.report_finalize",
        "person.persist",
    ),
}

STATUSES = frozenset({"pending", "running", "completed", "failed", "skipped", "cancelled"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "skipped", "cancelled"})

REASON_CODES: dict[str, frozenset[str]] = {
    "pending": frozenset(),
    "running": frozenset(),
    "cancelled": frozenset(),
    "completed": frozenset({"no_matches", "cache_hit", "cache_miss"}),
    "skipped": frozenset(
        {
            "out_of_scope",
            "no_target_company",
            "plan_not_included",
            "cache_hit",
            "cache_unavailable",
            "force_refresh",
            "mode_not_applicable",
            "sufficient_profiles",
            "no_profiles",
            "configuration_missing",
            "feature_disabled",
            "insufficient_input",
            "not_required",
            "upstream_auth_failed",
            "not_reached",
        }
    ),
    "failed": frozenset(
        {
            "provider_error",
            "provider_timeout",
            "provider_quota",
            "provider_rate_limit",
            "upstream_auth_failed",
            "structured_output_invalid",
            "no_valid_report",
            "persistence_error",
            "interrupted",
        }
    ),
}

ENTITY_META = frozenset({"attempts", "used_in_final", "recovered_by", "dossier_id", "dossier_status"})
SCOPE_FIELDS = frozenset({"origin", "profiles_count", "dossier"})
ORIGINS = frozenset({"generated", "redis_cache"})
BASES = frozenset({"provider_records", "model_only", "mixed", "unknown"})

# Sección corporativa → agente que la produce. UK y USA no tienen vista previa:
# sus bloques mezclan datos del registro con diagnósticos internos (ADR 0009).
CORPORATE_SECTIONS = {
    "corporate_eu": "agent_corporate_eu",
    "news": "agent_news",
    "synthesis": "synthesize_llm",
}
PERSON_MARKDOWN_SECTIONS = frozenset({"person_context_report", "person_report"})

MAX_PROFILES = 5
MAX_PROFILE_URLS = 3
MAX_FIELD_CHARS = 200
MAX_URL_CHARS = 500

_SCOPE_ID = re.compile(r"^(corporate|person):\d{1,3}$")
_BLOCK_START = re.compile(r"^(#|- |\* |\d+\. )")


# --- estructura --------------------------------------------------------------


def new_progress() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "revision": 0, "scopes": []}


def _entity(field: str, entity_id: str) -> dict[str, Any]:
    return {field: entity_id, "status": "pending", "reason_code": None, "revision": 0, "timestamp": None}


def _check_scope_id(scope_id: str, kind: str) -> None:
    m = _SCOPE_ID.match(scope_id or "")
    if m is None or m.group(1) != kind:
        raise ValueError(f"scope_id inválido para {kind}: {scope_id!r}")


def corporate_scope(scope_id: str, label: str) -> dict[str, Any]:
    _check_scope_id(scope_id, "corporate")
    return {
        "scope_id": scope_id,
        "kind": "corporate",
        "label": label,
        "origin": None,
        "agents": [_entity("agent_name", a) for a in CORPORATE_AGENTS],
        "partial_results": [],
        "dossier": None,
    }


def person_scope(scope_id: str, label: str, research_source: str) -> dict[str, Any]:
    _check_scope_id(scope_id, "person")
    if research_source not in PERSON_STAGES:
        raise ValueError(f"modalidad de investigación desconocida: {research_source!r}")
    return {
        "scope_id": scope_id,
        "kind": "person",
        "label": label,
        "research_source": research_source,
        "live_web_search": False,
        "origin": None,
        "profiles_count": None,
        "stages": [_entity("stage_id", s) for s in PERSON_STAGES[research_source]],
        "partial_results": [],
        "dossier": None,
    }


def find_scope(progress: dict[str, Any] | None, scope_id: str) -> dict[str, Any] | None:
    if not isinstance(progress, dict):
        return None
    return next((s for s in progress.get("scopes") or [] if s.get("scope_id") == scope_id), None)


def _scope(progress: dict[str, Any], scope_id: str) -> dict[str, Any]:
    scope = find_scope(progress, scope_id)
    if scope is None:
        raise ValueError(f"scope no declarado: {scope_id!r}")
    return scope


def add_scope(progress: dict[str, Any], scope: dict[str, Any]) -> bool:
    """Agrega el scope si no existía. No sube la revisión: lo hace quien declara."""
    if find_scope(progress, scope["scope_id"]) is not None:
        return False
    progress["scopes"].append(copy.deepcopy(scope))
    return True


def bump_revision(progress: dict[str, Any]) -> int:
    progress["revision"] = int(progress.get("revision") or 0) + 1
    return progress["revision"]


# --- transiciones -------------------------------------------------------------


def _entities(scope: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    if scope["kind"] == "corporate":
        return scope["agents"], "agent_name"
    return scope["stages"], "stage_id"


def update_entity(
    progress: dict[str, Any],
    scope_id: str,
    entity_id: str,
    status: str,
    *,
    reason_code: str | None = None,
    meta: dict[str, Any] | None = None,
    now: str,
) -> dict[str, Any] | None:
    """Aplica un cambio de agente o etapa. Devuelve la entidad nueva o ``None`` si no cambió.

    Un terminal no pasa a otro estado; sí puede ganar metadatos (``used_in_final``,
    ``recovered_by``…). Lo que no está en el catálogo del scope es un error.
    """
    scope = _scope(progress, scope_id)
    entities, field = _entities(scope)
    entity = next((e for e in entities if e[field] == entity_id), None)
    if entity is None:
        raise ValueError(f"{entity_id!r} no pertenece al catálogo de {scope_id!r}")
    if status not in STATUSES:
        raise ValueError(f"estado desconocido: {status!r}")
    if reason_code is not None and reason_code not in REASON_CODES[status]:
        raise ValueError(f"motivo {reason_code!r} no válido para {status!r}")
    meta = dict(meta or {})
    extra = set(meta) - ENTITY_META
    if extra:
        raise ValueError(f"metadatos no permitidos: {sorted(extra)}")

    current = entity["status"]
    if current in TERMINAL_STATUSES and status != current:
        return None
    if status == current:
        nuevos = {k: v for k, v in meta.items() if entity.get(k) != v}
        motivo_nuevo = reason_code is not None and reason_code != entity.get("reason_code")
        if not nuevos and not motivo_nuevo:
            return None
        meta = nuevos
        if reason_code is None:
            reason_code = entity.get("reason_code")

    entity["status"] = status
    entity["reason_code"] = reason_code
    entity.update(meta)
    entity["timestamp"] = now
    entity["revision"] = bump_revision(progress)
    return copy.deepcopy(entity)


def put_partial(progress: dict[str, Any], scope_id: str, partial: dict[str, Any] | None) -> dict[str, Any] | None:
    """Guarda la vista previa de una sección, reemplazando la anterior de esa sección."""
    if partial is None:
        return None
    scope = _scope(progress, scope_id)
    section = str(partial.get("section") or "")
    if scope["kind"] == "corporate":
        if CORPORATE_SECTIONS.get(section) != partial.get("agent_name"):
            raise ValueError(f"sección corporativa inválida: {section!r}")
    else:
        stages = {e["stage_id"] for e in scope["stages"]}
        if partial.get("stage_id") not in stages:
            raise ValueError(f"etapa {partial.get('stage_id')!r} fuera del catálogo de {scope_id!r}")
        if section not in PERSON_MARKDOWN_SECTIONS | {"person_profiles"}:
            raise ValueError(f"sección personal inválida: {section!r}")
    stored = copy.deepcopy(partial)
    stored["revision"] = bump_revision(progress)
    scope["partial_results"] = [p for p in scope["partial_results"] if p.get("section") != section]
    scope["partial_results"].append(stored)
    return copy.deepcopy(stored)


def set_scope_fields(progress: dict[str, Any], scope_id: str, fields: dict[str, Any]) -> bool:
    scope = _scope(progress, scope_id)
    extra = set(fields) - SCOPE_FIELDS
    if extra:
        raise ValueError(f"campos de scope no permitidos: {sorted(extra)}")
    if "origin" in fields and fields["origin"] not in ORIGINS | {None}:
        raise ValueError(f"origen inválido: {fields['origin']!r}")
    cuenta = fields.get("profiles_count")
    if cuenta is not None and (not isinstance(cuenta, int) or cuenta < 0):
        raise ValueError("profiles_count debe ser un entero no negativo")
    cambios = {k: v for k, v in fields.items() if scope.get(k) != v}
    if not cambios:
        return False
    scope.update(copy.deepcopy(cambios))
    bump_revision(progress)
    return True


def finalize_progress(progress: dict[str, Any] | None, job_status: str, *, now: str) -> dict[str, Any] | None:
    """Cierra el progreso al terminar el job, sin mutar el original.

    ``pending`` → ``skipped`` (no se llegó); ``running`` → ``failed`` (interrumpida),
    o ``cancelled`` si el job se canceló. Los terminales no se tocan.
    """
    if not isinstance(progress, dict):
        return None
    cerrado = copy.deepcopy(progress)
    pendientes: list[dict[str, Any]] = []
    for scope in cerrado.get("scopes") or []:
        entities, _ = _entities(scope)
        for e in entities:
            if e["status"] == "pending":
                e["status"], e["reason_code"] = "skipped", "not_reached"
                pendientes.append(e)
            elif e["status"] == "running":
                if job_status == "cancelled":
                    e["status"], e["reason_code"] = "cancelled", None
                else:
                    e["status"], e["reason_code"] = "failed", "interrupted"
                pendientes.append(e)
    if pendientes:
        revision = bump_revision(cerrado)
        for e in pendientes:
            e["revision"] = revision
            e["timestamp"] = now
    return cerrado


# --- vistas previas -----------------------------------------------------------


def _valid_text(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t or t.startswith("# Error"):
        return None
    return t


def _blocks(text: str) -> list[str]:
    """Bloques completos: un elemento de lista, un encabezado o un párrafo."""
    bloques: list[list[str]] = []
    previa_en_blanco = False
    for linea in text.split("\n"):
        nuevo = _BLOCK_START.match(linea) is not None or (previa_en_blanco and linea.strip() != "")
        if bloques and nuevo:
            bloques.append([linea])
        elif bloques:
            bloques[-1].append(linea)
        else:
            bloques.append([linea])
        previa_en_blanco = linea.strip() == ""
    return ["\n".join(b) for b in bloques]


def markdown_preview(text: str | None, *, limit: int = PREVIEW_MAX_BYTES) -> tuple[str, bool] | None:
    """Texto acotado a ``limit`` bytes UTF-8, cortado entre bloques completos.

    Devuelve ``(contenido, truncado)`` o ``None`` si no hay texto mostrable.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    texto = text.strip()
    if len(texto.encode("utf-8")) <= limit:
        return texto, False
    salida = ""
    for bloque in _blocks(texto):
        candidato = f"{salida}\n{bloque}" if salida else bloque
        if len(candidato.encode("utf-8")) > limit:
            break
        salida = candidato
    if not salida.strip():
        # Un único bloque más largo que el límite: se corta en un carácter completo.
        salida = texto.encode("utf-8")[:limit].decode("utf-8", errors="ignore")
    return salida.rstrip(), True


def safe_profile_url(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u or len(u) > MAX_URL_CHARS or any(c.isspace() or ord(c) < 32 for c in u):
        return None
    try:
        partes = urlsplit(u)
    except ValueError:
        return None
    if partes.scheme != "https" or not partes.hostname or partes.username or partes.password:
        return None
    return u


def _short_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    t = " ".join(value.split())
    return t[:MAX_FIELD_CHARS] or None


def person_profiles_data(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Proyección pública de los perfiles PDL seleccionados (ADR 0009).

    Solo nombre, cargo, empresa y hasta tres URLs ``https``: nada de ``data`` crudo,
    IDs del proveedor, correos, teléfonos ni parámetros de búsqueda.
    """
    salida = []
    for i, perfil in enumerate(profiles[:MAX_PROFILES]):
        perfil = perfil if isinstance(perfil, dict) else {}
        crudo = perfil.get("data")
        data: dict[str, Any] = crudo if isinstance(crudo, dict) else {}
        urls: list[str] = []
        for u in perfil.get("linkedin_urls") or []:
            segura = safe_profile_url(u)
            if segura and segura not in urls:
                urls.append(segura)
            if len(urls) >= MAX_PROFILE_URLS:
                break
        salida.append(
            {
                "record_key": f"profile:{i}",
                "full_name": _short_text(data.get("full_name")),
                "job_title": _short_text(data.get("job_title")),
                "company": _short_text(data.get("job_company_name")),
                "profile_urls": urls,
            }
        )
    return {"profiles": salida, "profiles_count": len(profiles)}


def _check_origin(origin: str) -> None:
    if origin not in ORIGINS:
        raise ValueError(f"origen inválido: {origin!r}")


def corporate_partial(
    agent_name: str, section: str, content: str | None, *, origin: str = "generated"
) -> dict[str, Any] | None:
    if CORPORATE_SECTIONS.get(section) != agent_name:
        raise ValueError(f"sin vista previa pública para {agent_name!r}/{section!r}")
    _check_origin(origin)
    preview = markdown_preview(_valid_text(content))
    if preview is None:
        return None
    contenido, truncado = preview
    return {
        "agent_name": agent_name,
        "section": section,
        "format": "markdown",
        "content": contenido,
        "origin": origin,
        "provisional": True,
        "truncated": truncado,
    }


def person_partial_profiles(
    stage_id: str, profiles: list[dict[str, Any]], *, origin: str
) -> dict[str, Any] | None:
    _check_origin(origin)
    if not profiles:
        return None
    return {
        "stage_id": stage_id,
        "section": "person_profiles",
        "format": "person_profiles",
        "data": person_profiles_data(profiles),
        "provenance": {"basis": "provider_records", "sources": ["pdl"], "live_web_search": False},
        "origin": origin,
        "provisional": True,
        "truncated": False,
    }


def person_partial_markdown(
    stage_id: str,
    section: str,
    content: str | None,
    *,
    basis: str,
    sources: list[str],
    origin: str,
) -> dict[str, Any] | None:
    if section not in PERSON_MARKDOWN_SECTIONS:
        raise ValueError(f"sección personal inválida: {section!r}")
    if basis not in BASES:
        raise ValueError(f"procedencia inválida: {basis!r}")
    _check_origin(origin)
    preview = markdown_preview(_valid_text(content))
    if preview is None:
        return None
    contenido, truncado = preview
    return {
        "stage_id": stage_id,
        "section": section,
        "format": "markdown",
        "content": contenido,
        "provenance": {"basis": basis, "sources": list(sources), "live_web_search": False},
        "origin": origin,
        "provisional": True,
        "truncated": truncado,
    }
