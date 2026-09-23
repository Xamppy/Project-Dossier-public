"""
Grafo LangGraph — dossier corporativo (UK + USA en paralelo → síntesis Gemini).

Topología: UK y US en paralelo desde START → síntesis (fan-in).

El alcance ``jurisdiction_scope`` evita mezclar datos cuando el usuario eligió solo
UK (Companies House) o solo USA (SEC) en el dashboard.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

JurisdictionScope = Literal["uk_only", "us_only", "dual"]

# Instrucciones de tono: el Markdown final va a clientes; no deben aparecer metadatos de ingeniería.
_CLIENT_EXECUTIVE_STYLE = (
    "Audiencia: cliente ejecutivo (riesgo, M&A, banca). **No** menciones marcas de productos de IA, APIs, "
    "nombres de proveedores (Lusha, Gemini, Google, etc.), registros por marca (Companies House, SEC, EDGAR, XBRL), "
    "«fragmentos» del archivo, ni limitaciones del software o del pipeline de generación. "
    "Usa lenguaje de negocio: «registro público», «información regulatoria», «cuentas auditadas», «presentaciones oficiales». "
    "Si falta información, formuladlo como vacío de negocio o pregunta a la contraparte (p. ej. solicitar "
    "documentación en data room), sin meta-comentarios sobre el origen técnico del dossier."
)

def infer_jurisdiction_scope(participantes: str) -> JurisdictionScope:
    """
    Deduce el alcance a partir del brief generado por la API (resolución explícita).

    - UK: texto con ``Companies House (número …)`` sin bloque SEC de resolución.
    - USA: ``emisor SEC (ticker …)`` sin número CH de resolución.
    """
    p = (participantes or "").strip()
    ch = bool(re.search(r"Companies House\s*\(\s*número", p, re.IGNORECASE))
    sec = bool(re.search(r"emisor\s+SEC\s*\(\s*ticker", p, re.IGNORECASE))
    if ch and not sec:
        return "uk_only"
    if sec and not ch:
        return "us_only"
    return "dual"


class CorporateDossierState(TypedDict, total=False):
    """Estado que circula por el grafo (campos opcionales salvo los de entrada)."""

    tema_reunion: str
    participantes: str
    descripcion: str
    jurisdiction_scope: JurisdictionScope
    output_language: str

    uk_corporate_context: str
    us_corporate_context: str

    final_dossier_markdown: str

    agent_errors: list[str]


def _node_agent_corporate_uk(state: CorporateDossierState) -> dict[str, Any]:
    """Agente UK (Companies House)."""
    scope = state.get("jurisdiction_scope", "dual")
    if scope == "us_only":
        bloque = (
            "## Reino Unido (Companies House)\n\n"
            "*No aplica: el brief corresponde a un **emisor estadounidense (SEC)**. "
            "No se consultó Companies House para no mezclar datos con una posible homónima en el Reino Unido.*\n"
        )
        logger.info("LangGraph agent_corporate_uk omitido (alcance SEC únicamente)")
        return {"uk_corporate_context": bloque}

    from dossier.services.corporate_registry_context import build_uk_corporate_context_markdown

    try:
        bloque = build_uk_corporate_context_markdown(state.get("participantes", "") or "")
    except Exception as e:
        logger.exception("Fallo agente UK (Companies House)")
        bloque = f"## Reino Unido (Companies House)\n\n*Error interno al construir contexto: {e}*\n"

    logger.info("LangGraph nodo agent_corporate_uk completado")
    return {"uk_corporate_context": bloque}


def _node_agent_corporate_usa(state: CorporateDossierState) -> dict[str, Any]:
    """Agente USA (SEC EDGAR)."""
    scope = state.get("jurisdiction_scope", "dual")
    if scope == "uk_only":
        bloque = (
            "## Estados Unidos (SEC EDGAR)\n\n"
            "*No aplica: el brief corresponde a una **empresa del Reino Unido (Companies House)**. "
            "No se consultó la SEC para no mezclar datos con una posible homónima en EE. UU.*\n"
        )
        logger.info("LangGraph agent_corporate_usa omitido (alcance UK únicamente)")
        return {"us_corporate_context": bloque}

    from dossier.services.corporate_registry_context import build_us_corporate_context_markdown

    try:
        bloque = build_us_corporate_context_markdown(state.get("participantes", "") or "")
    except Exception as e:
        logger.exception("Fallo agente USA (SEC)")
        bloque = f"## Estados Unidos (SEC EDGAR)\n\n*Error interno al construir contexto: {e}*\n"

    logger.info("LangGraph nodo agent_corporate_usa completado")
    return {"us_corporate_context": bloque}


def _node_synthesize_llm(state: CorporateDossierState) -> dict[str, Any]:
    """Síntesis LLM (DeepSeek) según alcance UK / US / dual."""
    from dossier.llm.text_generate import generate_text_with_llm
    from dossier.services.dossier_prompt_locales import (
        corporate_dossier_delivery_instructions,
        corporate_dual_scope_note,
    )
    from dossier.services.output_language import (
        apply_output_language_to_system_prompt,
        normalize_output_language,
    )

    tema = state.get("tema_reunion", "").strip()
    participantes = state.get("participantes", "").strip()
    descripcion = (state.get("descripcion") or "").strip()
    uk = state.get("uk_corporate_context", "").strip()
    us = state.get("us_corporate_context", "").strip()
    scope = state.get("jurisdiction_scope", "dual")
    output_language = normalize_output_language(state.get("output_language"))
    delivery = corporate_dossier_delivery_instructions(output_language)

    if scope == "uk_only":
        system = (
            "Eres un analista corporativo del Reino Unido. Redactas en español, en Markdown. "
            "Te basas **solo** en el contexto de **Companies House** (perfil, historial y, si existe, "
            "la lectura del formulario regulatorio incluida en el contexto). "
            "El bloque USA del mensaje indica explícitamente que no aplica: **no** lo uses como evidencia "
            "ni hagas comparativa transatlántica. No inventes hechos ajenos al contexto. "
            "Extensión total del dossier: **breve** (orientación: equivalente a ~1–1,5 páginas de texto como máximo). "
            + _CLIENT_EXECUTIVE_STYLE
        )
        user = f"""Preparación de reunión (solo **Reino Unido / Companies House**)

**Tema:** {tema}
**Brief / participantes:** {participantes}
**Descripción adicional:** {descripcion or "(ninguna)"}

---
### Contexto UK (Companies House)

{uk}

---
### Bloque USA (marcado como no aplicable por el sistema)

{us}

---
### Tu entrega

{delivery}
"""

    elif scope == "us_only":
        system = (
            "Eres un analista financiero-corporativo de emisores **estadounidenses**. Redactas en español, en Markdown. "
            "Te basas **solo** en el material del mensaje: tabla de presentaciones recientes ante la SEC, "
            "cifras estructuradas si aparecen, y la lectura del documento principal del emisor cuando exista. "
            "El bloque UK indica que no aplica: **no** lo uses ni hagas comparativa con Companies House. "
            "No inventes hechos ajenos al contexto. "
            "Extensión total del dossier: **breve** (orientación: equivalente a ~1–1,5 páginas de texto como máximo). "
            + _CLIENT_EXECUTIVE_STYLE
        )
        user = f"""Preparación de reunión (solo **Estados Unidos / SEC**)

**Tema:** {tema}
**Brief / participantes:** {participantes}
**Descripción adicional:** {descripcion or "(ninguna)"}

---
### Bloque UK (marcado como no aplicable por el sistema)

{uk}

---
### Contexto USA (información pública del emisor)

{us}

---
### Tu entrega

{delivery}
"""

    else:
        system = (
            "Eres un analista de inteligencia corporativa. Redactas en español, en Markdown. "
            "Recibes un bloque **UK (Companies House)** y otro **USA (SEC)** que pueden referirse a "
            "**entidades distintas** (homónimos, ADRs, etc.). "
            "**No** asumas que describen la misma empresa salvo que el brief del usuario lo indique de forma clara. "
            "Si un bloque es principalmente aviso de error o vacío, dilo y no lo compares como si fuera equivalente al otro. "
            "No inventes hechos no respaldados por el contexto. "
            "Extensión total del dossier: **breve** (orientación: equivalente a ~1,5–2 páginas como máximo en conjunto). "
            + _CLIENT_EXECUTIVE_STYLE
        )
        user = f"""Reunión a preparar (contexto **UK y USA** — tratarlos como fuentes independientes salvo indicación contraria en el brief)

**Tema:** {tema}
**Participantes / empresas (texto libre):** {participantes}
**Descripción adicional:** {descripcion or "(ninguna)"}

---
### Contexto UK (Companies House)

{uk}

---
### Contexto USA (información pública del emisor)

{us}

---
### Tu entrega

{corporate_dual_scope_note(output_language)}

{delivery}
"""

    system = apply_output_language_to_system_prompt(system, output_language)

    try:
        texto = generate_text_with_llm(user, system_instruction=system)
    except Exception as e:
        logger.exception("Fallo síntesis DeepSeek en LangGraph")
        err = f"Error en la síntesis del informe: {e}"
        return {
            "final_dossier_markdown": f"# Error en síntesis\n\n{err}",
            "agent_errors": [*state.get("agent_errors", []), err],
        }

    return {"final_dossier_markdown": texto}


def build_corporate_dossier_graph() -> StateGraph:
    graph = StateGraph(CorporateDossierState)
    graph.add_node("agent_corporate_uk", _node_agent_corporate_uk)
    graph.add_node("agent_corporate_usa", _node_agent_corporate_usa)
    graph.add_node("synthesize_llm", _node_synthesize_llm)

    graph.add_edge(START, "agent_corporate_uk")
    graph.add_edge(START, "agent_corporate_usa")
    graph.add_edge(["agent_corporate_uk", "agent_corporate_usa"], "synthesize_llm")
    graph.add_edge("synthesize_llm", END)
    return graph


def run_corporate_dossier_langgraph(
    tema_reunion: str,
    participantes: str,
    descripcion: str = "",
    jurisdiction_scope: JurisdictionScope | None = None,
    output_language: str = "es",
) -> str:
    """Compila el grafo, infiere alcance UK/US (o usa el explícito) y devuelve Markdown."""
    from dossier.services.output_language import normalize_output_language

    app = build_corporate_dossier_graph().compile()
    scope = jurisdiction_scope if jurisdiction_scope is not None else infer_jurisdiction_scope(participantes)
    logger.info("Corporate dossier jurisdiction_scope=%s output_language=%s", scope, output_language)
    result = app.invoke(
        {
            "tema_reunion": tema_reunion,
            "participantes": participantes,
            "descripcion": descripcion or "",
            "jurisdiction_scope": scope,
            "output_language": normalize_output_language(output_language),
            "agent_errors": [],
        }
    )
    return str(result.get("final_dossier_markdown") or "").strip()
