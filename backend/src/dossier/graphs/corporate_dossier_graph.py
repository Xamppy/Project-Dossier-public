"""
Grafo LangGraph — dossier corporativo (spec S0.12).

Topología: UK, USA, Europa (FR/DE) y prensa en paralelo desde START → síntesis (fan-in).

El alcance ``jurisdiction_scope`` evita mezclar datos cuando el usuario eligió solo
UK (Companies House) o solo USA (SEC) en el dashboard. Europa y prensa necesitan
``empresa_objetivo`` (nombre limpio); sin él se omiten y el grafo se comporta como antes.
"""
from __future__ import annotations

import logging
import operator
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)

# "dual" = sin registro elegido: corren UK, USA y Europa. "eu_only" = solo Europa.
JurisdictionScope = Literal["uk_only", "us_only", "dual", "eu_only"]

# Tope de menciones de prensa que se pasan al LLM (el agente puede traer cientos).
MAX_MENCIONES_PROMPT = 15

_NOTA_FUENTES_ADICIONALES = (
    " Si el mensaje incluye registros mercantiles europeos o menciones de prensa, úsalos como "
    "fuentes adicionales. Las menciones de prensa pueden referirse a homónimos: no las atribuyas "
    "a la empresa sin una coincidencia clara de nombre y contexto."
)

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
    # Nombre limpio de la empresa para Europa y prensa (el brief es texto libre con marcas).
    empresa_objetivo: str

    uk_corporate_context: str
    us_corporate_context: str
    eu_corporate_context: str
    news_context: str

    final_dossier_markdown: str

    agent_errors: list[str]

    # Reducer `operator.add`: UK y USA corren en paralelo (mismo superpaso) y cada uno
    # escribe su propia entrada; sin reducer, LangGraph rechaza dos escrituras concurrentes
    # a la misma clave de estado (CA2 de S0.12).
    agents_failed: Annotated[list[str], operator.add]
    agents_succeeded: Annotated[list[str], operator.add]
    # Fuera de alcance: no consultaron la red (CA3 de S0.12).
    agents_skipped: Annotated[list[str], operator.add]


def _node_agent_corporate_uk(state: CorporateDossierState) -> dict[str, Any]:
    """Agente UK (Companies House)."""
    scope = state.get("jurisdiction_scope", "dual")
    if scope in ("us_only", "eu_only"):
        origen = "un **emisor estadounidense (SEC)**" if scope == "us_only" else "una **empresa europea**"
        bloque = (
            "## Reino Unido (Companies House)\n\n"
            f"*No aplica: el brief corresponde a {origen}. "
            "No se consultó Companies House para no mezclar datos con una posible homónima en el Reino Unido.*\n"
        )
        logger.info("LangGraph agent_corporate_uk omitido (alcance %s)", scope)
        return {"uk_corporate_context": bloque, "agents_skipped": ["agent_corporate_uk"]}

    from dossier.services.corporate_registry_context import build_uk_corporate_context_markdown

    try:
        bloque = build_uk_corporate_context_markdown(state.get("participantes", "") or "")
    except Exception as e:
        logger.exception("Fallo agente UK (Companies House)")
        bloque = f"## Reino Unido (Companies House)\n\n*Error interno al construir contexto: {e}*\n"
        logger.info("LangGraph nodo agent_corporate_uk falló")
        return {"uk_corporate_context": bloque, "agents_failed": ["agent_corporate_uk"]}

    logger.info("LangGraph nodo agent_corporate_uk completado")
    return {"uk_corporate_context": bloque, "agents_succeeded": ["agent_corporate_uk"]}


def _node_agent_corporate_usa(state: CorporateDossierState) -> dict[str, Any]:
    """Agente USA (SEC EDGAR)."""
    scope = state.get("jurisdiction_scope", "dual")
    if scope in ("uk_only", "eu_only"):
        origen = (
            "una **empresa del Reino Unido (Companies House)**"
            if scope == "uk_only"
            else "una **empresa europea**"
        )
        bloque = (
            "## Estados Unidos (SEC EDGAR)\n\n"
            f"*No aplica: el brief corresponde a {origen}. "
            "No se consultó la SEC para no mezclar datos con una posible homónima en EE. UU.*\n"
        )
        logger.info("LangGraph agent_corporate_usa omitido (alcance %s)", scope)
        return {"us_corporate_context": bloque, "agents_skipped": ["agent_corporate_usa"]}

    from dossier.services.corporate_registry_context import build_us_corporate_context_markdown

    try:
        bloque = build_us_corporate_context_markdown(state.get("participantes", "") or "")
    except Exception as e:
        logger.exception("Fallo agente USA (SEC)")
        bloque = f"## Estados Unidos (SEC EDGAR)\n\n*Error interno al construir contexto: {e}*\n"
        logger.info("LangGraph nodo agent_corporate_usa falló")
        return {"us_corporate_context": bloque, "agents_failed": ["agent_corporate_usa"]}

    logger.info("LangGraph nodo agent_corporate_usa completado")
    return {"us_corporate_context": bloque, "agents_succeeded": ["agent_corporate_usa"]}


def _palabras(texto: str) -> set[str]:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return set(re.findall(r"[a-z0-9]+", sin_tildes.lower()))


def _coincide_con_empresa(razon_social: str, empresa: str) -> bool:
    """La búsqueda europea es difusa: exige que la razón social contenga todas las palabras buscadas.

    ponytail: coincidencia por palabras; un filtro de homónimos con más señales es S3.3.
    """
    buscadas = _palabras(empresa)
    return bool(buscadas) and buscadas <= _palabras(razon_social)


def _registro_europeo_markdown(cita: Any) -> str:
    r = cita.record
    datos = [
        f"jurisdicción {r.jurisdiccion.value.upper()}",
        f"identificador {r.identificador_registro}",
        f"estado {r.estado}" if r.estado else "",
        r.forma_juridica or "",
        f"constituida {r.fecha_constitucion}" if r.fecha_constitucion else "",
    ]
    linea = f"- **{r.razon_social}** ({', '.join(d for d in datos if d)})"
    if r.domicilio and (r.domicilio.localidad or r.domicilio.pais):
        linea += f"\n  Domicilio: {', '.join(p for p in (r.domicilio.localidad, r.domicilio.pais) if p)}"
    if r.directivos:
        linea += "\n  Directivos: " + ", ".join(d.nombre for d in r.directivos[:5])
    if r.url_fuente:
        linea += f"\n  Registro: {r.url_fuente}"
    return linea


def _node_agent_corporate_eu(state: CorporateDossierState) -> dict[str, Any]:
    """Agente Europa (registros FR/DE). Se omite si el usuario ya eligió un registro UK o US."""
    scope = state.get("jurisdiction_scope", "dual")
    empresa = (state.get("empresa_objetivo") or "").strip()
    if scope in ("uk_only", "us_only") or not empresa:
        logger.info("LangGraph agent_corporate_eu omitido (alcance %s)", scope)
        return {"eu_corporate_context": "", "agents_skipped": ["agent_corporate_eu"]}

    from dossier.eu_registry import agent as agente_europeo

    try:
        resultado = agente_europeo.run_eu_registry_agent(empresa)
    except Exception as e:
        logger.exception("Fallo agente Europa (registros FR/DE)")
        bloque = f"## Registros mercantiles europeos\n\n*Error interno al consultar: {e}*\n"
        return {"eu_corporate_context": bloque, "agents_failed": ["agent_corporate_eu"]}

    if resultado.errores and not resultado.citas:
        bloque = "## Registros mercantiles europeos\n\n*No se pudieron consultar los registros europeos.*\n"
        return {"eu_corporate_context": bloque, "agents_failed": ["agent_corporate_eu"]}

    lineas = [
        _registro_europeo_markdown(c)
        for c in resultado.citas
        if _coincide_con_empresa(c.record.razon_social, empresa)
    ]
    cuerpo = "\n".join(lineas) or "*Sin coincidencias en los registros europeos consultados.*"
    if resultado.errores:
        cuerpo += "\n\n*Sin respuesta de: " + ", ".join(sorted(resultado.errores)).upper() + ".*"
    logger.info("LangGraph nodo agent_corporate_eu completado (%d registros)", len(lineas))
    return {
        "eu_corporate_context": f"## Registros mercantiles europeos\n\n{cuerpo}\n",
        "agents_succeeded": ["agent_corporate_eu"],
    }


def _node_agent_news(state: CorporateDossierState) -> dict[str, Any]:
    """Agente de prensa (GDELT y NewsAPI). Corre en cualquier alcance si hay empresa."""
    empresa = (state.get("empresa_objetivo") or "").strip()
    if not empresa:
        return {"news_context": "", "agents_skipped": ["agent_news"]}

    from dossier.news import agent as agente_noticias

    try:
        resultado = agente_noticias.collect_press_mentions(empresa)
    except Exception as e:
        logger.exception("Fallo agente de prensa")
        return {
            "news_context": f"## Menciones de prensa recientes\n\n*Error interno al consultar: {e}*\n",
            "agents_failed": ["agent_news"],
        }

    if not resultado.mentions and len(resultado.failed_providers) >= 2:
        bloque = "## Menciones de prensa recientes\n\n*No se pudo consultar la prensa.*\n"
        return {"news_context": bloque, "agents_failed": ["agent_news"]}

    lineas = []
    for m in resultado.mentions[:MAX_MENCIONES_PROMPT]:
        fecha = f", {m.published_date}" if m.published_date else ""
        lineas.append(f"- **{m.headline}** — {m.publisher}{fecha}. {m.summary} ({m.url})")
    cuerpo = "\n".join(lineas) or "*Sin menciones de prensa recientes.*"
    logger.info("LangGraph nodo agent_news completado (%d menciones)", len(lineas))
    return {
        "news_context": f"## Menciones de prensa recientes\n\n{cuerpo}\n",
        "agents_succeeded": ["agent_news"],
    }


def _contexto_adicional(state: CorporateDossierState) -> str:
    """Bloques de Europa y prensa para el mensaje de síntesis (vacío si no hay)."""
    bloques = [
        (state.get("eu_corporate_context") or "").strip(),
        (state.get("news_context") or "").strip(),
    ]
    return "".join(f"---\n{b}\n\n" for b in bloques if b)


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
    extra = _contexto_adicional(state)

    if scope == "eu_only":
        system = (
            "Eres un analista corporativo de empresas de **Europa continental**. Redactas en español, en Markdown. "
            "Te basas en los registros mercantiles europeos y, si las hay, en las menciones de prensa del mensaje. "
            "Los bloques UK y USA indican que no aplican: **no** los uses. No inventes hechos ajenos al contexto. "
            "Extensión total del dossier: **breve** (orientación: equivalente a ~1–1,5 páginas de texto como máximo). "
            + _CLIENT_EXECUTIVE_STYLE
        )
        user = f"""Preparación de reunión (**Europa continental**)

**Tema:** {tema}
**Brief / participantes:** {participantes}
**Descripción adicional:** {descripcion or "(ninguna)"}

---
### Bloques UK y USA (marcados como no aplicables por el sistema)

{uk}

{us}

{extra}---
### Tu entrega

{delivery}
"""

    elif scope == "uk_only":
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

{extra}---
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

{extra}---
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

{extra}---
### Tu entrega

{corporate_dual_scope_note(output_language)}

{delivery}
"""

    if extra:
        system += _NOTA_FUENTES_ADICIONALES
    system = apply_output_language_to_system_prompt(system, output_language)

    try:
        texto = generate_text_with_llm(user, system_instruction=system)
    except Exception as e:
        logger.exception("Fallo síntesis DeepSeek en LangGraph")
        err = f"Error en la síntesis del informe: {e}"
        return {
            "final_dossier_markdown": f"# Error en síntesis\n\n{err}",
            "agent_errors": [*state.get("agent_errors", []), err],
            "agents_failed": ["synthesize_llm"],
        }

    return {"final_dossier_markdown": texto, "agents_succeeded": ["synthesize_llm"]}


def build_corporate_dossier_graph() -> StateGraph:
    graph = StateGraph(CorporateDossierState)
    graph.add_node("agent_corporate_uk", _node_agent_corporate_uk)
    graph.add_node("agent_corporate_usa", _node_agent_corporate_usa)
    graph.add_node("agent_corporate_eu", _node_agent_corporate_eu)
    graph.add_node("agent_news", _node_agent_news)
    graph.add_node("synthesize_llm", _node_synthesize_llm)

    agentes = ["agent_corporate_uk", "agent_corporate_usa", "agent_corporate_eu", "agent_news"]
    for agente in agentes:
        graph.add_edge(START, agente)
    graph.add_edge(agentes, "synthesize_llm")
    graph.add_edge("synthesize_llm", END)
    return graph


@dataclass(frozen=True)
class CorporateDossierResult:
    """Markdown final más la telemetría de qué agentes fallaron o completaron (CA2 de S0.12)."""

    markdown: str
    agents_failed: list[str]
    agents_succeeded: list[str]
    agents_skipped: list[str] = field(default_factory=list)


def run_corporate_dossier_langgraph_detailed(
    tema_reunion: str,
    participantes: str,
    descripcion: str = "",
    jurisdiction_scope: JurisdictionScope | None = None,
    output_language: str = "es",
    empresa_objetivo: str | None = None,
) -> CorporateDossierResult:
    """Compila el grafo, infiere alcance UK/US (o usa el explícito) y devuelve Markdown + agentes fallidos."""
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
            "empresa_objetivo": (empresa_objetivo or "").strip(),
            "agent_errors": [],
            "agents_failed": [],
            "agents_succeeded": [],
            "agents_skipped": [],
        }
    )
    markdown = str(result.get("final_dossier_markdown") or "").strip()
    agents_failed = list(result.get("agents_failed") or [])
    if agents_failed:
        logger.warning("Corporate dossier con agentes fallidos: %s", agents_failed)
    return CorporateDossierResult(
        markdown=markdown,
        agents_failed=agents_failed,
        agents_succeeded=list(result.get("agents_succeeded") or []),
        agents_skipped=list(result.get("agents_skipped") or []),
    )


def run_corporate_dossier_langgraph(
    tema_reunion: str,
    participantes: str,
    descripcion: str = "",
    jurisdiction_scope: JurisdictionScope | None = None,
    output_language: str = "es",
    empresa_objetivo: str | None = None,
) -> str:
    """Compatibilidad hacia atrás: solo el Markdown final.

    Ver ``run_corporate_dossier_langgraph_detailed`` para obtener también qué agentes
    fallaron (``agents_failed``); esta función existe porque hay llamadores que solo
    esperan el ``str`` (p. ej. ``api/dossier_routes.py``).
    """
    return run_corporate_dossier_langgraph_detailed(
        tema_reunion,
        participantes,
        descripcion,
        jurisdiction_scope,
        output_language,
        empresa_objetivo,
    ).markdown
