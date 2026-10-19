"""Tests unitarios — deduplicación de investigación de persona."""
from __future__ import annotations

import uuid

from dossier.schemas.person_research import PersonResearchRequest
from dossier.services.person_dossier_dedup import person_research_fingerprint


def test_same_name_same_org_same_fingerprint():
    org_id = uuid.uuid4()
    a = PersonResearchRequest(full_name="Matías Prueba")
    b = PersonResearchRequest(full_name="Matias Prueba")
    assert person_research_fingerprint(a, org_id) == person_research_fingerprint(b, org_id)


def test_different_company_different_fingerprint():
    org_id = uuid.uuid4()
    a = PersonResearchRequest(full_name="Matias Prueba", company="Empresa Ejemplo SpA")
    b = PersonResearchRequest(full_name="Matias Prueba", company="Other")
    assert person_research_fingerprint(a, org_id) != person_research_fingerprint(b, org_id)


def test_different_org_different_fingerprint():
    req = PersonResearchRequest(full_name="Jane Doe")
    assert person_research_fingerprint(req, uuid.uuid4()) != person_research_fingerprint(
        req, uuid.uuid4()
    )


def test_different_name_different_fingerprint():
    org_id = uuid.uuid4()
    a = PersonResearchRequest(full_name="Alice Smith")
    b = PersonResearchRequest(full_name="Bob Smith")
    assert person_research_fingerprint(a, org_id) != person_research_fingerprint(b, org_id)


def test_output_language_affects_fingerprint():
    org_id = uuid.uuid4()
    es = PersonResearchRequest(full_name="Jane Doe", output_language="es")
    en = PersonResearchRequest(full_name="Jane Doe", output_language="en")
    assert person_research_fingerprint(es, org_id) != person_research_fingerprint(en, org_id)
