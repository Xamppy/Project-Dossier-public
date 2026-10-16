"""S5.10 · BE2, BE6 y §4 de la política: volumen, concurrencia, latencia y un proveedor lento.

La latencia (BE2) se mide de punta a punta en un solo proceso: desde la llamada
al observador hasta que el generador del stream SSE entrega el frame.
"""
from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.models import DossierGenerationJob
from dossier.services import dossier_progress_events as bus
from dossier.services import dossier_progress_model as m
from dossier.services.dossier_generation_job_service import serialize_job
from dossier.services.dossier_job_progress import JobProgress, SqlProgressStore
from dossier.services.dossier_progress_stream import stream_job_events

LIMITE_LATENCIA_S = 0.5


def test_muchos_jobs_concurrentes_no_mezclan_eventos_ni_repiten_revisiones(progreso):
    jobs = [progreso.job() for _ in range(30)]
    for job in jobs:
        job.declare([m.corporate_scope("corporate:0", "Acme")])

    def trabajar(job):
        s = job.scope("corporate:0")
        for agente in m.CORPORATE_AGENTS:
            s.agent(agente, "running")
            s.agent(agente, "completed")

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(trabajar, jobs))

    for job in jobs:
        revisiones = [d["revision"] for d in progreso.de("agent_progress") if d["job_id"] == str(job.job_id)]
        assert revisiones == list(range(2, 12))
        assert progreso.guardado(job.job_id)["revision"] == 11


def test_con_mas_eventos_que_el_buffer_del_bus_el_snapshot_sigue_completo(progreso):
    job = progreso.job()
    job._publish = bus.publish_if_changed
    scopes = [m.person_scope(f"person:{i}", f"Persona {i}", "pdl") for i in range(15)]
    job.declare(scopes)
    try:
        for s in scopes:
            for etapa in m.PERSON_STAGES["pdl"]:
                job.scope(s["scope_id"]).stage(etapa, "running")
                job.scope(s["scope_id"]).stage(etapa, "completed")

        assert len(bus.events_since(job.job_id, 0)) <= 200, "el buffer en memoria es acotado"
        guardado = progreso.guardado(job.job_id)
        assert guardado["revision"] == 1 + 15 * 9 * 2
        assert all(e["status"] == "completed" for s in guardado["scopes"] for e in s["stages"])
    finally:
        bus.forget(job.job_id)


def test_un_proveedor_lento_no_retrasa_los_eventos_de_los_demas(progreso, monkeypatch):
    import dossier.llm.text_generate as llm
    import dossier.services.corporate_registry_context as ctx
    from dossier.eu_registry.agent import ResultadoAgenteEuropeo
    from dossier.graphs.corporate_dossier_graph import run_corporate_dossier_langgraph_detailed
    from dossier.news.agent import ResultadoRecoleccionPrensa

    def prensa_lenta(e, **_):
        time.sleep(0.4)
        return ResultadoRecoleccionPrensa(mentions=[])

    monkeypatch.setattr(ctx, "build_uk_corporate_context_markdown", lambda p: "## UK\n\nok\n")
    monkeypatch.setattr(ctx, "build_us_corporate_context_markdown", lambda p: "## USA\n\nok\n")
    monkeypatch.setattr("dossier.eu_registry.agent.run_eu_registry_agent", lambda e, **_: ResultadoAgenteEuropeo())
    monkeypatch.setattr("dossier.news.agent.collect_press_mentions", prensa_lenta)
    monkeypatch.setattr(llm, "generate_text_with_llm", lambda user, system_instruction=None: "# ok")
    momentos: dict[str, float] = {}
    job = progreso.job()
    original = job._publish

    def publicar(job_id, evento, datos):
        if evento == "agent_progress" and datos["status"] == "completed":
            momentos[datos["agent_name"]] = time.perf_counter()
        original(job_id, evento, datos)

    job._publish = publicar
    job.declare([m.corporate_scope("corporate:0", "Acme")])
    inicio = time.perf_counter()

    run_corporate_dossier_langgraph_detailed(
        tema_reunion="Acme", participantes="Acme", jurisdiction_scope="dual", empresa_objetivo="Acme",
        progress=job.scope("corporate:0"),
    )

    assert momentos["agent_corporate_uk"] - inicio < 0.3, "UK no espera a la prensa"
    assert momentos["agent_news"] - inicio >= 0.4
    assert momentos["synthesize_llm"] > momentos["agent_news"]


def _medir_latencia(job: JobProgress, scopes: list[str]) -> list[float]:
    """Latencias (s) entre cada ``stage()`` y la llegada de su frame al stream."""
    enviados: list[float] = []
    recibidos: list[float] = []
    listo = threading.Event()
    estado = {"id": str(job.job_id), "status": "running"}

    def consumir():
        for frame in stream_job_events(job.job_id, lambda: dict(estado), poll_seconds=5.0, max_seconds=30.0):
            listo.set()
            if "event: stage_progress" in frame:
                recibidos.append(time.perf_counter())
            if "event: job_completed" in frame:
                return

    hilo = threading.Thread(target=consumir)
    hilo.start()
    assert listo.wait(5)
    for scope_id in scopes:
        for etapa in m.PERSON_STAGES["pdl"]:
            for estado_etapa in ("running", "completed"):
                enviados.append(time.perf_counter())
                job.scope(scope_id).stage(etapa, estado_etapa)
                time.sleep(0.005)
    estado["status"] = "completed"
    bus.publish_if_changed(job.job_id, "job_completed", dict(estado))
    hilo.join(10)
    assert len(recibidos) == len(enviados)
    return [r - e for e, r in zip(enviados, recibidos, strict=True)]


def _informe(nombre: str, latencias: list[float]) -> None:
    ordenadas = sorted(latencias)
    p95 = ordenadas[int(len(ordenadas) * 0.95) - 1]
    print(
        f"\nBE2 {nombre}: n={len(latencias)} mediana={statistics.median(latencias) * 1000:.2f} ms "
        f"p95={p95 * 1000:.2f} ms max={max(latencias) * 1000:.2f} ms"
    )


def test_be2_latencia_en_un_proceso_con_almacen_en_memoria(progreso):
    job = progreso.job()
    job._publish = bus.publish_if_changed
    job.declare([m.person_scope("person:0", "Ana", "pdl"), m.person_scope("person:1", "Beto", "pdl")])
    try:
        latencias = _medir_latencia(job, ["person:0", "person:1"])
    finally:
        bus.forget(job.job_id)

    _informe("memoria", latencias)
    assert max(latencias) < LIMITE_LATENCIA_S


@pytest.fixture
def job_en_postgres(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id = conn.execute(
            text("INSERT INTO organizations (name, slug) VALUES ('Org', 'org-estres') RETURNING id")
        ).scalar_one()
        user_id = conn.execute(text("INSERT INTO users (email) VALUES ('e@example.com') RETURNING id")).scalar_one()
    with Session(pg_vacia) as db:
        job = DossierGenerationJob(
            organization_id=org_id, requested_by_user_id=user_id, status="running", job_type="person_manual"
        )
        db.add(job)
        db.commit()
        job_id = job.id
    almacen = SqlProgressStore(lambda: Session(pg_vacia, expire_on_commit=False), serialize_job)
    yield job_id, almacen
    bus.forget(job_id)


def test_be2_latencia_con_postgres_de_prueba(job_en_postgres):
    job_id, almacen = job_en_postgres
    job = JobProgress(job_id, almacen)
    job.declare([m.person_scope("person:0", "Ana", "pdl"), m.person_scope("person:1", "Beto", "pdl")])

    latencias = _medir_latencia(job, ["person:0", "person:1"])

    _informe("postgres", latencias)
    assert max(latencias) < LIMITE_LATENCIA_S


def test_escrituras_concurrentes_en_postgres_no_pierden_cambios(job_en_postgres):
    job_id, almacen = job_en_postgres
    publicados: list[int] = []
    job = JobProgress(job_id, almacen, publish=lambda _j, _e, d: publicados.append(d.get("revision", 0)))
    scopes = [m.person_scope(f"person:{i}", f"Persona {i}", "pdl") for i in range(4)]
    job.declare(scopes)

    def trabajar(scope_id):
        for etapa in m.PERSON_STAGES["pdl"]:
            # Cada hilo con su propio coordinador: el bloqueo de fila es lo que ordena.
            JobProgress(job_id, almacen, publish=lambda *_: None).scope(scope_id).stage(etapa, "completed")

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(trabajar, [s["scope_id"] for s in scopes]))

    with Session(almacen._factory().get_bind()) as db:
        final = db.get(DossierGenerationJob, job_id).result_payload["_progress"]
    assert final["revision"] == 1 + 4 * 9
    revisiones = sorted(e["revision"] for s in final["scopes"] for e in s["stages"])
    assert revisiones == list(range(2, 2 + 4 * 9)), "ninguna revisión repetida ni perdida"
