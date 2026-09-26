"""S4.2, integración: el análisis de persona produce el payload estructurado.

Recorre el armado real de prompts (datos investigados, contexto de reunión,
idioma) más la síntesis estructurada; solo el proveedor LLM es un doble.
"""
from __future__ import annotations

import json

from dossier.schemas.dossier_executive_payload import DossierExecutivePayload
from dossier.services.person_dossier_locales import person_bundle_user_instructions
from dossier.services.person_gemini_analysis import analyze_person_profile_bundle_structured

FILTROS = {"full_name": "Ana Prueba", "company": "Empresa de Prueba SA", "country": "Chile"}
PERFILES = [{"full_name": "Ana Prueba", "job_title": "Gerente general", "linkedin_url": "https://example.test/ana"}]
REUNION = {"title": "Revisión trimestral", "start": "2026-10-01T15:00:00Z"}


def _respuesta_valida() -> str:
    return json.dumps(
        {
            "meeting_context": REUNION,
            "executive_summary": "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
            "participants": [{"name": "Ana Prueba"}],
            "conversation_starters": [
                {
                    "topic": "Expansión",
                    "rationale": "Mencionada en su perfil.",
                    "suggested_opener": "¿Cómo va la expansión?",
                }
            ],
        },
        ensure_ascii=False,
    )


def test_analisis_de_persona_devuelve_payload_con_los_datos_investigados_en_el_prompt(llm_falso):
    llm = llm_falso(_respuesta_valida())

    payload = analyze_person_profile_bundle_structured(
        filters=FILTROS,
        profiles=PERFILES,
        posts_by_url={},
        meeting_context=REUNION,
        output_language="es",
    )

    assert isinstance(payload, DossierExecutivePayload)
    assert payload.conversation_starters[0].topic == "Expansión"

    llamada = llm.llamadas[0]
    assert llamada["json_mode"] is True
    assert "Ana Prueba" in llamada["prompt"]
    assert "https://example.test/ana" in llamada["prompt"]
    assert "Revisión trimestral" in llamada["prompt"]


def test_prompts_estructurados_no_arrastran_el_formato_del_informe_markdown(llm_falso):
    """Probado contra DeepSeek real (2026-09-26): con las instrucciones de secciones
    Markdown en el prompt, el modelo devolvía el JSON Schema copiado seguido del
    informe en Markdown, incluso en modo ``json_object``."""
    llm = llm_falso(_respuesta_valida())

    analyze_person_profile_bundle_structured(
        filters=FILTROS, profiles=PERFILES, posts_by_url={}, enrichment_provider="pdl"
    )

    llamada = llm.llamadas[0]
    assert person_bundle_user_instructions("es", "PDL") not in llamada["prompt"]
    assert "###" not in llamada["system"]
    assert "JSON" in llamada["system"]


def test_idioma_de_salida_llega_a_la_sintesis_estructurada(llm_falso):
    llm = llm_falso(_respuesta_valida())

    analyze_person_profile_bundle_structured(
        filters=FILTROS, profiles=PERFILES, posts_by_url={}, output_language="en"
    )

    llamada = llm.llamadas[0]
    assert "English" in llamada["system"]
    # Probado contra DeepSeek real: con la directiva solo en el sistema, el
    # contenido salía en español. Debe cerrar también el mensaje de usuario.
    assert "English" in llamada["prompt"]


def test_el_analisis_markdown_existente_no_cambia(monkeypatch):
    """S4.2 agrega la variante estructurada; el camino Markdown lo sustituye S4.3."""
    capturado: dict = {}

    def _generar(prompt, *, system_instruction=None, **_):
        capturado["system"] = system_instruction
        return "# Informe"

    monkeypatch.setattr("dossier.services.person_gemini_analysis.generate_text_with_llm", _generar)

    from dossier.services.person_gemini_analysis import analyze_person_profile_bundle

    salida = analyze_person_profile_bundle(filters=FILTROS, profiles=PERFILES, posts_by_url={})

    assert salida == "# Informe"
    assert "JSON Schema" not in capturado["system"]
