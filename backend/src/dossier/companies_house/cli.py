"""
CLI Companies House (Reino Unido): búsqueda por nombre, perfil e historial de filings.
Requiere COMPANIES_HOUSE_API_KEY en .env. Opcional: GEMINI_API_KEY para análisis automático.
"""
from __future__ import annotations

import os

import requests

from dossier.companies_house.prompt_templates import format_ch_filing_gemini_prompt
from dossier.config import data_path, load_env, write_json
from dossier.llm.document_analyze import analyze_document_bytes

SEARCH_URL = "https://api.company-information.service.gov.uk/search/companies"
COMPANY_URL_TEMPLATE = "https://api.company-information.service.gov.uk/company/{number}"
FILING_HISTORY_URL_TEMPLATE = (
    "https://api.company-information.service.gov.uk/company/{number}/filing-history"
)
MAX_ITEMS_SEARCH = 100
MAX_ITEMS_FILINGS = 100


def load_api_key() -> tuple[str, str]:
    load_env()
    key = os.getenv("COMPANIES_HOUSE_API_KEY")
    if not key or not str(key).strip():
        raise SystemExit(
            "Falta COMPANIES_HOUSE_API_KEY. Añádela al archivo .env en backend/."
        )
    return (str(key).strip(), "")


def ch_get(url: str, auth: tuple[str, str], params: dict | None = None) -> dict:
    response = requests.get(url, auth=auth, params=params or {}, timeout=60)
    response.raise_for_status()
    return response.json()


def search_companies(query: str, auth: tuple[str, str]) -> dict:
    return ch_get(
        SEARCH_URL,
        auth,
        params={"q": query, "items_per_page": MAX_ITEMS_SEARCH},
    )


def filter_and_sort_items(items: list[dict], query: str) -> tuple[list[dict], bool]:
    q = query.strip().casefold()
    if not q:
        return items, False
    filtered = [it for it in items if q in (it.get("title") or "").casefold()]
    if filtered:
        items_to_sort = filtered
        strict = True
    else:
        items_to_sort = list(items)
        strict = False

    def sort_key(it: dict) -> tuple[int, int]:
        t = (it.get("title") or "").casefold()
        if t == q:
            rank = 0
        elif t.startswith(q):
            rank = 1
        elif q in t:
            rank = 2
        else:
            rank = 3
        return (rank, len(t))

    return sorted(items_to_sort, key=sort_key), strict


def get_company_profile(company_number: str, auth: tuple[str, str]) -> dict:
    url = COMPANY_URL_TEMPLATE.format(number=company_number)
    return ch_get(url, auth)


def get_filing_history(company_number: str, auth: tuple[str, str]) -> dict:
    url = FILING_HISTORY_URL_TEMPLATE.format(number=company_number)
    return ch_get(
        url,
        auth,
        params={"items_per_page": MAX_ITEMS_FILINGS},
    )


MIME_TO_EXT = {
    "application/pdf": ".pdf",
    "application/xhtml+xml": ".html",
    "text/html": ".html",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/xml": ".xml",
}

DEFAULT_ACCEPT_ORDER: list[tuple[str, str]] = [
    ("application/pdf", ".pdf"),
    ("application/xhtml+xml", ".html"),
    ("text/html", ".html"),
    ("application/json", ".json"),
    ("application/xml", ".xml"),
]


def _mime_sort_key(mime: str) -> int:
    m = mime.split(";")[0].strip().lower()
    if "pdf" in m:
        return 0
    if "xhtml" in m or m == "text/html":
        return 1
    if "json" in m:
        return 2
    if "xml" in m:
        return 3
    return 9


def _accept_order_from_metadata(meta: dict | None) -> list[tuple[str, str]]:
    if not meta:
        return list(DEFAULT_ACCEPT_ORDER)
    resources = meta.get("resources") or {}
    keys = [k.split(";")[0].strip() for k in resources if k]
    keys_sorted = sorted(set(keys), key=_mime_sort_key)
    order: list[tuple[str, str]] = []
    for mime in keys_sorted:
        ext = MIME_TO_EXT.get(mime.lower(), ".bin")
        order.append((mime, ext))
    for mime, ext in DEFAULT_ACCEPT_ORDER:
        if mime not in [x[0] for x in order]:
            order.append((mime, ext))
    return order


def ch_fetch_metadata_dict(metadata_url: str, auth: tuple[str, str]) -> dict | None:
    try:
        return ch_get(metadata_url, auth)
    except requests.HTTPError:
        return None


def ch_download_filing_document(metadata_url: str, auth: tuple[str, str]) -> tuple[bytes, str]:
    base = metadata_url.rstrip("/")
    content_url = f"{base}/content"
    meta = ch_fetch_metadata_dict(metadata_url, auth)
    attempts = _accept_order_from_metadata(meta)
    last: tuple[int, str] | None = None
    for accept, ext in attempts:
        response = requests.get(
            content_url,
            auth=auth,
            headers={"Accept": accept},
            timeout=120,
            allow_redirects=True,
        )
        if response.status_code == 200 and response.content:
            return response.content, ext
        last = (response.status_code, (response.text or "")[:300])
    raise RuntimeError(
        f"No se pudo descargar el documento desde {content_url}. "
        f"Último intento HTTP {last[0]}: {last[1]!r}"
        if last
        else "Sin respuesta."
    )


def maybe_analyze_ch_filing_with_gemini(
    profile: dict,
    filing_history: dict,
    auth: tuple[str, str],
    company_number: str,
) -> None:
    load_env()
    if (os.getenv("GEMINI_SKIP_ANALYSIS") or "").strip() in ("1", "true", "yes"):
        print("\n(Gemini: omitido por GEMINI_SKIP_ANALYSIS.)")
        return
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip():
        print(
            "\n(Gemini: no hay GEMINI_API_KEY; añádela al .env para analizar "
            "documentos de Companies House automáticamente.)"
        )
        return

    items = filing_history.get("items") or []
    chosen: tuple[dict, str] | None = None
    for item in items:
        meta_url = (item.get("links") or {}).get("document_metadata")
        if meta_url:
            chosen = (item, str(meta_url))
            break

    if not chosen:
        print(
            "\n(Gemini: ningún ítem del historial reciente incluye document_metadata "
            "(p. ej. solo presentaciones en papel); no hay archivo que descargar.)"
        )
        return

    item, meta_url = chosen
    company_name = profile.get("company_name", "N/A")
    print("\nDescargando documento desde Companies House (Document API) para Gemini…")
    try:
        data, ext = ch_download_filing_document(meta_url, auth)
        date = item.get("date", "")
        ftype = item.get("type", "")
        category = item.get("category", "")
        desc = item.get("description", "")
        tx = item.get("transaction_id", "doc")[:24]
        safe_cn = "".join(c if c.isalnum() else "_" for c in company_number)[:16]
        filename = f"ch_{safe_cn}_{date}_{ftype}{ext}"

        prompt = format_ch_filing_gemini_prompt(
            company_name=str(company_name),
            company_number=str(company_number),
            date=str(date),
            ftype=str(ftype),
            category=str(category),
            description=str(desc),
        )
        print("Enviando a Gemini (puede tardar si el PDF/HTML es grande)…")
        analysis = analyze_document_bytes(data, filename, prompt)
        print("\n=== Análisis Gemini (Companies House) ===\n")
        print(analysis)

        out_path = data_path(f"ch_gemini_analysis_{safe_cn}_{tx}.txt")
        out_path.write_text(
            f"document_metadata: {meta_url}\n\n{analysis}",
            encoding="utf-8",
        )
        print(f"\n(Análisis guardado en: {out_path.resolve()})")
    except ImportError as e:
        print(f"\n(Gemini: instala dependencias: pip install -r requirements.txt) {e}")
    except Exception as e:  # noqa: BLE001 - CLI: no debe morir por un fallo del analisis Gemini opcional
        print(f"\n(Gemini: error al analizar — {e})")


def _format_address(addr: dict | None) -> str:
    if not addr:
        return "N/A"
    parts = [
        addr.get("premises"),
        addr.get("address_line_1"),
        addr.get("address_line_2"),
        addr.get("locality"),
        addr.get("region"),
        addr.get("postal_code"),
        addr.get("country"),
    ]
    return ", ".join(p for p in parts if p)


def print_profile_summary(profile: dict) -> None:
    print(f"\nNombre: {profile.get('company_name', 'N/A')}")
    print(f"Número: {profile.get('company_number', 'N/A')}")
    print(f"Estado: {profile.get('company_status', 'N/A')}")
    print(f"Tipo: {profile.get('type', 'N/A')}")
    print(f"Jurisdicción: {profile.get('jurisdiction', 'N/A')}")
    print(f"Constitución: {profile.get('date_of_creation', 'N/A')}")
    print(f"Domicilio social: {_format_address(profile.get('registered_office_address'))}")

    sic = profile.get("sic_codes")
    if sic:
        print("SIC:")
        for code in sic:
            print(f"  - {code}")

    accounts = profile.get("accounts")
    if accounts:
        na = accounts.get("next_accounts") or {}
        la = accounts.get("last_accounts") or {}
        if na.get("due_on"):
            print(f"Cuentas — próximo vencimiento: {na.get('due_on')}")
        if la.get("made_up_to"):
            print(f"Cuentas — último periodo hasta: {la.get('made_up_to')}")

    ch_profile = profile.get("links", {}).get("self")
    if ch_profile:
        web = f"https://find-and-update.company-information.service.gov.uk{ch_profile}"
        print(f"\nFicha en Companies House: {web}")


def print_filing_history_summary(_: dict, company_number: str) -> None:
    base_web = (
        f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/filing-history"
    )
    print(f"\nHistorial en web: {base_web}")


def main() -> None:
    nombre = input("Nombre de la empresa (Reino Unido, Companies House): ").strip()
    if not nombre:
        print("No ingresaste ningún nombre.")
        return

    try:
        auth = load_api_key()
        print("\nBuscando en Companies House…")
        data = search_companies(nombre, auth)
        items = data.get("items") or []
        total = data.get("total_results", 0)

        if not items:
            print(f"No hay resultados para «{nombre}». Total API: {total}.")
            return

        matches, strict = filter_and_sort_items(items, nombre)
        max_show = 30
        if len(matches) > max_show:
            print(
                f"Hay {len(matches)} resultados mostrables; se listan {max_show} "
                "(mejor ordenados)."
            )
            matches = matches[:max_show]

        if not strict:
            print(
                "\n(Aviso: ningún resultado contiene tu texto en el título con el mismo criterio; "
                "se muestran los primeros resultados de la API.)"
            )

        selected: dict
        if len(matches) == 1:
            selected = matches[0]
            print(f"\nCoincidencia única: {selected.get('title')} ({selected.get('company_number')})")
        else:
            print("\nVarias coincidencias — elige una:\n")
            for i, m in enumerate(matches, 1):
                print(
                    f"  {i}. {m.get('title')} | {m.get('company_number')} | "
                    f"{m.get('company_status', '')} | {m.get('address_snippet', '')}"
                )
            while True:
                raw = input(f"\nNúmero (1–{len(matches)}): ").strip()
                if not raw.isdigit():
                    print("Escribe un número válido.")
                    continue
                idx = int(raw)
                if 1 <= idx <= len(matches):
                    selected = matches[idx - 1]
                    break
                print("Fuera de rango.")

        company_number = selected.get("company_number")
        if not company_number:
            print("Respuesta sin company_number.")
            return

        print(f"\nObteniendo perfil y filing history para {company_number}…")
        profile = get_company_profile(company_number, auth)
        filing_history = get_filing_history(company_number, auth)

        slug = "".join(c if c.isalnum() else "_" for c in company_number)[:16]
        bundle = {"profile": profile, "filing_history": filing_history}
        output_file = write_json(bundle, f"company_uk_{slug}.json")

        print("Consulta completada correctamente.")
        print(f"Archivo guardado en: {output_file.resolve()}")
        print_profile_summary(profile)
        print_filing_history_summary(filing_history, company_number)
        maybe_analyze_ch_filing_with_gemini(
            profile, filing_history, auth, company_number
        )

    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json() if e.response is not None else ""
        except ValueError:
            detail = e.response.text if e.response is not None else ""
        print(f"Error HTTP (Companies House): {e} {detail}")
    except requests.RequestException as e:
        print(f"Error de red: {e}")
