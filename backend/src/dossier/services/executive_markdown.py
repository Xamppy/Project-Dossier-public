"""Markdown legible generado por código desde ``DossierExecutivePayload`` (S4.3).

El dashboard lee ``dossier_data.body``: renderizarlo desde el payload evita una
segunda llamada al LLM y mantiene el informe consistente con los datos validados.
"""
from __future__ import annotations

from typing import Any

from dossier.schemas.dossier_executive_payload import DossierExecutivePayload, SourceCitation
from dossier.services.output_language import normalize_output_language

_TITULOS: dict[str, dict[str, Any]] = {
    "es": {
        "summary": "Resumen ejecutivo",
        "career": "Trayectoria profesional",
        "alerts": "Alertas de riesgo",
        "press": "Menciones de prensa",
        "starters": "Ideas para iniciar la conversación",
        "sources": "Fuentes consultadas",
        "current": "actual",
        "severity": {"low": "baja", "medium": "media", "high": "alta"},
    },
    "en": {
        "summary": "Executive summary",
        "career": "Career history",
        "alerts": "Risk alerts",
        "press": "Press mentions",
        "starters": "Conversation starters",
        "sources": "Sources consulted",
        "current": "present",
        "severity": {"low": "low", "medium": "medium", "high": "high"},
    },
    "pt": {
        "summary": "Resumo executivo",
        "career": "Trajetória profissional",
        "alerts": "Alertas de risco",
        "press": "Menções na imprensa",
        "starters": "Ideias para iniciar a conversa",
        "sources": "Fontes consultadas",
        "current": "atual",
        "severity": {"low": "baixa", "medium": "média", "high": "alta"},
    },
    "it": {
        "summary": "Sintesi esecutiva",
        "career": "Percorso professionale",
        "alerts": "Segnali di rischio",
        "press": "Menzioni sulla stampa",
        "starters": "Spunti per avviare la conversazione",
        "sources": "Fonti consultate",
        "current": "attuale",
        "severity": {"low": "bassa", "medium": "media", "high": "alta"},
    },
    "fr": {
        "summary": "Synthèse",
        "career": "Parcours professionnel",
        "alerts": "Alertes de risque",
        "press": "Mentions dans la presse",
        "starters": "Idées pour engager la conversation",
        "sources": "Sources consultées",
        "current": "actuel",
        "severity": {"low": "faible", "medium": "moyenne", "high": "élevée"},
    },
    "de": {
        "summary": "Zusammenfassung",
        "career": "Beruflicher Werdegang",
        "alerts": "Risikohinweise",
        "press": "Presseerwähnungen",
        "starters": "Gesprächseinstiege",
        "sources": "Verwendete Quellen",
        "current": "heute",
        "severity": {"low": "niedrig", "medium": "mittel", "high": "hoch"},
    },
}


def _enlace(texto: str, url: str | None) -> str:
    return f"[{texto}]({url})" if url else texto


def _fuente(cita: SourceCitation) -> str:
    return _enlace(cita.source_name, cita.url)


def render_executive_markdown(payload: DossierExecutivePayload, output_language: str) -> str:
    t = _TITULOS.get(normalize_output_language(output_language), _TITULOS["es"])
    partes = [f"## {t['summary']}\n\n{payload.executive_summary}"]

    if payload.career_trajectory:
        lineas = []
        for c in payload.career_trajectory:
            fin = t["current"] if c.is_current else (c.end_date or "")
            periodo = " – ".join(p for p in (c.start_date or "", fin) if p)
            lineas.append(
                f"- **{c.role_title}**, {c.company_name}" + (f" ({periodo})" if periodo else "")
            )
        partes.append(f"## {t['career']}\n\n" + "\n".join(lineas))

    if payload.risk_alerts:
        lineas = [
            f"- **{a.title}** ({t['severity'][a.severity.value]}): {a.description}"
            + (f" — {', '.join(_fuente(s) for s in a.sources)}" if a.sources else "")
            for a in payload.risk_alerts
        ]
        partes.append(f"## {t['alerts']}\n\n" + "\n".join(lineas))

    if payload.press_mentions:
        lineas = [
            f"- **{m.headline}** — {_enlace(m.publisher, m.url)}"
            + (f", {m.published_date}" if m.published_date else "")
            + f"\n  {m.summary}"
            for m in payload.press_mentions
        ]
        partes.append(f"## {t['press']}\n\n" + "\n".join(lineas))

    if payload.conversation_starters:
        lineas = [
            f"- **{c.topic}**: «{c.suggested_opener}»\n  {c.rationale}"
            for c in payload.conversation_starters
        ]
        partes.append(f"## {t['starters']}\n\n" + "\n".join(lineas))

    fuentes = list(dict.fromkeys(_fuente(s) for s in payload.data_sources_used))
    partes.append(f"## {t['sources']}\n\n" + ("\n".join(f"- {f}" for f in fuentes) or "-"))

    return "\n\n".join(partes) + "\n"
