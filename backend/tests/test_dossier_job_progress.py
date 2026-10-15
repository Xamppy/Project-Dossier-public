"""S5.10 · Coordinador de progreso por job (ADR 0009).

Usa un almacén en memoria (fixture ``progreso``): aquí se prueba el orden
guardar → publicar, la forma de los eventos y que un job terminado no revive.
La versión con Postgres está en tests/integration/test_person_job_progress.py.
"""
from __future__ import annotations

import threading
import uuid

from dossier.services import dossier_job_progress as djp
from dossier.services import dossier_progress_model as m


def test_declarar_scopes_publica_un_job_status_con_el_catalogo(progreso):
    job = progreso.job()

    job.declare([m.corporate_scope("corporate:0", "Acme"), m.person_scope("person:0", "Ana", "pdl")])

    assert [e for e, _ in progreso.eventos] == ["job_status"]
    snapshot = progreso.eventos[0][1]
    assert [s["scope_id"] for s in snapshot["progress"]["scopes"]] == ["corporate:0", "person:0"]
    assert snapshot["progress"]["schema_version"] == 1


def test_redeclarar_el_mismo_scope_no_publica_nada(progreso):
    job = progreso.job()
    job.declare([m.corporate_scope("corporate:0", "Acme")])

    job.declare([m.corporate_scope("corporate:0", "Acme")])

    assert len(progreso.eventos) == 1


def test_agent_progress_tiene_la_forma_del_contrato(progreso):
    job = progreso.job()
    job.declare([m.corporate_scope("corporate:0", "Acme")])

    job.scope("corporate:0").agent("agent_corporate_eu", "running")

    evento, datos = progreso.eventos[-1]
    assert evento == "agent_progress"
    assert set(datos) == {
        "schema_version", "job_id", "scope_id", "revision", "agent_name", "status", "timestamp", "reason_code"
    }
    assert datos["job_id"] == str(job.job_id)
    assert (datos["scope_id"], datos["agent_name"], datos["status"]) == ("corporate:0", "agent_corporate_eu", "running")
    assert datos["revision"] == 2  # 1 = declaración
    assert "dossier_id" not in datos, "el job ID ya no viaja como dossier_id (formato de S4.9)"


def test_stage_progress_lleva_modalidad_y_metadatos(progreso):
    job = progreso.job()
    job.declare([m.person_scope("person:0", "Ana", "pdl")])

    job.scope("person:0").stage(
        "person.pdl_enrich", "completed", "no_matches", attempts={"total": 3, "failed": 1}
    )

    evento, datos = progreso.eventos[-1]
    assert evento == "stage_progress"
    assert datos["research_source"] == "pdl"
    assert (datos["stage_id"], datos["status"], datos["reason_code"]) == (
        "person.pdl_enrich", "completed", "no_matches"
    )
    assert datos["attempts"] == {"total": 3, "failed": 1}


def test_partial_result_se_guarda_antes_de_publicarse(progreso):
    job = progreso.job()
    job.declare([m.corporate_scope("corporate:0", "Acme")])
    visto_al_publicar: list = []
    publicar_original = progreso.publicar

    def publicar(job_id, evento, datos):
        guardado = progreso.guardado(job_id)
        visto_al_publicar.append(guardado["revision"])
        publicar_original(job_id, evento, datos)

    job._publish = publicar
    job.scope("corporate:0").partial(m.corporate_partial("synthesize_llm", "synthesis", "## Resumen"))

    evento, datos = progreso.eventos[-1]
    assert evento == "partial_result"
    assert datos["section"] == "synthesis" and datos["content"] == "## Resumen"
    assert visto_al_publicar == [datos["revision"]], "se publica lo que ya está confirmado"


def test_partial_personal_lleva_la_modalidad_del_scope(progreso):
    job = progreso.job()
    job.declare([m.person_scope("person:0", "Ana", "gemini_web")])

    job.scope("person:0").partial(
        m.person_partial_markdown(
            "person.context_analysis", "person_context_report", "## Informe",
            basis="model_only", sources=[], origin="generated",
        )
    )

    datos = progreso.de("partial_result")[-1]
    assert datos["research_source"] == "gemini_web"
    assert datos["provenance"]["live_web_search"] is False


def test_parcial_vacio_no_se_publica(progreso):
    job = progreso.job()
    job.declare([m.corporate_scope("corporate:0", "Acme")])

    job.scope("corporate:0").partial(None)

    assert progreso.de("partial_result") == []


def test_un_job_terminado_no_revive_con_callbacks_tardios(progreso):
    job = progreso.job()
    job.declare([m.corporate_scope("corporate:0", "Acme")])
    progreso.estado(job.job_id, "cancelled")

    job.scope("corporate:0").agent("agent_news", "running")
    job.scope("corporate:0").partial(m.corporate_partial("agent_news", "news", "- titular"))

    assert [e for e, _ in progreso.eventos] == ["job_status"]
    assert progreso.guardado(job.job_id)["revision"] == 1


def test_campos_del_scope_y_snapshot_quedan_disponibles(progreso):
    job = progreso.job()
    job.declare([m.person_scope("person:0", "Ana", "pdl")])

    job.scope("person:0").fields(origin="redis_cache", profiles_count=2)

    scope = job.scope("person:0").snapshot()
    assert (scope["origin"], scope["profiles_count"]) == ("redis_cache", 2)


def test_scope_nulo_no_hace_nada():
    djp.NULL_SCOPE.agent("agent_news", "running")
    djp.NULL_SCOPE.stage("person.persist", "completed")
    djp.NULL_SCOPE.partial({"section": "news"})
    djp.NULL_SCOPE.fields(origin="generated")
    assert djp.NULL_SCOPE.snapshot() is None
    assert djp.NULL_SCOPE.research_source is None


def test_si_el_almacen_falla_la_generacion_sigue_y_no_se_publica(caplog):
    class AlmacenRoto:
        def apply(self, job_id, change):
            raise RuntimeError("base caída")

    publicados: list = []
    job = djp.JobProgress(uuid.uuid4(), AlmacenRoto(), publish=lambda *a: publicados.append(a))

    job.declare([m.corporate_scope("corporate:0", "Acme")])
    job.scope("corporate:0").agent("agent_news", "running")

    assert publicados == []
    assert "progreso" in caplog.text.lower()


def test_un_cambio_invalido_se_descarta_sin_lanzar(caplog):
    publicados: list = []

    class Almacen:
        progreso = None

        def apply(self, job_id, change):
            import copy

            cambio = change(copy.deepcopy(self.progreso))
            if cambio is None:
                return None
            self.progreso, resultado = cambio
            return resultado, copy.deepcopy(self.progreso), {"id": str(job_id)}

    job = djp.JobProgress(uuid.uuid4(), Almacen(), publish=lambda *a: publicados.append(a))
    job.declare([m.person_scope("person:0", "Ana", "gemini_web")])

    job.scope("person:0").stage("person.pdl_enrich", "running")  # no existe en Web pública

    assert [p[1] for p in publicados] == ["job_status"]
    assert "person.pdl_enrich" in caplog.text


def test_actualizaciones_concurrentes_no_duplican_revisiones_y_publican_en_orden(progreso):
    job = progreso.job()
    job.declare([m.corporate_scope("corporate:0", "Acme")])
    agentes = list(m.CORPORATE_AGENTS)

    def trabajar(nombre):
        s = job.scope("corporate:0")
        s.agent(nombre, "running")
        s.agent(nombre, "completed")

    hilos = [threading.Thread(target=trabajar, args=(a,)) for a in agentes]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    revisiones = [d["revision"] for d in progreso.de("agent_progress")]
    assert revisiones == sorted(revisiones) == list(range(2, 2 + 2 * len(agentes)))
    assert progreso.guardado(job.job_id)["revision"] == 1 + 2 * len(agentes)
