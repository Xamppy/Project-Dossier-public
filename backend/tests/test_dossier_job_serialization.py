"""S5.10 · BE4/BE7: el job expone `progress` aparte de `result` y el cierre fusiona.

Sin base de datos: ``serialize_job`` y la fusión del resultado final operan sobre
el objeto del job en memoria.
"""
from __future__ import annotations

import uuid

from dossier.db.models import DossierGenerationJob
from dossier.schemas.dossier_generation_job import DossierGenerationJobResponse
from dossier.services import dossier_progress_model as m
from dossier.services.dossier_generation_job_service import serialize_job
from dossier.services.dossier_job_progress import merge_result_payload

AHORA = "2026-10-15T12:00:00+00:00"


def _progreso():
    p = m.new_progress()
    m.add_scope(p, m.person_scope("person:0", "Ana Prueba", "pdl"))
    m.bump_revision(p)
    m.update_entity(p, "person:0", "person.pdl_enrich", "running", now=AHORA)
    return p


def _job(payload, status="running"):
    return DossierGenerationJob(
        id=uuid.uuid4(), status=status, job_type="person_manual", result_payload=payload,
        credits_estimated=1, credits_consumed=0,
    )


def test_mientras_corre_el_resultado_es_nulo_y_el_progreso_va_aparte():
    datos = serialize_job(_job({"_progress": _progreso()}))

    assert datos["result"] is None
    assert datos["progress"]["scopes"][0]["scope_id"] == "person:0"


def test_al_terminar_el_resultado_no_lleva_la_clave_interna():
    datos = serialize_job(_job({"saved_dossier": {"id": "d1"}, "_progress": _progreso()}, status="completed"))

    assert datos["result"] == {"saved_dossier": {"id": "d1"}}
    assert "_progress" not in datos["result"]
    assert datos["progress"]["revision"] == 2


def test_jobs_antiguos_sin_progreso_siguen_igual():
    datos = serialize_job(_job({"saved_dossier": {"id": "d1"}}, status="completed"))

    assert datos["result"] == {"saved_dossier": {"id": "d1"}}
    assert datos["progress"] is None
    assert serialize_job(_job(None))["result"] is None


def test_el_esquema_de_respuesta_acepta_progress_y_su_ausencia():
    con = DossierGenerationJobResponse(**serialize_job(_job({"_progress": _progreso()})))
    sin = DossierGenerationJobResponse(**{k: v for k, v in serialize_job(_job(None)).items() if k != "progress"})

    assert con.progress["schema_version"] == 1
    assert sin.progress is None


def test_fusionar_el_resultado_conserva_y_cierra_el_progreso():
    final = merge_result_payload({"saved_dossier": {"id": "d1"}}, {"_progress": _progreso()}, "completed")

    assert final["saved_dossier"] == {"id": "d1"}
    estados = {e["stage_id"]: (e["status"], e["reason_code"]) for e in final["_progress"]["scopes"][0]["stages"]}
    assert estados["person.pdl_enrich"] == ("failed", "interrupted")
    assert estados["person.persist"] == ("skipped", "not_reached")


def test_fusionar_sin_progreso_devuelve_el_resultado_tal_cual():
    assert merge_result_payload({"a": 1}, None, "completed") == {"a": 1}
    assert merge_result_payload(None, None, "failed") is None
    assert merge_result_payload(None, {"_progress": _progreso()}, "cancelled")["_progress"]["revision"] == 3
