"""Búsqueda de empresas para desambiguar nombres (UK Companies House + SEC tickers)."""
from __future__ import annotations

import logging
import os
import re
import time
from functools import lru_cache
from typing import Any

import requests

from dossier.companies_house.cli import filter_and_sort_items, search_companies
from dossier.config import load_env
from dossier.sec_edgar.user_agent import sec_request_headers

logger = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


@lru_cache(maxsize=1)
def _load_sec_company_rows() -> tuple[dict[str, Any], ...]:
    """Índice SEC (ticker, title, cik_str); se cachea en memoria por proceso."""
    headers = sec_request_headers()
    r = requests.get(SEC_TICKERS_URL, headers=headers, timeout=60)
    r.raise_for_status()
    time.sleep(0.1)
    data = r.json()
    return tuple(data.values())


def _normalize_sec_compare(s: str) -> str:
    """Quita puntuación para comparar nombres (p. ej. «Tesla Inc» vs «Tesla, Inc.»)."""
    return " ".join(re.sub(r"[^\w\s]", " ", (s or "").lower()).split())


def _sec_search_candidates(query: str) -> list[str]:
    """Variantes del texto para resolver ticker/CIK (asuntos de calendario, briefs libres)."""
    q = (query or "").strip()
    if not q:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        s = s.strip()
        if len(s) >= 2 and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)

    add(q)
    if "." in q:
        add(q.split(".", 1)[0])
    norm = " ".join(_normalize_sec_compare(q).split())
    add(norm)
    for pat in (
        r"(?i)^(?:reunión|reunion|demo|llamada|call|meeting)\s+(?:comercial|estratégica|estadategica|producto|con|de)\s+(.+)$",
        r"(?i)^(?:reunión|reunion|meeting|call)\s+con\s+(.+)$",
        r"(?i)^(?:reunión|reunion|meeting|call)\s+with\s+(.+)$",
    ):
        m = re.match(pat, q)
        if m:
            add(m.group(1).strip())
    stop = {
        "reunión", "reunion", "meeting", "call", "demo", "comercial", "con", "de", "the", "inc",
        "corp", "ltd", "llc", "plc", "sa", "ag",
    }
    for word in re.findall(r"\w{3,}", q):
        if word.lower() not in stop:
            add(word)
    return out


def find_sec_matches(query: str, limit: int = 30) -> list[dict[str, Any]]:
    """Coincidencias en el listado de tickers SEC (nombre o ticker)."""
    companies = list(_load_sec_company_rows())
    for cand in _sec_search_candidates(query):
        q = cand.strip().lower()
        if len(q) < 2:
            continue
        for c in companies:
            if str(c["ticker"]).lower() == q:
                return [_normalize_sec_row(c)]
        qnorm = _normalize_sec_compare(cand)
        for c in companies:
            title_norm = _normalize_sec_compare(str(c.get("title", "")))
            if qnorm == title_norm or qnorm in title_norm or title_norm.startswith(qnorm):
                return [_normalize_sec_row(c)]
        for c in companies:
            if str(c["title"]).lower() == q:
                return [_normalize_sec_row(c)]
        hits = [
            _normalize_sec_row(c)
            for c in companies
            if q in str(c["title"]).lower() or q in str(c["ticker"]).lower()
        ]
        if hits:
            return hits[:limit]
    return []


def _normalize_sec_row(c: dict[str, Any]) -> dict[str, Any]:
    cik = str(c.get("cik_str", "")).strip()
    if cik.isdigit():
        cik = cik.zfill(10)
    return {
        "ticker": str(c.get("ticker", "")).strip(),
        "title": str(c.get("title", "")).strip(),
        "cik": cik,
    }


def find_companies_house_matches(query: str, limit: int = 20) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Búsqueda en Companies House. Si falta API key, devuelve lista vacía y aviso.
    """
    warnings: list[str] = []
    load_env()

    key = (os.getenv("COMPANIES_HOUSE_API_KEY") or "").strip()
    if not key:
        warnings.append("missing_companies_house_api_key")
        return [], warnings

    auth = (key, "")
    try:
        raw = search_companies(query, auth)
    except requests.RequestException as e:
        logger.warning("Companies House search failed: %s", e)
        warnings.append("companies_house_request_failed")
        return [], warnings

    items = raw.get("items") or []
    sorted_items, _strict = filter_and_sort_items(items, query)
    out: list[dict[str, Any]] = []
    for it in sorted_items[:limit]:
        out.append(
            {
                "company_number": str(it.get("company_number") or "").strip(),
                "title": str(it.get("title") or "").strip(),
                "company_status": str(it.get("company_status") or "").strip(),
                "company_type": str(it.get("company_type") or "").strip(),
            }
        )
    return out, warnings


def search_corporate_company_candidates(query: str, *, uk_limit: int = 20, us_limit: int = 30) -> dict[str, Any]:
    """
    Resultado unificado para el dashboard: UK + US.

    ``warnings`` usa claves cortas consumibles por i18n en el front si hace falta.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return {"query": q, "uk": [], "us": [], "warnings": ["query_too_short"]}

    uk, w1 = find_companies_house_matches(q, limit=uk_limit)
    warnings = list(w1)
    try:
        us = find_sec_matches(q, limit=us_limit)
    except requests.RequestException as e:
        logger.warning("SEC company index fetch failed: %s", e)
        us = []
        warnings.append("sec_request_failed")

    return {"query": q, "uk": uk, "us": us, "warnings": warnings}
