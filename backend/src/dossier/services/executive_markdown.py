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
        "recommendation": "Conclusión y recomendación",
        "confidence": "Nivel de confianza",
        "overall_risk": "Riesgo global",
        "decision_label": "Recomendación",
        "key_findings": "Hallazgos clave",
        "next_steps": "Próximos pasos",
        "risk_levels": {"low": "bajo", "medium": "medio", "high": "alto", "critical": "crítico"},
        "decisions": {"proceed": "Proceder", "proceed_with_caution": "Proceder con cautela", "escalate_legal_review": "Escalar a revisión legal", "do_not_proceed": "No proceder"},
        "confidence_levels": {"high_confidence": "Alta confianza", "medium_confidence": "Confianza media", "low_confidence": "Baja confianza", "inferences": "Inferencias"},
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
        "recommendation": "Conclusion and recommendation",
        "confidence": "Confidence level",
        "overall_risk": "Overall risk",
        "decision_label": "Recommendation",
        "key_findings": "Key findings",
        "next_steps": "Next steps",
        "risk_levels": {"low": "low", "medium": "medium", "high": "high", "critical": "critical"},
        "decisions": {"proceed": "Proceed", "proceed_with_caution": "Proceed with caution", "escalate_legal_review": "Escalate to legal review", "do_not_proceed": "Do not proceed"},
        "confidence_levels": {"high_confidence": "High confidence", "medium_confidence": "Medium confidence", "low_confidence": "Low confidence", "inferences": "Inferences"},
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
        "recommendation": "Conclusão e recomendação",
        "confidence": "Nível de confiança",
        "overall_risk": "Risco global",
        "decision_label": "Recomendação",
        "key_findings": "Principais constatações",
        "next_steps": "Próximos passos",
        "risk_levels": {"low": "baixo", "medium": "médio", "high": "alto", "critical": "crítico"},
        "decisions": {"proceed": "Prosseguir", "proceed_with_caution": "Prosseguir com cautela", "escalate_legal_review": "Encaminhar para revisão jurídica", "do_not_proceed": "Não prosseguir"},
        "confidence_levels": {"high_confidence": "Alta confiança", "medium_confidence": "Confiança média", "low_confidence": "Baixa confiança", "inferences": "Inferências"},
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
        "recommendation": "Conclusione e raccomandazione",
        "confidence": "Livello di affidabilità",
        "overall_risk": "Rischio complessivo",
        "decision_label": "Raccomandazione",
        "key_findings": "Risultati principali",
        "next_steps": "Prossimi passi",
        "risk_levels": {"low": "basso", "medium": "medio", "high": "alto", "critical": "critico"},
        "decisions": {"proceed": "Procedere", "proceed_with_caution": "Procedere con cautela", "escalate_legal_review": "Sottoporre a revisione legale", "do_not_proceed": "Non procedere"},
        "confidence_levels": {"high_confidence": "Alta affidabilità", "medium_confidence": "Affidabilità media", "low_confidence": "Bassa affidabilità", "inferences": "Inferenze"},
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
        "recommendation": "Conclusion et recommandation",
        "confidence": "Niveau de confiance",
        "overall_risk": "Risque global",
        "decision_label": "Recommandation",
        "key_findings": "Constats clés",
        "next_steps": "Prochaines étapes",
        "risk_levels": {"low": "faible", "medium": "moyen", "high": "élevé", "critical": "critique"},
        "decisions": {"proceed": "Poursuivre", "proceed_with_caution": "Poursuivre avec prudence", "escalate_legal_review": "Soumettre à un examen juridique", "do_not_proceed": "Ne pas poursuivre"},
        "confidence_levels": {"high_confidence": "Confiance élevée", "medium_confidence": "Confiance moyenne", "low_confidence": "Confiance faible", "inferences": "Déductions"},
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
        "recommendation": "Fazit und Empfehlung",
        "confidence": "Verlässlichkeit",
        "overall_risk": "Gesamtrisiko",
        "decision_label": "Empfehlung",
        "key_findings": "Wichtigste Erkenntnisse",
        "next_steps": "Nächste Schritte",
        "risk_levels": {"low": "niedrig", "medium": "mittel", "high": "hoch", "critical": "kritisch"},
        "decisions": {"proceed": "Fortfahren", "proceed_with_caution": "Mit Vorsicht fortfahren", "escalate_legal_review": "Rechtlich prüfen lassen", "do_not_proceed": "Nicht fortfahren"},
        "confidence_levels": {"high_confidence": "Hohe Verlässlichkeit", "medium_confidence": "Mittlere Verlässlichkeit", "low_confidence": "Geringe Verlässlichkeit", "inferences": "Schlussfolgerungen"},
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


def _vinetas(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


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

    if payload.final_recommendation:
        r = payload.final_recommendation
        bloque = (
            f"**{t['decision_label']}: {t['decisions'][r.decision.value]}** · "
            f"{t['overall_risk']}: {t['risk_levels'][r.overall_risk.value]}"
        )
        if r.key_findings:
            bloque += f"\n\n**{t['key_findings']}**\n" + _vinetas(r.key_findings)
        if r.next_steps:
            bloque += f"\n\n**{t['next_steps']}**\n" + _vinetas(r.next_steps)
        partes.append(f"## {t['recommendation']}\n\n{bloque}")

    if payload.confidence_assessment:
        confianza = payload.confidence_assessment
        niveles = [
            f"**{t['confidence_levels'][nivel]}**\n" + _vinetas(datos)
            for nivel, datos in (
                ("high_confidence", confianza.high_confidence),
                ("medium_confidence", confianza.medium_confidence),
                ("low_confidence", confianza.low_confidence),
                ("inferences", confianza.inferences),
            )
            if datos
        ]
        if niveles:
            partes.append(f"## {t['confidence']}\n\n" + "\n\n".join(niveles))

    fuentes = list(dict.fromkeys(_fuente(s) for s in payload.data_sources_used))
    partes.append(f"## {t['sources']}\n\n" + ("\n".join(f"- {f}" for f in fuentes) or "-"))

    return "\n\n".join(partes) + "\n"
