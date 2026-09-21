"""Tests - S4.8: bus de eventos en memoria del canal SSE de un job."""
from __future__ import annotations

import uuid

from dossier.services.dossier_progress_events import (
    events_since,
    forget,
    publish_if_changed,
)


def test_publica_y_asigna_ids_incrementales():
    job_id = uuid.uuid4()
    seq1 = publish_if_changed(job_id, "job_status", {"status": "queued"})
    seq2 = publish_if_changed(job_id, "job_status", {"status": "running"})
    assert seq1 == 1
    assert seq2 == 2


def test_no_publica_si_el_evento_es_identico_al_ultimo():
    job_id = uuid.uuid4()
    publish_if_changed(job_id, "job_status", {"status": "running"})
    repetido = publish_if_changed(job_id, "job_status", {"status": "running"})
    assert repetido is None


def test_events_since_filtra_por_id_y_mantiene_orden():
    job_id = uuid.uuid4()
    publish_if_changed(job_id, "job_status", {"status": "queued"})
    publish_if_changed(job_id, "job_status", {"status": "running"})
    publish_if_changed(job_id, "job_completed", {"status": "completed"})

    pendientes = events_since(job_id, 1)
    assert [e[0] for e in pendientes] == [2, 3]
    assert pendientes[-1][1] == "job_completed"


def test_events_since_de_job_desconocido_es_vacio():
    assert events_since(uuid.uuid4(), 0) == []


def test_forget_limpia_el_job():
    job_id = uuid.uuid4()
    publish_if_changed(job_id, "job_status", {"status": "queued"})
    forget(job_id)
    assert events_since(job_id, 0) == []
    # Vuelve a numerar desde 1: es una limpieza real, no un placeholder.
    assert publish_if_changed(job_id, "job_status", {"status": "queued"}) == 1


def test_jobs_distintos_no_se_mezclan():
    job_a, job_b = uuid.uuid4(), uuid.uuid4()
    publish_if_changed(job_a, "job_status", {"status": "queued"})
    publish_if_changed(job_b, "job_status", {"status": "running"})
    assert [e[1:] for e in events_since(job_a, 0)] == [("job_status", {"status": "queued"})]
    assert [e[1:] for e in events_since(job_b, 0)] == [("job_status", {"status": "running"})]
