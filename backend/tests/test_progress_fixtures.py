"""S5.10 · Las fixtures para el frontend de S5.4 cumplen el contrato de ADR 0009.

Las genera ``backend/scripts/generar_fixtures_progreso.py`` con el backend real y
los proveedores simulados. Esta prueba no necesita base de datos: valida los
archivos, para que un cambio de contrato sin regenerarlas no pase inadvertido.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dossier.services import dossier_progress_model as m

CARPETA = Path(__file__).resolve().parents[2] / "specs" / "fixtures" / "S5.10-progreso"
ESPERADAS = {
    "calendario-agente-caido",
    "personas-pdl",
    "personas-pdl-respaldo",
    "personas-pdl-informe-fallido",
    "personas-web-publica",
    "personas-web-publica-fallida",
    "personas-cache",
    "personas-cancelada",
}
EVENTOS_JOB = {"job_status", "job_completed", "job_failed"}
EVENTOS_PROGRESO = {"agent_progress", "stage_progress", "partial_result"}
BASE = {"schema_version", "job_id", "scope_id", "revision"}
CLAVES_AGENTE = BASE | {"agent_name", "status", "timestamp", "reason_code"}
CLAVES_ETAPA = BASE | {"research_source", "stage_id", "status", "timestamp", "reason_code"}
CLAVES_PERFIL = {"record_key", "full_name", "job_title", "company", "profile_urls"}


def _fixture(nombre: str) -> dict:
    return json.loads((CARPETA / f"{nombre}.json").read_text(encoding="utf-8"))


def test_estan_todas_las_fixtures():
    assert {p.stem for p in CARPETA.glob("*.json")} == ESPERADAS


def _validar_estado(datos: dict) -> None:
    assert datos["status"] in m.STATUSES
    if datos["reason_code"] is not None:
        assert datos["reason_code"] in m.REASON_CODES[datos["status"]]


@pytest.mark.parametrize("nombre", sorted(ESPERADAS))
def test_la_fixture_cumple_el_contrato(nombre):
    fixture = _fixture(nombre)
    frames = fixture["frames"]
    ids = [f["id"] for f in frames]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert frames[-1]["event"] in {"job_completed", "job_failed"}
    assert frames[-1]["data"]["status"] == fixture["snapshot_final"]["status"]

    scopes: dict[str, dict] = {}
    ultima_revision = 0
    for frame in frames:
        evento, datos = frame["event"], frame["data"]
        assert evento in EVENTOS_JOB | EVENTOS_PROGRESO, evento
        if evento in EVENTOS_JOB:
            progreso = datos.get("progress")
            if progreso:
                assert progreso["revision"] >= ultima_revision
                ultima_revision = progreso["revision"]
                scopes = {s["scope_id"]: s for s in progreso["scopes"]}
            continue
        assert datos["revision"] > ultima_revision, f"revisión fuera de orden en el frame {frame['id']}"
        ultima_revision = datos["revision"]
        scope = scopes[datos["scope_id"]]
        if evento == "agent_progress":
            assert set(datos) == CLAVES_AGENTE and scope["kind"] == "corporate"
            assert datos["agent_name"] in m.CORPORATE_AGENTS
            _validar_estado(datos)
        elif evento == "stage_progress":
            assert CLAVES_ETAPA <= set(datos) <= CLAVES_ETAPA | m.ENTITY_META
            assert scope["kind"] == "person" and datos["research_source"] == scope["research_source"]
            assert datos["stage_id"] in m.PERSON_STAGES[scope["research_source"]]
            _validar_estado(datos)
        else:
            assert datos["provisional"] is True
            if scope["kind"] == "corporate":
                assert m.CORPORATE_SECTIONS[datos["section"]] == datos["agent_name"]
                assert datos["content"].strip()
            elif datos["section"] == "person_profiles":
                assert all(set(p) == CLAVES_PERFIL for p in datos["data"]["profiles"])
                assert datos["provenance"]["live_web_search"] is False
            else:
                assert datos["section"] in m.PERSON_MARKDOWN_SECTIONS
                assert datos["provenance"]["live_web_search"] is False

    final = fixture["snapshot_final"]
    assert final["result"] is None or "_progress" not in final["result"]
    for scope in final["progress"]["scopes"]:
        entidades = scope.get("agents") or scope.get("stages")
        assert all(e["status"] in m.TERMINAL_STATUSES for e in entidades), "el cierre no deja nada en curso"


@pytest.mark.parametrize("nombre", sorted(ESPERADAS))
def test_ningun_evento_de_progreso_lleva_datos_crudos_del_proveedor(nombre):
    eventos = [f for f in _fixture(nombre)["frames"] if f["event"] in EVENTOS_PROGRESO]
    texto = json.dumps(eventos)
    for prohibido in ("pdl-ficticio-1", "min_likelihood", "SELECT ", "Companies House no responde", "DeepSeek no responde"):
        assert prohibido not in texto


def test_web_publica_nunca_declara_etapas_de_busqueda():
    for nombre in ("personas-web-publica", "personas-web-publica-fallida"):
        etapas = {f["data"]["stage_id"] for f in _fixture(nombre)["frames"] if f["event"] == "stage_progress"}
        assert etapas <= set(m.PERSON_STAGES["gemini_web"])
        assert not any("search" in e or "pdl" in e for e in etapas)
