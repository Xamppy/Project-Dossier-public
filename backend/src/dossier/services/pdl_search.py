"""Estrategias de búsqueda PDL (person/enrich + person/search SQL)."""
from __future__ import annotations

import contextlib
import re
from typing import Any

from dossier.schemas.person_research import PersonResearchRequest
from dossier.services.lusha_company import company_search_variants
from dossier.services.person_profile_lookup import split_person_name


def _name_splits(name: str) -> list[tuple[str, str]]:
    """
    Variantes (first_name, last_name) para nombres de 3+ partes.

    Muchos proveedores guardan solo un nombre y un apellido, así que para
    «Victor Escobar Jeria» probamos tanto «Victor» / «Escobar Jeria» como
    «Victor» / «Jeria» y «Victor Escobar» / «Jeria».
    """
    parts = name.split()
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def push(first: str, last: str) -> None:
        first = first.strip()
        last = last.strip()
        if not first or not last:
            return
        key = (first.lower(), last.lower())
        if key not in seen:
            seen.add(key)
            out.append((first, last))

    if len(parts) < 2:
        return out
    if len(parts) == 2:
        push(parts[0], parts[1])
        return out
    # 3+ partes: cubrir las combinaciones más frecuentes.
    push(parts[0], parts[-1])
    push(" ".join(parts[:-1]), parts[-1])
    push(parts[0], " ".join(parts[1:]))
    return out

# Literales permitidos en el dialecto SQL de People Data Labs (API externa, no PostgreSQL).
_PDL_SAFE_LITERAL = re.compile(r"^[\w\s\-'.@áéíóúÁÉÍÓÚñÑüÜ&,]+$")
_PDL_ALLOWED_FIELDS = frozenset({
    "first_name",
    "last_name",
    "full_name",
    "job_company_name",
    "location_country",
})


def _pdl_query_literal(value: str, *, max_len: int = 255) -> str:
    """Escapa y valida un literal para consultas PDL."""
    v = " ".join(value.strip().split())[:max_len]
    if not v:
        raise ValueError("valor vacío para consulta PDL")
    if not _PDL_SAFE_LITERAL.match(v):
        raise ValueError("caracteres no permitidos en consulta PDL")
    return v.replace("'", "''")


def _equals_clause(field: str, value: str) -> str:
    if field not in _PDL_ALLOWED_FIELDS:
        raise ValueError(f"campo PDL no permitido: {field}")
    return f"{field}='{_pdl_query_literal(value)}'"


def _email_domain_clause(domain: str) -> str:
    dom = _pdl_query_literal(domain, max_len=120)
    if "@" in dom or " " in dom:
        raise ValueError("dominio de email inválido para consulta PDL")
    return f"work_email LIKE '%@{dom}'"


def _normalize_linkedin(url: str) -> str:
    u = url.strip()
    if not u:
        return u
    if not u.startswith("http"):
        u = f"https://{u.lstrip('/')}"
    return u


def _last_name_spelling_variants(last: str) -> list[str]:
    """Variantes ortográficas frecuentes (p. ej. Jeria / Jerias)."""
    base = last.strip()
    if len(base) < 3:
        return [base] if base else []
    variants = [base]
    if base.endswith("s") and len(base) > 4:
        variants.append(base[:-1])
    elif not base.endswith("s"):
        variants.append(f"{base}s")
    out: list[str] = []
    seen: set[str] = set()
    for v in variants:
        key = v.lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _person_name_pairs(full_name: str) -> list[tuple[str, str, str]]:
    """
    Variantes (etiqueta, first_name, last_name) para nombres de varias palabras.

    PDL suele indexar «Victor Escobar Jeria» como first_name=Victor, last_name=Jeria.
    """
    name = " ".join(full_name.strip().split())
    parts = name.split()
    if len(parts) < 2:
        return []

    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, first: str, last: str) -> None:
        key = (first.casefold(), last.casefold())
        if key in seen:
            return
        seen.add(key)
        out.append((label, first, last))

    add("apellido final", " ".join(parts[:-1]), parts[-1])
    if len(parts) >= 3:
        add("primer nombre + apellido", parts[0], parts[-1])
        add("nombre + apellidos", parts[0], " ".join(parts[1:]))
    else:
        add("nombre + apellido", parts[0], parts[1])
    return out


def _assemble_search_sql(clauses: list[str]) -> str:
    where = " AND ".join(clauses)
    return "SELECT * FROM person WHERE " + where  # nosec B608


def _extra_search_clauses(req: PersonResearchRequest) -> list[str]:
    clauses: list[str] = []
    em = (req.email or "").strip().lower()
    if em and "@" in em:
        domain = em.split("@", 1)[1]
        if domain:
            clauses.append(_email_domain_clause(domain))
    if req.country:
        clauses.append(_equals_clause("location_country", req.country.strip()))
    return clauses


def build_pdl_search_sql_candidates(req: PersonResearchRequest) -> list[tuple[str, str]]:
    """Consultas SQL de mayor a menor especificidad (person/search)."""
    name = req.full_name.strip()
    if len(name) < 2:
        return []

    candidates: list[tuple[str, str]] = []
    seen_sql: set[str] = set()
    companies = company_search_variants(req.company)
    extras = _extra_search_clauses(req)

    def push(label: str, sql: str) -> None:
        if sql in seen_sql:
            return
        seen_sql.add(sql)
        candidates.append((label, sql))

    _, _, single = split_person_name(name)
    if single:
        push("full_name", _assemble_search_sql([_equals_clause("full_name", single), *extras]))

    for pair_label, first, last in _person_name_pairs(name):
        for last_v in _last_name_spelling_variants(last):
            suffix = f" ({last_v})" if last_v != last else ""
            name_clause = (
                "("
                + _equals_clause("first_name", first)
                + " AND "
                + _equals_clause("last_name", last_v)
                + ")"
            )
            for comp in companies:
                push(
                    f"{pair_label} + empresa ({comp[:32]}){suffix}",
                    _assemble_search_sql([name_clause, _equals_clause("job_company_name", comp), *extras]),
                )
            push(
                f"{pair_label}{suffix}",
                _assemble_search_sql([name_clause, *extras]),
            )

    return candidates


def build_pdl_enrich_strategies(req: PersonResearchRequest) -> list[tuple[str, dict[str, Any]]]:
    """Parámetros para GET /v5/person/enrich (una estrategia por intento)."""
    strategies: list[tuple[str, dict[str, Any]]] = []
    seen: set[frozenset[tuple[str, str]]] = set()

    def add(label: str, params: dict[str, Any]) -> None:
        clean = {k: v for k, v in params.items() if v is not None and str(v).strip()}
        if not clean:
            return
        key = frozenset((k, str(v)) for k, v in sorted(clean.items()))
        if key in seen:
            return
        seen.add(key)
        strategies.append((label, clean))

    em = (req.email or "").strip().lower()
    if em and "@" in em:
        add("email", {"email": em})

    li = _normalize_linkedin(req.linkedin_url or "")
    if li:
        add("profile (LinkedIn)", {"profile": li})

    name = req.full_name.strip()
    _first, _last, single = split_person_name(name)
    companies = company_search_variants(req.company)
    location = ", ".join(
        p for p in [(req.city or "").strip(), (req.country or "").strip()] if p
    )

    # person/enrich exige al menos 2 señales fuertes; solo nombre+apellido da HTTP 400.
    # Combinamos nombre con empresa, ubicación o país (lo que haya disponible).
    has_extra_signal = bool(companies or location or req.country)

    splits = _name_splits(name)
    # Las variantes ortográficas de apellido solo tienen sentido con nombres simples
    # (2 partes); en nombres compuestos multiplicarían las llamadas sin aportar.
    multi_split = len(splits) > 1

    for first_v, last_v in splits:
        last_variants = [last_v] if multi_split else _last_name_spelling_variants(last_v)
        for last_variant in last_variants:
            tag = f"[{first_v}/{last_variant}]"
            for comp in companies:
                add(f"nombre + company ({comp[:40]}) {tag}", {
                    "first_name": first_v,
                    "last_name": last_variant,
                    "company": comp,
                })
            if location:
                add(f"nombre + location {tag}", {
                    "first_name": first_v,
                    "last_name": last_variant,
                    "location": location,
                })
            elif req.country:
                add(f"nombre + country {tag}", {
                    "first_name": first_v,
                    "last_name": last_variant,
                    "country": req.country.strip(),
                })

    if single and companies:
        add("name + company", {"name": single, "company": companies[0]})

    # Si no hay ninguna señal extra, un único intento por nombre completo (PDL lo tolera).
    if not has_extra_signal and name and len(name) >= 2:
        add("full name", {"name": name})

    return strategies


def _name_clause(name: str) -> str | None:
    """Cláusula de nombre tolerante a varias divisiones first/last."""
    _first, _last, single = split_person_name(name)
    if single:
        return _equals_clause("full_name", single)

    or_parts: list[str] = []
    seen: set[str] = set()

    def push(clause: str) -> None:
        if clause not in seen:
            seen.add(clause)
            or_parts.append(clause)

    for first_v, last_v in _name_splits(name):
        for last_variant in _last_name_spelling_variants(last_v):
            push(
                "("
                + _equals_clause("first_name", first_v)
                + " AND "
                + _equals_clause("last_name", last_variant)
                + ")"
            )

    # También el nombre completo por si el proveedor no separa igual.
    with contextlib.suppress(ValueError):
        push(_equals_clause("full_name", name))

    if not or_parts:
        return None
    if len(or_parts) == 1:
        return or_parts[0]
    return "(" + " OR ".join(or_parts) + ")"


def build_pdl_search_sql(req: PersonResearchRequest, *, limit: int = 5) -> str | None:
    """SQL fallback para POST /v5/person/search."""
    name = req.full_name.strip()
    if len(name) < 2:
        return None

    clauses: list[str] = []
    name_clause = _name_clause(name)
    if not name_clause:
        return None
    clauses.append(name_clause)

    companies = company_search_variants(req.company)
    if companies:
        clauses.append(_equals_clause("job_company_name", companies[0]))

    em = (req.email or "").strip().lower()
    if em and "@" in em:
        domain = em.split("@", 1)[1]
        if domain:
            clauses.append(_email_domain_clause(domain))

    if req.country:
        clauses.append(_equals_clause("location_country", req.country.strip()))

    where = " AND ".join(clauses)
    # PDL no admite LIMIT en el SQL; el tope va en el parámetro ``size`` de person/search.
    return "SELECT * FROM person WHERE " + where  # nosec B608
