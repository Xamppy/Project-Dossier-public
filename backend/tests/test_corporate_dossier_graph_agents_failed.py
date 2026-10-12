"""Tests — S4.9: registro estructurado de agentes fallidos en el grafo corporativo.

Cubre los nodos ``agent_corporate_uk``, ``agent_corporate_usa`` y ``synthesize_llm``
de ``corporate_dossier_graph.py`` de forma aislada (sin compilar el grafo completo):
cada nodo debe reportar en qué lista queda (``agents_failed`` / ``agents_succeeded``)
según si su dependencia externa lanzó excepción o no.
"""
from __future__ import annotations

from dossier.graphs.corporate_dossier_graph import (
    _node_agent_corporate_uk,
    _node_agent_corporate_usa,
    _node_synthesize_llm,
)


def test_agente_uk_exitoso_queda_en_agents_succeeded(monkeypatch):
    import dossier.services.corporate_registry_context as ctx

    monkeypatch.setattr(ctx, "build_uk_corporate_context_markdown", lambda p: "## UK\n\nok\n")

    out = _node_agent_corporate_uk({"jurisdiction_scope": "dual", "participantes": "Acme Ltd"})

    assert out["agents_succeeded"] == ["agent_corporate_uk"]
    assert "agents_failed" not in out


def test_agente_uk_que_lanza_excepcion_queda_en_agents_failed(monkeypatch):
    import dossier.services.corporate_registry_context as ctx

    def _explota(_participantes: str) -> str:
        raise RuntimeError("Companies House no responde")

    monkeypatch.setattr(ctx, "build_uk_corporate_context_markdown", _explota)

    out = _node_agent_corporate_uk({"jurisdiction_scope": "dual", "participantes": "Acme Ltd"})

    assert out["agents_failed"] == ["agent_corporate_uk"]
    assert "agents_succeeded" not in out
    # El nodo sigue devolviendo un bloque Markdown legible: la síntesis puede usarlo igual.
    assert "Error interno" in out["uk_corporate_context"]


def test_agente_uk_omitido_por_alcance_no_se_marca_ni_exitoso_ni_fallido(monkeypatch):
    """``us_only`` significa que el nodo UK ni se llama: no cuenta como agente activado."""
    out = _node_agent_corporate_uk({"jurisdiction_scope": "us_only", "participantes": "Acme Inc"})

    assert "agents_failed" not in out
    assert "agents_succeeded" not in out


def test_agente_usa_exitoso_queda_en_agents_succeeded(monkeypatch):
    import dossier.services.corporate_registry_context as ctx

    monkeypatch.setattr(ctx, "build_us_corporate_context_markdown", lambda p: "## USA\n\nok\n")

    out = _node_agent_corporate_usa({"jurisdiction_scope": "dual", "participantes": "Acme Inc"})

    assert out["agents_succeeded"] == ["agent_corporate_usa"]


def test_agente_usa_que_expira_queda_en_agents_failed(monkeypatch):
    """Un timeout es una ``Exception`` como cualquier otra: el try/except ya la cubre."""
    import dossier.services.corporate_registry_context as ctx

    def _expira(_participantes: str) -> str:
        raise TimeoutError("SEC EDGAR tardó demasiado")

    monkeypatch.setattr(ctx, "build_us_corporate_context_markdown", _expira)

    out = _node_agent_corporate_usa({"jurisdiction_scope": "dual", "participantes": "Acme Inc"})

    assert out["agents_failed"] == ["agent_corporate_usa"]


def test_sintesis_exitosa_queda_en_agents_succeeded(monkeypatch):
    import dossier.llm.text_generate as llm

    monkeypatch.setattr(llm, "generate_text_with_llm", lambda user, system_instruction=None: "# Dossier\n\nOK")

    out = _node_synthesize_llm(
        {
            "tema_reunion": "Reunión",
            "participantes": "Acme",
            "uk_corporate_context": "## UK",
            "us_corporate_context": "## USA",
            "jurisdiction_scope": "dual",
        }
    )

    assert out["agents_succeeded"] == ["synthesize_llm"]
    assert out["final_dossier_markdown"] == "# Dossier\n\nOK"


def test_sintesis_que_falla_no_bloquea_y_queda_en_agents_failed(monkeypatch):
    """CA2 de S0.12: la síntesis no debe propagar la excepción hacia arriba."""
    import dossier.llm.text_generate as llm

    def _explota(user: str, system_instruction: str | None = None) -> str:
        raise RuntimeError("DeepSeek no disponible")

    monkeypatch.setattr(llm, "generate_text_with_llm", _explota)

    out = _node_synthesize_llm(
        {
            "tema_reunion": "Reunión",
            "participantes": "Acme",
            "uk_corporate_context": "## UK",
            "us_corporate_context": "## USA",
            "jurisdiction_scope": "dual",
            "agent_errors": [],
        }
    )

    assert out["agents_failed"] == ["synthesize_llm"]
    assert out["final_dossier_markdown"].startswith("# Error en síntesis")
    assert "DeepSeek no disponible" in out["agent_errors"][0]
