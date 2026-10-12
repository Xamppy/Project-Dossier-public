"""Tests de integración — S4.9: resultados parciales cuando un agente falla.

Cubre tres capas, de abajo hacia arriba:

1. El grafo completo (``StateGraph`` compilado, no los nodos sueltos): un agente
   que lanza excepción no impide que el otro y la síntesis terminen (CA2 de
   S0.12), y ``agents_failed``/``agents_succeeded`` se acumulan correctamente
   incluso cuando UK y USA fallan en el mismo superpaso paralelo.
2. El servicio de calendario (``generate_dossiers_from_calendar_event``): la
   telemetría del grafo llega intacta hasta el dict de resultado.
3. La persistencia (``persist_calendar_dossiers``): la fila ``dossiers`` guarda
   el ``agents_failed`` real del grafo, no la aproximación anterior basada solo
   en si el Markdown final es un error.

4. Round-trip contra Postgres real (``pg_vacia`` + ``alembic_cfg``, mismo patrón que
   ``tests/integration/test_person_research_structured.py``): la columna
   ``agents_failed`` es ``ARRAY(Text)`` — se verifica que un ``list[str]`` de Python
   sobrevive el viaje de ida y vuelta, no solo que el atributo del objeto ORM quedó
   bien puesto en memoria.

Las capas 1-3 no requieren Postgres real: ``persist_calendar_dossiers`` solo llama a
``db.get``/``db.add``/``db.commit``, así que una sesión doble alcanza (mismo patrón
``_FakeSession`` que ``tests/integration/test_dossier_stream_route.py``).
"""
from __future__ import annotations

import uuid

from dossier.db.models import Dossier
from dossier.graphs.corporate_dossier_graph import run_corporate_dossier_langgraph_detailed
from dossier.services.calendar_event_dossiers import (
    generate_dossiers_from_calendar_event,
    persist_calendar_dossiers,
)

# ---------------------------------------------------------------------------
# 1. Grafo completo
# ---------------------------------------------------------------------------

def _monkeypatch_agentes(monkeypatch, *, uk_ok=True, usa_ok=True, llm_ok=True):
    import dossier.llm.text_generate as llm
    import dossier.services.corporate_registry_context as ctx

    if uk_ok:
        monkeypatch.setattr(ctx, "build_uk_corporate_context_markdown", lambda p: "## UK\n\ndatos reales\n")
    else:
        def _uk_falla(_p):
            raise RuntimeError("Companies House caído")

        monkeypatch.setattr(ctx, "build_uk_corporate_context_markdown", _uk_falla)

    if usa_ok:
        monkeypatch.setattr(ctx, "build_us_corporate_context_markdown", lambda p: "## USA\n\ndatos reales\n")
    else:
        def _usa_falla(_p):
            raise TimeoutError("SEC EDGAR no respondió a tiempo")

        monkeypatch.setattr(ctx, "build_us_corporate_context_markdown", _usa_falla)

    if llm_ok:
        monkeypatch.setattr(
            llm, "generate_text_with_llm", lambda user, system_instruction=None: "# Dossier corporativo\n\nResumen."
        )
    else:
        def _llm_falla(user, system_instruction=None):
            raise RuntimeError("DeepSeek no disponible")

        monkeypatch.setattr(llm, "generate_text_with_llm", _llm_falla)


def test_un_agente_falla_el_otro_y_la_sintesis_terminan(monkeypatch):
    _monkeypatch_agentes(monkeypatch, uk_ok=False, usa_ok=True, llm_ok=True)

    resultado = run_corporate_dossier_langgraph_detailed(
        tema_reunion="Reunión con Acme",
        participantes="Acme Corp",
        jurisdiction_scope="dual",
    )

    assert resultado.agents_failed == ["agent_corporate_uk"]
    assert set(resultado.agents_succeeded) == {"agent_corporate_usa", "synthesize_llm"}
    assert not resultado.markdown.lstrip().startswith("# Error")
    assert resultado.markdown == "# Dossier corporativo\n\nResumen."


def test_ambos_agentes_fallan_a_la_vez_sin_perder_ninguno(monkeypatch):
    """Fallo simultáneo en el mismo superpaso paralelo: el reducer no debe pisar entradas."""
    _monkeypatch_agentes(monkeypatch, uk_ok=False, usa_ok=False, llm_ok=True)

    resultado = run_corporate_dossier_langgraph_detailed(
        tema_reunion="Reunión con Acme",
        participantes="Acme Corp",
        jurisdiction_scope="dual",
    )

    assert set(resultado.agents_failed) == {"agent_corporate_uk", "agent_corporate_usa"}
    assert len(resultado.agents_failed) == 2, "cada agente debe aparecer una sola vez"
    # La síntesis sigue corriendo con los bloques de error como único contexto disponible.
    assert resultado.agents_succeeded == ["synthesize_llm"]
    assert not resultado.markdown.lstrip().startswith("# Error")


def test_sintesis_falla_pero_no_revienta_el_grafo(monkeypatch):
    _monkeypatch_agentes(monkeypatch, uk_ok=True, usa_ok=True, llm_ok=False)

    resultado = run_corporate_dossier_langgraph_detailed(
        tema_reunion="Reunión con Acme",
        participantes="Acme Corp",
        jurisdiction_scope="dual",
    )

    assert resultado.agents_failed == ["synthesize_llm"]
    assert set(resultado.agents_succeeded) == {"agent_corporate_uk", "agent_corporate_usa"}
    assert resultado.markdown.startswith("# Error en síntesis")


# ---------------------------------------------------------------------------
# 2. Servicio de calendario
# ---------------------------------------------------------------------------

def test_generate_dossiers_propaga_agents_failed_del_grafo(monkeypatch):
    import dossier.services.calendar_event_dossiers as calmod

    class _ResultadoFalso:
        def __init__(self) -> None:
            self.markdown = "# Dossier corporativo\n\nResumen parcial."
            self.agents_failed = ["agent_corporate_uk"]
            self.agents_succeeded = ["agent_corporate_usa", "synthesize_llm"]

    monkeypatch.setattr(
        calmod,
        "run_corporate_dossier_langgraph_detailed",
        lambda **kwargs: _ResultadoFalso(),
    )
    # Evita la resolución real (Companies House / SEC vía red): no es lo que se prueba aquí.
    monkeypatch.setattr(calmod, "resolve_corporate_brief", lambda q: (q, "dual"))

    reunion = {
        "tema": "Reunión con Acme Corp",
        "descripcion": "Empresa: Acme Corp",
        "participantes": [],
        "inicio": "2026-09-28T10:00:00Z",
    }

    resultado = generate_dossiers_from_calendar_event(reunion, organization_plan="pro")

    assert resultado["corporate_agents_failed"] == ["agent_corporate_uk"]
    assert resultado["dossier_corporativo"] == "# Dossier corporativo\n\nResumen parcial."


# ---------------------------------------------------------------------------
# 3. Persistencia
# ---------------------------------------------------------------------------

class _FakeSession:
    """Doble mínimo de ``Session``: solo lo que usa ``persist_calendar_dossiers``."""

    def __init__(self):
        self.added: list[object] = []

    def get(self, model, pk):
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass


def _resultado_base(*, corporate_md: str, corporate_agents_failed):
    return {
        "reunion": {},
        "parse": {"tema": "Reunión con Acme", "company_corporate": "Acme Corp"},
        "dossier_corporativo": corporate_md,
        "dossier_persona": None,
        "dossier_persona_research": None,
        "dossier_personas": [],
        "errors": [],
        "corporate_cache_hit": False,
        "person_cache_hit": False,
        "corporate_cache_key": None,
        "person_cache_key": None,
        "corporate_agents_failed": corporate_agents_failed,
        "output_language": "es",
    }


def test_persist_usa_agents_failed_explicito_aunque_el_dossier_sea_exitoso():
    """Éxito global (la síntesis armó Markdown) con un agente parcialmente caído."""
    db = _FakeSession()
    result = _resultado_base(
        corporate_md="# Dossier corporativo\n\nResumen.",
        corporate_agents_failed=["agent_corporate_uk"],
    )

    persist_calendar_dossiers(
        db,
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        result=result,
        calendar_provider="google",
        generation_duration_ms=10,
    )

    corp = next(o for o in db.added if isinstance(o, Dossier) and o.module_corporate)
    assert corp.status == "complete"
    assert corp.agents_failed == ["agent_corporate_uk"]


def test_persist_con_markdown_de_error_total_no_crea_fila_corporativa():
    """Hallazgo (no introducido por S4.9): ``_markdown_is_persistable`` ya excluía todo
    Markdown que empieza con ``# Error`` *antes* de llegar al ``if is_err`` de esta
    función — así que ese ``if`` nunca vio ``is_err=True`` para el corporativo. La
    excepción fuera del grafo (ver ``generate_dossiers_from_calendar_event``) queda
    registrada solo en ``errors``/``corporate_skipped_plan_free``, no como fila
    ``dossiers``. El fallback ``["synthesize_llm"] if is_err else []`` se conserva por
    compatibilidad, pero es inalcanzable para el corporativo en la práctica."""
    db = _FakeSession()
    result = _resultado_base(
        corporate_md="# Error en dossier corporativo\n\nboom",
        corporate_agents_failed=None,
    )

    item = persist_calendar_dossiers(
        db,
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        result=result,
        calendar_provider="google",
        generation_duration_ms=10,
    )

    assert "corporate" not in item.get("saved_dossiers", {})
    assert not any(isinstance(o, Dossier) and o.module_corporate for o in db.added)


def test_persist_sin_telemetria_y_sin_error_no_marca_ningun_agente_fallido():
    db = _FakeSession()
    result = _resultado_base(
        corporate_md="# Dossier corporativo\n\nResumen.",
        corporate_agents_failed=None,
    )

    persist_calendar_dossiers(
        db,
        user_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        result=result,
        calendar_provider="google",
        generation_duration_ms=10,
    )

    corp = next(o for o in db.added if isinstance(o, Dossier) and o.module_corporate)
    assert corp.status == "complete"
    assert corp.agents_failed == []


# ---------------------------------------------------------------------------
# 4. Emisión del evento SSE `agent_progress` (S0.11) desde el job
# ---------------------------------------------------------------------------

def test_job_service_publica_agent_progress_por_cada_agente_fallido():
    from dossier.services.dossier_generation_job_service import _publish_corporate_agent_failures
    from dossier.services.dossier_progress_events import events_since

    job_id = uuid.uuid4()
    _publish_corporate_agent_failures(job_id, ["agent_corporate_uk", "agent_corporate_usa"])

    eventos = events_since(job_id, 0)
    assert [e[1] for e in eventos] == ["agent_progress", "agent_progress"]
    nombres = [e[2]["agent_name"] for e in eventos]
    assert nombres == ["agent_corporate_uk", "agent_corporate_usa"]
    assert all(e[2]["status"] == "failed" for e in eventos)
    assert all(e[2]["dossier_id"] == str(job_id) for e in eventos)


def test_job_service_no_publica_nada_si_no_hay_agentes_fallidos():
    from dossier.services.dossier_generation_job_service import _publish_corporate_agent_failures
    from dossier.services.dossier_progress_events import events_since

    job_id = uuid.uuid4()
    _publish_corporate_agent_failures(job_id, [])

    assert events_since(job_id, 0) == []


# ---------------------------------------------------------------------------
# 5. Round-trip contra Postgres real: la columna ARRAY(Text) `agents_failed`
# ---------------------------------------------------------------------------

def test_persist_calendar_dossiers_guarda_agents_failed_en_postgres_real(pg_vacia, alembic_cfg):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from alembic import command

    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org_id = conn.execute(
            text("INSERT INTO organizations (name, slug) VALUES ('Org', 'org-s49') RETURNING id")
        ).scalar_one()
        user_id = conn.execute(
            text("INSERT INTO users (email) VALUES ('s49@example.test') RETURNING id")
        ).scalar_one()

    result = _resultado_base(
        corporate_md="# Dossier corporativo\n\nResumen.",
        corporate_agents_failed=["agent_corporate_uk"],
    )

    with Session(pg_vacia) as db:
        item = persist_calendar_dossiers(
            db,
            user_id=user_id,
            org_id=org_id,
            result=result,
            calendar_provider="google",
            generation_duration_ms=10,
            charge_credits=False,
        )
        dossier_id = item["saved_dossiers"]["corporate"]["id"]

    with pg_vacia.connect() as conn:
        agents_failed, status = conn.execute(
            text("SELECT agents_failed, status FROM dossiers WHERE id = :d"),
            {"d": dossier_id},
        ).one()

    assert list(agents_failed) == ["agent_corporate_uk"]
    assert status == "complete"
