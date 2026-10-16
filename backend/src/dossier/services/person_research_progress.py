"""Etapas de caché y guardado de una persona, comunes a Personas y Calendario (S5.10).

``run_person_research`` informa la investigación; estas funciones, lo que hacen
los dos wrappers que la rodean: consultar la caché Redis y guardar el dossier.
"""
from __future__ import annotations

from typing import Any

from dossier.llm.common import normalize_person_report_text
from dossier.services.dossier_progress_model import (
    PERSON_STAGES,
    SCHEMA_VERSION,
    person_partial_markdown,
)

CACHE_LOOKUP = "person.cache_lookup"
PERSIST = "person.persist"
_FUERA_DE_LA_INVESTIGACION = {CACHE_LOOKUP, "person.report_finalize", PERSIST}


def report_cache_hit(progress: Any, *, research_source: str, cached_payload: dict[str, Any]) -> None:
    """Un acierto de caché: no se ejecutó nada nuevo, así que la investigación queda omitida.

    La caché no guarda perfiles (solo su cantidad): no se publica un parcial de
    perfiles, y la procedencia del informe es desconocida.
    """
    for stage in PERSON_STAGES.get(research_source, ()):
        if stage not in _FUERA_DE_LA_INVESTIGACION:
            progress.stage(stage, "skipped", "cache_hit")
    cuenta = cached_payload.get("profiles_count")
    progress.fields(origin="redis_cache", profiles_count=int(cuenta) if isinstance(cuenta, int) else None)
    informe = normalize_person_report_text(str(cached_payload.get("markdown") or ""))
    if informe and not informe.lstrip().startswith("# Error"):
        progress.partial(
            person_partial_markdown(
                "person.report_finalize",
                "person_report",
                informe,
                basis="unknown",
                sources=[],
                origin="redis_cache",
            )
        )
        progress.stage("person.report_finalize", "completed")
    else:
        progress.stage("person.report_finalize", "skipped", "no_content")


def report_generated(progress: Any, result: dict[str, Any]) -> None:
    fa = result.get("filters_applied")
    cuenta = fa.get("profiles_count") if isinstance(fa, dict) else None
    if not isinstance(cuenta, int):
        cuenta = len(result.get("profiles") or [])
    progress.fields(origin="generated", profiles_count=cuenta)


def scope_copy(progress: Any) -> dict[str, Any] | None:
    """Copia del scope para ``dossier_data["_progress"]`` del dossier que se guarda."""
    scope = progress.snapshot()
    if not scope:
        return None
    return {"schema_version": SCHEMA_VERSION, "job_id": progress.job_id, "scope": scope}


def report_persisted(progress: Any, *, dossier_id: str, dossier_status: str) -> None:
    """Un registro ``failed`` existe pero no es un informe: ``persist`` queda fallida."""
    if dossier_status == "complete":
        progress.stage(PERSIST, "completed", dossier_id=dossier_id, dossier_status=dossier_status)
    else:
        progress.stage(
            PERSIST, "failed", "no_valid_report", dossier_id=dossier_id, dossier_status=dossier_status
        )
    progress.fields(dossier={"id": dossier_id, "status": dossier_status})
