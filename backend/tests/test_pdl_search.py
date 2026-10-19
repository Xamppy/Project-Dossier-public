"""Tests unitarios — estrategias PDL y caché de persona."""
from __future__ import annotations

from dossier.schemas.person_research import PersonResearchRequest
from dossier.services.pdl_search import build_pdl_enrich_strategies, build_pdl_search_sql
from dossier.services.person_dossier_dedup import (
    person_research_response_from_redis_cache,
    profiles_count_from_research_result,
    should_cache_person_research_result,
)


def test_pdl_enrich_uses_full_name_when_no_extra_signal():
    req = PersonResearchRequest(full_name="Edward Dalton")
    strategies = build_pdl_enrich_strategies(req)
    assert any(params.get("name") == "Edward Dalton" for _, params in strategies)


def test_pdl_enrich_combines_name_with_company():
    req = PersonResearchRequest(full_name="Valeria Ruiz Prueba", company="Empresa Ejemplo SpA")
    strategies = build_pdl_enrich_strategies(req)
    assert all(
        "company" in params or "location" in params or "country" in params or "name" in params
        for _, params in strategies
    )
    assert any(
        params.get("first_name") == "Valeria" and params.get("last_name") == "Prueba"
        for _, params in strategies
    )


def test_pdl_search_sql_covers_multiple_name_splits():
    req = PersonResearchRequest(full_name="Valeria Ruiz Prueba")
    sql = build_pdl_search_sql(req)
    assert sql is not None
    assert "first_name='Valeria'" in sql
    assert "last_name='Prueba'" in sql


def test_should_not_cache_pdl_without_profiles():
    result = {
        "llm_analysis_markdown": "# Informe",
        "profiles": [],
    }
    assert not should_cache_person_research_result(result, gemini_only=False)
    assert should_cache_person_research_result(result, gemini_only=True)


def test_redis_cache_response_restores_profiles_count():
    req = PersonResearchRequest(full_name="Jane Doe")
    cached = {
        "markdown": "# Informe",
        "profiles_count": 2,
        "profile_urls": ["https://linkedin.com/in/jane"],
        "warnings": [],
        "gemini_google_search_used": True,
    }
    out = person_research_response_from_redis_cache(
        req,
        organization_context_block=None,
        cached_payload=cached,
    )
    assert profiles_count_from_research_result(out) == 2
    assert out["profile_urls"] == ["https://linkedin.com/in/jane"]
