"""
Contexto corporativo real para el grafo LangGraph (Companies House + SEC).

Los nodos del grafo llaman aquí para inyectar datos de APIs públicas en el prompt
de síntesis Gemini. Opcionalmente se analiza con Gemini un **documento** del filing
(CH vía Document API; SEC vía HTML principal en EDGAR), gobernado por variables de entorno.
Si falla una API o faltan credenciales, se devuelve Markdown explicativo en lugar de fallar
el pipeline entero.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import requests

from dossier.companies_house.cli import (
    ch_download_filing_document,
    get_company_profile,
    get_filing_history,
)
from dossier.companies_house.prompt_templates import (
    format_ch_filing_gemini_prompt,
    format_sec_filing_gemini_prompt,
)
from dossier.config import load_env
from dossier.llm.common import (
    is_transient_server_error,
    retry_after_seconds,
    should_retry,
)
from dossier.llm.document_analyze import analyze_document_bytes
from dossier.sec_edgar.user_agent import sec_request_headers
from dossier.services.corporate_company_search import (
    find_companies_house_matches,
    find_sec_matches,
)

logger = logging.getLogger(__name__)


def _sec_filing_gemini_enabled() -> bool:
    """
    Análisis Gemini del primer documento HTML principal de un filing SEC reciente.

    Desactivar con ``DOSSIER_CORPORATE_SEC_FILING_GEMINI=0`` (misma filosofía que CH).
    """
    load_env()
    v = (os.getenv("DOSSIER_CORPORATE_SEC_FILING_GEMINI") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _ch_filing_gemini_enabled() -> bool:
    """
    Análisis Gemini del primer filing CH (sube archivo + generate_content).

    Desactivar con ``DOSSIER_CORPORATE_CH_FILING_GEMINI=0`` para ahorrar 1 llamada por dossier
    (útil en cuota free tier de Gemini, donde la síntesis final ya consume otra petición).
    """
    load_env()
    v = (os.getenv("DOSSIER_CORPORATE_CH_FILING_GEMINI") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _is_gemini_429_or_quota(exc: BaseException) -> bool:
    s = str(exc).lower()
    return (
        "429" in str(exc)
        or "resource_exhausted" in s
        or ("quota" in s and "exceed" in s)
        or "too many requests" in s
    )


def _gemini_retry_sleep_seconds(exc: BaseException) -> float:
    m = re.search(r"retry in ([\d.]+)s", str(exc), re.IGNORECASE)
    if m:
        return min(float(m.group(1)) + 2.0, 120.0)
    return 58.0


def _gemini_analyze_bytes_with_retries(
    data: bytes, filename: str, prompt: str, *, log_prefix: str
) -> str:
    """
    Reintentos ante 429/cuota y errores transitorios de Gemini (503 UNAVAILABLE, timeouts).

    ``analyze_document_bytes`` ya reintenta dentro de ``generate_content``; aquí repetimos
    el flujo completo (subida + análisis) cuando falla upload, procesamiento del archivo, etc.
    """
    last: BaseException | None = None
    max_attempts = int(os.getenv("GEMINI_CORPORATE_FILING_OUTER_RETRIES", "5"))
    max_attempts = max(2, min(max_attempts, 8))
    for attempt in range(max_attempts):
        try:
            return analyze_document_bytes(data, filename, prompt)
        except Exception as e:
            last = e
            if attempt < max_attempts - 1 and should_retry(e):
                wait = (
                    _gemini_retry_sleep_seconds(e)
                    if _is_gemini_429_or_quota(e)
                    else retry_after_seconds(e)
                )
                logger.info(
                    "%s: error reintentable (%s), espera %.1fs (paso %s/%s)",
                    log_prefix,
                    type(e).__name__,
                    wait,
                    attempt + 2,
                    max_attempts,
                )
                time.sleep(wait)
                continue
            raise
    assert last is not None
    raise last


def _analyze_ch_document_with_retries(data: bytes, filename: str, prompt: str) -> str:
    return _gemini_analyze_bytes_with_retries(
        data, filename, prompt, log_prefix="Gemini filing CH"
    )

# Número tras plantilla de resolución (español) del backend.
_RE_CH_NUMBER = re.compile(
    r"Companies House\s*\(\s*número\s+([0-9]{6,10})\s*\)",
    re.IGNORECASE,
)
# Petición original entre comillas latinas « »
_RE_USER_TERM = re.compile(r"«\s*([^»]{2,120})\s*»")

_RE_CIK = re.compile(r"\bCIK\s+(\d{7,10})\b", re.IGNORECASE)
_RE_TICKER = re.compile(r"\bticker\s+([A-Z0-9.]{1,10})\b", re.IGNORECASE)


def _trunc(text: str, max_chars: int = 14_000) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 80] + "\n\n… *(contenido truncado por tamaño)* …\n"


def _ch_auth() -> tuple[str, str] | None:
    load_env()
    key = (os.getenv("COMPANIES_HOUSE_API_KEY") or "").strip()
    if not key:
        return None
    return (key, "")


def _resolve_ch_company_number(participantes: str) -> tuple[str | None, str]:
    """
    Devuelve (company_number, nota de cómo se resolvió) o (None, motivo).
    """
    text = (participantes or "").strip()
    if not text:
        return None, "texto vacío"

    m = _RE_CH_NUMBER.search(text)
    if m:
        return m.group(1).strip(), "número explícito en el brief (Companies House)"

    um = _RE_USER_TERM.search(text)
    if um:
        q = um.group(1).strip()
        if len(q) >= 2 and _ch_auth():
            rows, warns = find_companies_house_matches(q, limit=5)
            if rows:
                return rows[0]["company_number"], f"búsqueda UK por término del usuario «{q}»"
            if warns:
                logger.info("CH search sin resultados para %r: %s", q, warns)

    if _ch_auth() and len(text) >= 3:
        snippet = text[:100].strip()
        rows, _ = find_companies_house_matches(snippet, limit=3)
        if rows:
            return rows[0]["company_number"], "primera coincidencia UK por texto del brief (heurística)"

    return None, "no se pudo deducir número UK (falta clave API, texto o coincidencias)"


def _sec_fetch_bytes(url: str) -> bytes:
    headers = sec_request_headers()
    r = requests.get(url, headers=headers, timeout=120)
    r.raise_for_status()
    time.sleep(0.11)
    return r.content


def _sec_get_json(url: str) -> dict[str, Any]:
    headers = sec_request_headers()
    r = requests.get(url, headers=headers, timeout=90)
    r.raise_for_status()
    # Buena práctica SEC: espaciar peticiones.
    time.sleep(0.11)
    return r.json()


def _sec_filing_tier_for_gemini_pick(form: str) -> int:
    """
    Prioridad para elegir **qué filing** descargar y enviar a Gemini (un solo HTML).

    Valores más bajos = preferidos. Así evitamos quedarnos en el primer HTML «válido»
    de la cola reciente (p. ej. Form SD o 8-K) cuando existe un 10-K o 10-Q cercano.
    """
    u = (form or "").strip().upper()
    if u in ("10-K", "20-F", "40-F"):
        return 0
    if u in ("10-K/A", "10-KT", "20-F/A", "40-F/A"):
        return 1
    if u.startswith("10-K"):
        return 2
    if u in ("10-Q", "10-Q/A", "6-K", "6-K/A"):
        return 3
    if u in ("DEF 14A", "DEFA14A", "PRE 14A"):
        return 5
    if u.startswith(("S-1", "F-1", "424B")):
        return 8
    if u.startswith("8-K"):
        return 22
    if "13G" in u or "13D" in u or u.startswith("SC 13"):
        return 38
    if u in ("SD", "SD/A"):
        return 40
    if u in ("4", "144", "3", "5"):
        return 45
    return 30


def _resolve_sec_cik(participantes: str) -> tuple[str | None, str | None, str]:
    """(cik10, ticker opcional, nota)."""
    text = (participantes or "").strip()

    m = _RE_CIK.search(text)
    if m:
        return str(m.group(1)).zfill(10), None, "CIK explícito en el brief"

    tm = _RE_TICKER.search(text)
    if tm:
        t = tm.group(1).upper().replace(".", "")
        hits = find_sec_matches(t, limit=8)
        for h in hits:
            if h.get("ticker", "").upper() == t:
                return h["cik"], h.get("ticker"), f"CIK deducido del ticker {t}"
        if hits:
            h0 = hits[0]
            return h0["cik"], h0.get("ticker"), f"CIK por primera coincidencia SEC para ticker «{t}»"

    um = _RE_USER_TERM.search(text)
    if um:
        q = um.group(1).strip()
        if len(q) >= 2:
            hits = find_sec_matches(q, limit=8)
            if hits:
                h0 = hits[0]
                return h0["cik"], h0.get("ticker"), f"CIK por primera coincidencia SEC para «{q}»"

    if len(text) >= 2:
        hits = find_sec_matches(text[:80], limit=5)
        if hits:
            h0 = hits[0]
            return h0["cik"], h0.get("ticker"), "CIK por heurística sobre primeros caracteres del brief"

    return None, None, "no se pudo deducir CIK/ticker US"


def _format_sec_recent_submissions(data: dict[str, Any], limit: int = 20) -> str:
    name = data.get("name") or "(sin nombre en submissions)"
    cik_header = data.get("cik") or ""
    tickers = data.get("tickers") or []
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accs = recent.get("accessionNumber") or []
    lines = [
        "## Presentaciones recientes (referencia regulatoria)",
        f"- **Nombre en SEC:** {name}",
        f"- **CIK (cabecera):** {cik_header}",
        f"- **Tickers:** {', '.join(str(x) for x in tickers) if tickers else '(no listados)'}",
        "",
        f"### Últimos envíos recientes (hasta {limit} filas)",
        "",
        "| filingDate | form | accessionNumber |",
        "|---|---|---|",
    ]
    n = min(len(forms), len(dates), len(accs), limit)
    for i in range(n):
        lines.append(f"| {dates[i]} | {forms[i]} | {accs[i]} |")
    return "\n".join(lines)


# Etiquetas us-gaap frecuentes para un snapshot compacto (Company Facts API).
_SEC_COMPANY_FACTS_TAGS: tuple[str, ...] = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "NetIncomeLoss",
    "OperatingIncomeLoss",
    "CashAndCashEquivalentsAtCarryingValue",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "LongTermDebt",
    "DebtCurrent",
)


def _sec_company_facts_enabled() -> bool:
    """Resumen XBRL vía `companyfacts` (una petición extra a data.sec.gov)."""
    load_env()
    v = (os.getenv("DOSSIER_SEC_COMPANY_FACTS") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _sec_extract_company_facts_sample(payload: dict[str, Any]) -> dict[str, Any]:
    """Reduce el JSON masivo de companyfacts a unas pocas series temporales."""
    usgaap = (payload.get("facts") or {}).get("us-gaap") or {}
    sample: dict[str, list[dict[str, Any]]] = {}
    for tag in _SEC_COMPANY_FACTS_TAGS:
        block = usgaap.get(tag)
        if not isinstance(block, dict):
            continue
        units = block.get("units") or {}
        rows: list[Any] = []
        for uk in ("USD", "USD/shares", "shares", "pure"):
            if uk in units and isinstance(units[uk], list):
                rows = units[uk]
                break
        if not rows and units:
            for _u, arr in units.items():
                if isinstance(arr, list) and arr:
                    rows = arr
                    break
        if not rows:
            continue

        def _rk(r: dict[str, Any]) -> str:
            return str(r.get("filed") or r.get("end") or "")

        top = sorted(rows, key=_rk, reverse=True)[:8]
        slim: list[dict[str, Any]] = []
        for r in top:
            if not isinstance(r, dict):
                continue
            row_out: dict[str, Any] = {}
            for k in ("filed", "end", "val", "fy", "fp", "form", "accn"):
                if k in r and r[k] is not None:
                    row_out[k] = r[k]
            if row_out:
                slim.append(row_out)
        if slim:
            sample[tag] = slim
    return {
        "entityName": payload.get("entityName"),
        "cik": payload.get("cik"),
        "us_gaap_highlights": sample,
    }


def _build_sec_company_facts_markdown(cik: str) -> str:
    if not _sec_company_facts_enabled():
        return ""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    try:
        payload = _sec_get_json(url)
    except Exception as e:  # noqa: BLE001 - fuente externa opcional (SEC): degrada con texto informativo
        logger.warning("SEC companyfacts CIK=%s: %s", cik, e)
        return (
            "\n\n### Indicadores financieros públicos (cifras reportadas por el emisor)\n\n"
            f"*No se pudieron cargar las series resumidas: `{e}`*\n"
        )
    slim = _sec_extract_company_facts_sample(payload)
    highlights = slim.get("us_gaap_highlights") or {}
    if not highlights:
        return (
            "\n\n### Indicadores financieros públicos (cifras reportadas por el emisor)\n\n"
            "*No hay series numéricas reconocibles en el material público estándar para este emisor "
            "(emisores extranjeros o presentaciones con taxonomía distinta pueden dejar esta sección casi vacía).*\n"
        )
    raw = json.dumps(slim, indent=2, ensure_ascii=False)
    max_chars_raw = (os.getenv("DOSSIER_SEC_COMPANY_FACTS_MAX_CHARS") or "14000").strip()
    max_c = int(max_chars_raw) if max_chars_raw.isdigit() else 14_000
    max_c = max(4000, min(max_c, 80_000))
    return (
        "\n\n### Indicadores financieros públicos (cifras reportadas por el emisor)\n\n"
        "Serie temporal reciente de partidas contables frecuentes (ingresos, activos, patrimonio, "
        "resultado, caja, deuda, BPA, etc.), tal como figuran en los datos públicos de referencia. "
        "Usa `form`, `filed` y `end` para interpretar cada cifra.\n\n"
        "```json\n"
        + _trunc(raw, max_c)
        + "\n```\n"
    )


def _ch_gemini_filing_markdown(
    profile: dict[str, Any],
    fh: dict[str, Any],
    auth: tuple[str, str],
    company_number: str,
) -> str:
    """
    Misma lógica que ``maybe_analyze_ch_filing_with_gemini`` en el CLI: primer filing con
    ``document_metadata``, descarga y prompt compartido en ``prompt_templates``.
    """
    load_env()
    if (os.getenv("GEMINI_SKIP_ANALYSIS") or "").strip().lower() in ("1", "true", "yes"):
        return ""

    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip():
        return (
            "\n\n### Lectura del formulario regulatorio (Reino Unido)\n\n"
            "*Falta la clave de análisis de documentos en el entorno: se omitió la lectura del formulario.*\n"
        )

    if not _ch_filing_gemini_enabled():
        return (
            "\n\n### Lectura del formulario regulatorio (Reino Unido)\n\n"
            "*Omitido por configuración (`DOSSIER_CORPORATE_CH_FILING_GEMINI=0`): no se adjunta lectura "
            "detallada del formulario en este dossier.*\n"
        )

    items = fh.get("items") or []
    chosen: tuple[dict[str, Any], str] | None = None
    for item in items:
        meta_url = (item.get("links") or {}).get("document_metadata")
        if meta_url:
            chosen = (item, str(meta_url))
            break

    if not chosen:
        return (
            "\n\n### Lectura del formulario regulatorio (Reino Unido)\n\n"
            "*Ningún ítem reciente del historial incluye documento electrónico descargable "
            "(p. ej. solo presentaciones en papel); no hay archivo para analizar.*\n"
        )

    item, meta_url = chosen
    company_name = str(profile.get("company_name", "N/A"))
    date = str(item.get("date", ""))
    ftype = str(item.get("type", ""))
    category = str(item.get("category", ""))
    desc = str(item.get("description", ""))
    safe_cn = "".join(c if c.isalnum() else "_" for c in company_number)[:16]

    try:
        data, ext = ch_download_filing_document(meta_url, auth)
        filename = f"ch_{safe_cn}_{date}_{ftype}{ext}"
        prompt = format_ch_filing_gemini_prompt(
            company_name=company_name,
            company_number=company_number,
            date=date,
            ftype=ftype,
            category=category,
            description=desc,
        )
        logger.info("DeepSeek: analizando primer filing CH %s (%s)", company_number, filename)
        analysis = _analyze_ch_document_with_retries(data, filename, prompt)
        return (
            "\n\n### Lectura del formulario Companies House\n\n"
            + (analysis.strip() or "(Sin texto en el resumen del documento.)")
            + "\n"
        )
    except Exception as e:  # noqa: BLE001 - fuente externa (DeepSeek): degrada con texto informativo
        logger.warning("DeepSeek CH filing analysis failed: %s", e)
        if _is_gemini_429_or_quota(e):
            return (
                "\n\n### Lectura del formulario regulatorio (Reino Unido)\n\n"
                "**Límite de cuota del servicio de análisis de documentos (429).** "
                "Este paso consume capacidad adicional además del informe ejecutivo final.\n\n"
                "- Espere según el mensaje del proveedor y vuelva a intentar, o revise el plan de uso.\n"
                "- Para generar dossiers sin esta lectura detallada del formulario, en `.env`:\n\n"
                "  `DOSSIER_CORPORATE_CH_FILING_GEMINI=0`\n\n"
                f"*Detalle técnico:* `{e}`\n"
            )
        if is_transient_server_error(e):
            return (
                "\n\n### Lectura del formulario regulatorio (Reino Unido)\n\n"
                "**El servicio de análisis no respondió a tiempo (503 / no disponible / timeout).** "
                "Suele ser un fallo puntual; no indica que el formulario no exista.\n\n"
                "- Espere unos minutos y vuelva a generar el dossier.\n"
                "- Para omitir esta lectura: `DOSSIER_CORPORATE_CH_FILING_GEMINI=0` en `.env`.\n\n"
                f"*Detalle técnico:* `{e}`\n"
            )
        return f"\n\n### Lectura del formulario regulatorio (Reino Unido)\n\n*Error al analizar el documento: {e}*\n"


def _sec_gemini_filing_markdown(
    submissions_data: dict[str, Any],
    cik: str,
    ticker_resolver: str | None,
    resolution_note: str,
) -> str:
    """
    Descarga el HTML principal de un filing SEC reciente y lo analiza con Gemini.

    Orden de revisión: se priorizan **10-K / 20-F / 40-F**, luego enmiendas y **10-Q**,
    y recién después formularios puntuales (8-K, SD, 13G, etc.), siempre respetando
    el índice de recencia de la API (menor índice = filing más reciente entre el mismo tipo).
    """
    from dossier.sec_edgar.cli import build_document_url, build_index_url, find_main_document

    load_env()
    if (os.getenv("GEMINI_SKIP_ANALYSIS") or "").strip().lower() in ("1", "true", "yes"):
        return ""

    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip():
        return (
            "\n\n### Lectura del informe periódico SEC\n\n"
            "*Falta la clave de análisis de documentos en el entorno: se omitió la lectura del informe.*\n"
        )

    if not _sec_filing_gemini_enabled():
        return (
            "\n\n### Lectura del informe periódico SEC\n\n"
            "*Omitido por configuración (`DOSSIER_CORPORATE_SEC_FILING_GEMINI=0`): no se adjunta lectura "
            "detallada del informe periódico en este dossier.*\n"
        )

    company_name = str(submissions_data.get("name") or "N/A")
    tickers_list = submissions_data.get("tickers") or []
    ticker_display = (ticker_resolver or "").strip()
    if not ticker_display and isinstance(tickers_list, list) and tickers_list:
        ticker_display = str(tickers_list[0])
    symbol_hint = ticker_display or None

    recent = (submissions_data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accns = recent.get("accessionNumber") or []
    if not forms or not accns or len(forms) != len(accns):
        return (
            "\n\n### Lectura del informe periódico SEC\n\n"
            "*No hay bloque `filings.recent` utilizable en submissions.*\n"
        )

    chosen_form = chosen_date = chosen_acc = ""
    chosen_doc: str | None = None
    doc_bytes: bytes | None = None
    doc_url = ""

    scan_raw = (os.getenv("DOSSIER_SEC_GEMINI_FILING_SCAN_MAX") or "60").strip()
    scan_max = int(scan_raw) if scan_raw.isdigit() else 60
    scan_max = max(12, min(scan_max, 120))

    n = min(len(forms), len(dates), len(accns), scan_max)
    indices = list(range(n))
    indices.sort(key=lambda i: (_sec_filing_tier_for_gemini_pick(str(forms[i])), i))

    for i in indices:
        form_s = str(forms[i])
        date_s = str(dates[i])
        acc_s = str(accns[i])
        try:
            idx_url = build_index_url(cik, acc_s)
            index_data = _sec_get_json(idx_url)
        except Exception as e:  # noqa: BLE001 - fuente externa opcional (SEC): se omite este filing y continua
            logger.info("SEC index.json omitido accession=%s: %s", acc_s, e)
            continue
        doc_name = find_main_document(index_data, symbol_hint=symbol_hint)
        if not doc_name:
            continue
        low = str(doc_name).lower()
        if not low.endswith((".htm", ".html")):
            continue
        try:
            final_url = build_document_url(cik, acc_s, str(doc_name))
            raw = _sec_fetch_bytes(final_url)
        except Exception as e:  # noqa: BLE001 - fuente externa opcional (SEC): se omite este documento y continua
            logger.warning("SEC documento omitido %s: %s", doc_name, e)
            continue
        chosen_form, chosen_date, chosen_acc = form_s, date_s, acc_s
        chosen_doc = str(doc_name)
        doc_bytes = raw
        doc_url = final_url
        logger.info(
            "SEC filing elegido para Gemini: form=%s date=%s accession=%s (tier=%s, índice reciente=%s)",
            chosen_form,
            chosen_date,
            chosen_acc,
            _sec_filing_tier_for_gemini_pick(chosen_form),
            i,
        )
        break

    if not chosen_doc or doc_bytes is None:
        return (
            "\n\n### Lectura del informe periódico SEC\n\n"
            "*No se encontró un HTML principal descargable en los envíos recientes revisados "
            "(o falló `index.json` / la descarga).*\n"
        )

    safe_acc = "".join(c if c.isalnum() else "_" for c in chosen_acc.replace("-", ""))[:28]
    safe_doc = "".join(c if c.isalnum() else "_" for c in chosen_doc)[:40]
    filename = f"sec_{safe_acc}_{chosen_form}_{safe_doc}"

    prompt = format_sec_filing_gemini_prompt(
        company_name=company_name,
        cik=cik,
        ticker=ticker_display,
        form=chosen_form,
        filing_date=chosen_date,
        accession=chosen_acc,
        document_name=chosen_doc,
    )
    try:
        logger.info("DeepSeek: analizando filing SEC CIK=%s accession=%s (%s)", cik, chosen_acc, filename)
        analysis = _gemini_analyze_bytes_with_retries(
            doc_bytes, filename, prompt, log_prefix="Gemini filing SEC"
        )
        return (
            "\n\n### Lectura del informe periódico SEC\n\n"
            f"*Resolución emisor: {resolution_note}"
            + (f", ticker **{ticker_display}**" if ticker_display else "")
            + f". Enlace al documento de referencia: `{doc_url}`*\n\n"
            + (analysis.strip() or "(Sin texto en el resumen del documento.)")
            + "\n"
        )
    except Exception as e:  # noqa: BLE001 - fuente externa (DeepSeek): degrada con texto informativo
        logger.warning("DeepSeek SEC filing analysis failed: %s", e)
        if _is_gemini_429_or_quota(e):
            return (
                "\n\n### Lectura del informe periódico SEC\n\n"
                "**Límite de cuota del servicio de análisis de documentos (429).** "
                "Este paso consume capacidad adicional además del informe ejecutivo final.\n\n"
                "- Espere y vuelva a intentar, o revise el plan de uso del proveedor.\n"
                "- Para omitir esta lectura en dossiers corporativos:\n\n"
                "  `DOSSIER_CORPORATE_SEC_FILING_GEMINI=0`\n\n"
                f"*Detalle técnico:* `{e}`\n"
            )
        if is_transient_server_error(e):
            return (
                "\n\n### Lectura del informe periódico SEC\n\n"
                "**El servicio de análisis no respondió a tiempo (503 / no disponible / timeout).** "
                "Suele ser un fallo puntual al procesar el archivo; no indica que el informe no exista.\n\n"
                "- Espere unos minutos y vuelva a generar el dossier.\n"
                "- Para omitir esta lectura: `DOSSIER_CORPORATE_SEC_FILING_GEMINI=0` en `.env`.\n\n"
                f"*Detalle técnico:* `{e}`\n"
            )
        return f"\n\n### Lectura del informe periódico SEC\n\n*No se pudo completar la lectura del documento: {e}*\n"


def build_uk_corporate_context_markdown(participantes: str) -> str:
    """Markdown con perfil + muestra de historial Companies House, o mensaje de fallo."""
    auth = _ch_auth()
    if not auth:
        return (
            "## Reino Unido (Companies House)\n\n"
            "*No hay `COMPANIES_HOUSE_API_KEY` en el entorno: no se consultó la API.*\n"
        )

    num, note = _resolve_ch_company_number(participantes)
    if not num:
        return (
            "## Reino Unido (Companies House)\n\n"
            f"*No se obtuvo número de empresa ({note}).*\n\n"
            "**Texto de entrada (extracto):**\n```\n"
            + _trunc(participantes, 2000)
            + "\n```\n"
        )

    try:
        profile = get_company_profile(num, auth)
    except requests.RequestException as e:
        logger.warning("CH profile %s: %s", num, e)
        return f"## Reino Unido (Companies House)\n\n*Error HTTP al leer perfil {num}: {e}*\n"

    try:
        fh = get_filing_history(num, auth)
        items = (fh.get("items") or [])[:10]
        fh_summary = []
        for it in items:
            fh_summary.append(
                {
                    "date": it.get("date"),
                    "type": it.get("type"),
                    "description": it.get("description"),
                }
            )
    except requests.RequestException as e:
        logger.warning("CH filing history %s: %s", num, e)
        fh = {}
        fh_summary = [{"error": str(e)}]

    prof_json = json.dumps(profile, indent=2, ensure_ascii=False)
    fh_json = json.dumps(fh_summary, indent=2, ensure_ascii=False)

    gemini_md = _ch_gemini_filing_markdown(profile, fh, auth, num)

    return (
        "## Reino Unido (Companies House)\n\n"
        f"*Empresa resuelta: **{num}** ({note}).*\n\n"
        "### Perfil (JSON)\n\n```json\n"
        + _trunc(prof_json, 10_000)
        + "\n```\n\n"
        "### Muestra de filing history (ítems recientes)\n\n```json\n"
        + _trunc(fh_json, 4000)
        + "\n```\n"
        + gemini_md
    )


def build_us_corporate_context_markdown(participantes: str) -> str:
    """Markdown con submissions, indicadores financieros públicos y lectura opcional del informe EDGAR."""
    cik, ticker, note = _resolve_sec_cik(participantes)
    if not cik:
        return (
            "## Estados Unidos (SEC EDGAR)\n\n"
            f"*No se obtuvo CIK ({note}).*\n\n"
            "**Texto de entrada (extracto):**\n```\n"
            + _trunc(participantes, 2000)
            + "\n```\n"
        )

    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        data = _sec_get_json(url)
    except requests.RequestException as e:
        logger.warning("SEC submissions %s: %s", cik, e)
        return (
            "## Estados Unidos (SEC EDGAR)\n\n"
            f"*Error al descargar submissions para CIK {cik}: {e}*\n"
            f"*Resolución: {note}*"
            + (f", ticker {ticker}" if ticker else "")
            + "\n"
        )

    body = _format_sec_recent_submissions(data, limit=22)
    company_facts_md = _build_sec_company_facts_markdown(cik)
    sec_gemini = _sec_gemini_filing_markdown(data, cik, ticker, note)
    return (
        "## Estados Unidos (SEC EDGAR — información pública)\n\n"
        f"*Emisor resuelto: CIK **{cik}** ({note})"
        + (f", ticker **{ticker}**" if ticker else "")
        + ".*\n\n"
        + body
        + "\n"
        + company_facts_md
        + sec_gemini
    )
