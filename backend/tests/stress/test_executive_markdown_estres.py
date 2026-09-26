"""Pruebas de estrés - S4.3: Markdown derivado del payload.

Ver docs/dev/testing-policy.md §4. La degradación del proveedor (caído o con
JSON inválido) está en tests/integration/test_person_research_structured.py.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from dossier.schemas.dossier_executive_payload import (
    DossierExecutivePayload,
    PressMention,
    SourceCitation,
    SourceType,
)
from dossier.services.executive_markdown import render_executive_markdown

_CITA = SourceCitation(
    source_type=SourceType.gdelt_news,
    source_name="GDELT",
    retrieved_at=datetime(2026, 9, 26, tzinfo=UTC),
)


def _payload(n_menciones: int, resumen: str = "Resumen ejecutivo de volumen.") -> DossierExecutivePayload:
    return DossierExecutivePayload(
        meeting_context={},
        executive_summary=resumen,
        participants=[],
        conversation_starters=[],
        press_mentions=[
            PressMention(
                headline=f"Titular {i}",
                publisher="Diario",
                summary="Resumen.",
                url=f"https://example.test/{i}",
                source=_CITA,
            )
            for i in range(n_menciones)
        ],
    )


def test_volumen_mil_menciones_se_renderizan_rapido_y_completas():
    payload = _payload(1_000)

    inicio = time.perf_counter()
    md = render_executive_markdown(payload, "es")
    transcurrido = time.perf_counter() - inicio

    assert transcurrido < 1.0, f"render de 1000 menciones tardó {transcurrido:.2f}s"
    assert "Titular 999" in md


def test_concurrencia_renders_paralelos_no_se_mezclan():
    payloads = [_payload(5, resumen=f"Resumen del sujeto {i} con largo suficiente.") for i in range(40)]

    with ThreadPoolExecutor(max_workers=10) as pool:
        salidas = list(pool.map(lambda p: render_executive_markdown(p, "es"), payloads))

    for i, md in enumerate(salidas):
        assert f"sujeto {i} " in md
