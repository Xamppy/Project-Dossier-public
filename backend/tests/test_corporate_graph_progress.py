"""S5.10 · BE1/BE3: el grafo corporativo informa inicio y terminal reales de cada agente.

El observador se pasa por invocación (``progress=``); sin él, el grafo hace lo
mismo que antes. Los proveedores son dobles: ninguna prueba sale a la red.
"""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

import pytest

from dossier.eu_registry.agent import ResultadoAgenteEuropeo
from dossier.graphs.corporate_dossier_graph import run_corporate_dossier_langgraph_detailed
from dossier.news.agent import FalloProveedor, ResultadoRecoleccionPrensa
from dossier.schemas.corporate_registry import JurisdiccionRegistro, RegistroCorporativo
from dossier.schemas.dossier_executive_payload import (
    CorporateRecordCitation,
    PressMention,
    SourceCitation,
    SourceType,
)
from dossier.services import dossier_progress_model as m

AHORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
SECRETO = "detalle-interno-7f3a"


def _cita(razon="Acme France SAS"):
    return CorporateRecordCitation(
        record=RegistroCorporativo(
            jurisdiccion=JurisdiccionRegistro.fr,
            fuente="recherche-entreprises",
            identificador_registro="123456789",
            razon_social=razon,
            estado="active",
            url_fuente="https://annuaire-entreprises.data.gouv.fr/entreprise/123456789",
        ),
        source=SourceCitation(
            source_type=SourceType.eu_registry, source_name="recherche-entreprises", retrieved_at=AHORA
        ),
    )


def _mencion():
    return PressMention(
        headline="Acme anuncia expansión",
        publisher="Diario de Prueba",
        published_date="2026-10-01",
        summary="Resumen breve.",
        url="https://example.test/nota",
        source=SourceCitation(source_type=SourceType.gdelt_news, source_name="gdelt_news", retrieved_at=AHORA),
    )


def _falla(mensaje):
    def _f(*_a, **_k):
        raise RuntimeError(mensaje)

    return _f


@pytest.fixture
def agentes(monkeypatch):
    """Todos los agentes responden bien; cada prueba rompe el que necesita."""
    import dossier.llm.text_generate as llm
    import dossier.services.corporate_registry_context as ctx

    def instalar(*, uk=None, usa=None, eu=None, news=None, sintesis=None):
        monkeypatch.setattr(ctx, "build_uk_corporate_context_markdown", uk or (lambda p: "## UK\n\nregistro UK\n"))
        monkeypatch.setattr(ctx, "build_us_corporate_context_markdown", usa or (lambda p: "## USA\n\nregistro US\n"))
        monkeypatch.setattr(
            "dossier.eu_registry.agent.run_eu_registry_agent",
            eu or (lambda nombre, **_: ResultadoAgenteEuropeo(citas=[_cita()])),
        )
        monkeypatch.setattr(
            "dossier.news.agent.collect_press_mentions",
            news or (lambda consulta, **_: ResultadoRecoleccionPrensa(mentions=[_mencion()])),
        )
        monkeypatch.setattr(
            llm,
            "generate_text_with_llm",
            sintesis or (lambda user, system_instruction=None: "# Dossier corporativo\n\nResumen final."),
        )

    instalar()
    return instalar


def _correr(progreso, *, scope="dual", empresa="Acme"):
    job = progreso.job()
    job.declare([m.corporate_scope("corporate:0", "Acme")])
    resultado = run_corporate_dossier_langgraph_detailed(
        tema_reunion="Reunión con Acme",
        participantes="Acme",
        jurisdiction_scope=scope,
        empresa_objetivo=empresa,
        progress=job.scope("corporate:0"),
    )
    return job, resultado


def _transiciones(progreso, agente):
    return [
        (d["status"], d["reason_code"]) for d in progreso.de("agent_progress") if d["agent_name"] == agente
    ]


def _parciales(progreso):
    return {d["section"]: d for d in progreso.de("partial_result")}


def test_alcance_dual_cada_agente_inicia_y_termina_y_la_sintesis_va_al_final(progreso, agentes):
    _correr(progreso)

    for agente in m.CORPORATE_AGENTS:
        assert _transiciones(progreso, agente) == [("running", None), ("completed", None)], agente
    eventos = [(d["agent_name"], d["status"]) for d in progreso.de("agent_progress")]
    inicio_sintesis = eventos.index(("synthesize_llm", "running"))
    for agente in m.CORPORATE_AGENTS[:4]:
        assert eventos.index((agente, "completed")) < inicio_sintesis, "la síntesis espera el fan-in"


def test_un_agente_que_falla_no_aborta_y_el_resto_completa(progreso, agentes):
    agentes(uk=_falla(f"Companies House caído {SECRETO}"))

    _, resultado = _correr(progreso)

    assert _transiciones(progreso, "agent_corporate_uk") == [("running", None), ("failed", "provider_error")]
    assert _transiciones(progreso, "synthesize_llm")[-1] == ("completed", None)
    assert resultado.agents_failed == ["agent_corporate_uk"]
    assert "synthesis" in _parciales(progreso)


@pytest.mark.parametrize(
    ("alcance", "omitidos"),
    [
        ("us_only", {"agent_corporate_uk", "agent_corporate_eu"}),
        ("uk_only", {"agent_corporate_usa", "agent_corporate_eu"}),
        ("eu_only", {"agent_corporate_uk", "agent_corporate_usa"}),
    ],
)
def test_agentes_fuera_de_alcance_quedan_omitidos_sin_pasar_por_running(progreso, agentes, alcance, omitidos):
    _correr(progreso, scope=alcance)

    for agente in omitidos:
        assert _transiciones(progreso, agente) == [("skipped", "out_of_scope")], agente
    for agente in set(m.CORPORATE_AGENTS) - omitidos:
        assert _transiciones(progreso, agente)[0] == ("running", None), agente


def test_sin_empresa_objetivo_europa_y_prensa_se_omiten_con_motivo(progreso, agentes):
    _correr(progreso, empresa="")

    assert _transiciones(progreso, "agent_corporate_eu") == [("skipped", "no_target_company")]
    assert _transiciones(progreso, "agent_news") == [("skipped", "no_target_company")]


def test_europa_con_registros_publica_su_vista_previa_con_url_de_registro(progreso, agentes):
    _correr(progreso)

    parcial = _parciales(progreso)["corporate_eu"]
    assert parcial["agent_name"] == "agent_corporate_eu"
    assert "Acme France SAS" in parcial["content"]
    assert "https://annuaire-entreprises.data.gouv.fr/entreprise/123456789" in parcial["content"]
    assert parcial["provisional"] is True and parcial["format"] == "markdown"


def test_europa_y_prensa_sin_coincidencias_completan_sin_vista_previa(progreso, agentes):
    agentes(
        eu=lambda nombre, **_: ResultadoAgenteEuropeo(citas=[_cita("Otra Empresa SAS")]),
        news=lambda consulta, **_: ResultadoRecoleccionPrensa(mentions=[]),
    )

    _correr(progreso)

    assert _transiciones(progreso, "agent_corporate_eu")[-1] == ("completed", "no_matches")
    assert _transiciones(progreso, "agent_news")[-1] == ("completed", "no_matches")
    assert {"corporate_eu", "news"}.isdisjoint(_parciales(progreso))


def test_prensa_con_menciones_publica_titular_medio_y_url(progreso, agentes):
    _correr(progreso)

    parcial = _parciales(progreso)["news"]
    assert "Acme anuncia expansión" in parcial["content"]
    assert "https://example.test/nota" in parcial["content"]


def test_prensa_sin_proveedores_falla_sin_vista_previa(progreso, agentes):
    agentes(
        news=lambda consulta, **_: ResultadoRecoleccionPrensa(
            mentions=[],
            failed_providers=[FalloProveedor("gdelt", SECRETO), FalloProveedor("newsapi", SECRETO)],
        )
    )

    _correr(progreso)

    assert _transiciones(progreso, "agent_news")[-1] == ("failed", "provider_error")
    assert "news" not in _parciales(progreso)


def test_uk_y_usa_nunca_publican_vista_previa(progreso, agentes):
    agentes(uk=lambda p: "## UK\n\n*Error al analizar el documento: timeout*\n")

    _correr(progreso)

    assert set(_parciales(progreso)) == {"corporate_eu", "news", "synthesis"}


def test_sintesis_fallida_no_publica_texto_de_error(progreso, agentes):
    agentes(sintesis=_falla(f"DeepSeek no disponible {SECRETO}"))

    _, resultado = _correr(progreso)

    assert _transiciones(progreso, "synthesize_llm") == [("running", None), ("failed", "provider_error")]
    assert "synthesis" not in _parciales(progreso)
    assert resultado.markdown.startswith("# Error en síntesis")


def test_ningun_evento_lleva_texto_de_excepciones(progreso, agentes):
    agentes(
        uk=_falla(SECRETO),
        usa=_falla(SECRETO),
        eu=_falla(SECRETO),
        news=_falla(SECRETO),
        sintesis=_falla(SECRETO),
    )

    _correr(progreso)

    assert SECRETO not in json.dumps(progreso.eventos)


def test_sin_observador_el_grafo_devuelve_lo_mismo(agentes):
    resultado = run_corporate_dossier_langgraph_detailed(
        tema_reunion="Reunión con Acme", participantes="Acme", jurisdiction_scope="dual", empresa_objetivo="Acme"
    )

    assert resultado.markdown == "# Dossier corporativo\n\nResumen final."
    assert sorted(resultado.agents_succeeded) == sorted(m.CORPORATE_AGENTS)


def test_dos_grafos_concurrentes_no_cruzan_eventos(progreso, agentes):
    """BE1: cada invocación lleva su observador; no hay estado global del job actual."""

    def uk(participantes):
        if "Rota" in participantes:
            raise RuntimeError("caído")
        return "## UK\n\nok\n"

    agentes(uk=uk)

    jobs = {}

    def correr(nombre):
        job = progreso.job()
        job.declare([m.corporate_scope("corporate:0", nombre)])
        jobs[nombre] = job
        run_corporate_dossier_langgraph_detailed(
            tema_reunion=nombre,
            participantes=nombre,
            jurisdiction_scope="dual",
            empresa_objetivo=nombre,
            progress=job.scope("corporate:0"),
        )

    hilos = [threading.Thread(target=correr, args=(n,)) for n in ("Sana", "Rota")]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    def uk_de(nombre):
        job_id = str(jobs[nombre].job_id)
        return [
            d["status"]
            for d in progreso.de("agent_progress")
            if d["job_id"] == job_id and d["agent_name"] == "agent_corporate_uk"
        ]

    assert uk_de("Sana") == ["running", "completed"]
    assert uk_de("Rota") == ["running", "failed"]
