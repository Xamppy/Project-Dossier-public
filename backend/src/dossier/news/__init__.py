"""Cliente y agente de noticias (GDELT DOC 2.0, NewsAPI). Ver ADR 0004, S3.1/S3.2."""
from dossier.news.agent import (
    FalloProveedor,
    ResultadoRecoleccionPrensa,
    collect_press_mentions,
)

__all__ = [
    "FalloProveedor",
    "ResultadoRecoleccionPrensa",
    "collect_press_mentions",
]
