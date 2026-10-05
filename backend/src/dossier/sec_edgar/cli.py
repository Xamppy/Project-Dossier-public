"""CLI SEC EDGAR (Estados Unidos): búsqueda de filings y análisis opcional con Gemini."""
from __future__ import annotations

import os
import time

import requests

from dossier.companies_house.prompt_templates import format_sec_filing_gemini_prompt
from dossier.config import data_path, load_env
from dossier.llm.document_analyze import analyze_document_bytes

USER_AGENT = "CarlosApp/1.0 (fduran@utem.cl)"
MIN_INTERVAL_SECONDS = 0.1
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
MAX_FILINGS_TO_SHOW = 10


def fetch_json(url: str) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    time.sleep(MIN_INTERVAL_SECONDS)
    return response.json()


def fetch_bytes(url: str) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }
    response = requests.get(url, headers=headers, timeout=120)
    response.raise_for_status()
    time.sleep(MIN_INTERVAL_SECONDS)
    return response.content


def load_company_index() -> list[dict]:
    data = fetch_json(COMPANY_TICKERS_URL)
    return list(data.values())


def find_companies(query: str, companies: list[dict]) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []

    for c in companies:
        if c["ticker"].lower() == q:
            return [c]

    for c in companies:
        if c["title"].lower() == q:
            return [c]

    return [
        c for c in companies
        if q in c["title"].lower() or q in c["ticker"].lower()
    ]


def pick_company(matches: list[dict]) -> dict:
    if len(matches) == 1:
        c = matches[0]
        print(f"Coincidencia única: {c['title']} (ticker: {c['ticker']})")
        return c

    print(f"\nSe encontraron {len(matches)} coincidencias (máx. 30 mostradas):")
    shown = matches[:30]
    for i, c in enumerate(shown, start=1):
        print(f"  {i}. [{c['ticker']}] {c['title']}  (CIK {c['cik_str']})")

    while True:
        choice = input(f"\nNúmero de la empresa (1-{len(shown)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(shown):
                return shown[idx]
        except ValueError:
            pass
        print("Opción inválida, intenta de nuevo.")


def build_index_url(cik: str, accession: str) -> str:
    cik_clean = str(int(cik))
    accession_clean = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{accession_clean}/index.json"


def build_document_url(cik: str, accession: str, document_name: str) -> str:
    cik_clean = str(int(cik))
    accession_clean = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_clean}/{accession_clean}/{document_name}"


def filing_index_htm_url(cik: str, accession: str) -> str:
    cik_clean = str(int(cik))
    accession_clean = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_clean}/{accession_clean}/{accession}-index.htm"
    )


def find_main_document(index_data: dict, symbol_hint: str | None = None) -> str | None:
    files = index_data.get("directory", {}).get("item", [])
    hint = (symbol_hint or "").lower()

    if hint:
        for file in files:
            name = file.get("name", "")
            if name.endswith(".htm") and hint in name.lower():
                return name

    for file in files:
        name = file.get("name", "")
        if name.endswith(".htm") and not name.startswith("R") and "index" not in name.lower():
            return name

    return None


def maybe_analyze_with_gemini(
    *,
    document_url: str,
    document_name: str,
    company_name: str,
    form: str,
    filing_date: str,
    accession: str,
    cik: str,
    ticker: str = "",
) -> None:
    load_env()
    if (os.getenv("GEMINI_SKIP_ANALYSIS") or "").strip() in ("1", "true", "yes"):
        print("\n(Gemini: omitido por GEMINI_SKIP_ANALYSIS.)")
        return
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip():
        print(
            "\n(Gemini: no hay GEMINI_API_KEY; añádela al .env para analizar el "
            "formulario automáticamente.)"
        )
        return

    print("\nDescargando documento para análisis con Gemini…")
    try:
        data = fetch_bytes(document_url)
        prompt = format_sec_filing_gemini_prompt(
            company_name=str(company_name),
            cik=str(cik),
            ticker=str(ticker or ""),
            form=str(form),
            filing_date=str(filing_date),
            accession=str(accession),
            document_name=str(document_name),
        )
        print("Enviando a Gemini (puede tardar en documentos largos)…")
        analysis = analyze_document_bytes(data, document_name, prompt)
        print("\n=== Análisis Gemini ===\n")
        print(analysis)

        safe = "".join(c if c.isalnum() else "_" for c in accession.replace("-", ""))[:40]
        out_path = data_path(f"sec_gemini_analysis_{safe}.txt")
        out_path.write_text(
            f"URL: {document_url}\n\n{analysis}",
            encoding="utf-8",
        )
        print(f"\n(Análisis guardado en: {out_path.resolve()})")
    except ImportError as e:
        print(f"\n(Gemini: instala dependencias: pip install -r requirements.txt) {e}")
    except Exception as e:  # noqa: BLE001 - CLI: no debe morir por un fallo del analisis Gemini opcional
        print(f"\n(Gemini: error al analizar — {e})")


def main() -> None:
    try:
        load_env()
        print("=== CONSULTA SEC EDGAR ===")

        query = input(
            "Nombre de la empresa USA (SEC EDGAR) o ticker (ej: Tesla o TSLA): "
        ).strip()
        target_form = input(
            "Tipo de formulario a filtrar (ej: 10-K, 10-Q, 8-K): "
        ).strip().upper()

        if not query:
            print("Debes ingresar un nombre o ticker.")
            return
        if not target_form:
            print("Debes ingresar un tipo de formulario.")
            return

        companies = load_company_index()
        matches = find_companies(query, companies)
        if not matches:
            print("No se encontró ninguna empresa con ese nombre o ticker.")
            return

        company = pick_company(matches)
        cik = str(company["cik_str"]).zfill(10)

        print(f"\nObteniendo envíos (submissions) para CIK {cik}...")

        submissions_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data = fetch_json(submissions_url)

        company_name = data.get("name", "N/A")
        recent = data["filings"]["recent"]

        forms = recent["form"]
        dates = recent["filingDate"]
        accessions = recent["accessionNumber"]

        print(f"\nEmpresa: {company_name}")
        print(f"Filtrando solo formularios: {target_form}\n")

        filtered = []
        for form, date, accession in zip(forms, dates, accessions, strict=False):
            if form == target_form:
                filtered.append({
                    "form": form,
                    "date": date,
                    "accession": accession,
                })
                if len(filtered) >= MAX_FILINGS_TO_SHOW:
                    break

        if not filtered:
            print(
                f"No hay filings recientes de tipo «{target_form}» "
                "en el bloque «recent» de submissions."
            )
            return

        print(
            f"Últimos {len(filtered)} filings de tipo {target_form} "
            "(más recientes primero):\n"
        )

        for i, item in enumerate(filtered, start=1):
            idx_url = filing_index_htm_url(cik, item["accession"])
            print(f"--- {i} ---")
            print(f"Formulario: {item['form']}")
            print(f"Fecha:      {item['date']}")
            print(f"Accession:  {item['accession']}")
            print(f"Índice:     {idx_url}")
            print()

        first = filtered[0]
        index_url = build_index_url(cik, first["accession"])
        index_data = fetch_json(index_url)

        tickers = data.get("tickers") or []
        symbol_hint = tickers[0] if tickers else None
        document_name = find_main_document(index_data, symbol_hint=symbol_hint)

        if document_name:
            final_url = build_document_url(
                cik,
                first["accession"],
                document_name,
            )
            print("=== Documento principal del filing más reciente (mismo tipo) ===")
            print(f"Archivo: {document_name}")
            print("URL directa al HTML principal:")
            print(final_url)
            maybe_analyze_with_gemini(
                document_url=final_url,
                document_name=document_name,
                company_name=company_name,
                form=first["form"],
                filing_date=first["date"],
                accession=first["accession"],
                cik=cik,
                ticker=str(company.get("ticker", "") or ""),
            )
        else:
            print(
                "(No se pudo detectar el HTML principal del filing más reciente; "
                "usa el enlace «Índice» arriba.)"
            )

    except Exception as e:  # noqa: BLE001 - CLI: reporta el error y sigue
        print("Error:", e)
