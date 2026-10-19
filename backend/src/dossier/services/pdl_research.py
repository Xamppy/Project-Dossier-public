"""Búsqueda de perfiles de persona vía People Data Labs."""
from __future__ import annotations

from typing import Any

import requests

from dossier.schemas.person_research import PersonResearchRequest
from dossier.services.pdl_client import PdlApiError, PdlClient, pdl_error_message
from dossier.services.pdl_contact_parse import pdl_people_from_search, pdl_person_from_enrich
from dossier.services.pdl_search import build_pdl_enrich_strategies, build_pdl_search_sql
from dossier.services.person_profile_lookup import extract_profile_urls


def _person_to_profile(person: dict[str, Any]) -> dict[str, Any]:
    pid = str(person.get("id") or "").strip() or None
    urls = extract_profile_urls(person, max_urls=3)
    li = person.get("linkedin_url")
    if isinstance(li, str) and li.strip() and li.strip() not in urls:
        urls = [li.strip(), *urls]
    return {
        "provider": "pdl",
        "provider_id": pid,
        "pdl_id": pid,
        "linkedin_urls": urls,
        "data": person,
    }


def _contact_key(profile: dict[str, Any]) -> str:
    pid = profile.get("provider_id") or profile.get("pdl_id")
    if pid:
        return f"pdl:{pid}"
    urls = profile.get("linkedin_urls") or []
    if urls:
        return f"url:{urls[0]}"
    data = profile.get("data") or {}
    name = str(data.get("full_name") or "").strip()
    comp = str(data.get("job_company_name") or "").strip()
    return f"name:{name}|{comp}"


def pdl_failure_reason(statuses: list[int]) -> str:
    """``reason_code`` de una fase PDL en la que fallaron todos los intentos (S5.10)."""
    if any(s in (401, 403) for s in statuses):
        return "upstream_auth_failed"
    if 429 in statuses:
        return "provider_rate_limit"
    if statuses and all(s == 402 for s in statuses):
        return "provider_quota"
    if any(s in (408, 504) for s in statuses):
        return "provider_timeout"
    return "provider_error"


def exception_reason(exc: BaseException) -> str:
    """``reason_code`` de una excepción de proveedor, sin exponer su texto."""
    if isinstance(exc, PdlApiError):
        return pdl_failure_reason([exc.status])
    if isinstance(exc, (TimeoutError, requests.Timeout)):
        return "provider_timeout"
    return "provider_error"


class _Fase:
    """Contadores reales de una fase PDL y su terminal según lo que respondió el proveedor."""

    def __init__(self, progress: Any, stage_id: str) -> None:
        self._progress = progress
        self.stage_id = stage_id
        self.total = 0
        self.fallidos: list[int] = []
        self.encontrados = 0

    def intento(self) -> None:
        if self.total == 0:
            self._progress.stage(self.stage_id, "running")
        self.total += 1

    def _attempts(self) -> dict[str, int]:
        return {"total": self.total, "failed": len(self.fallidos)}

    def fallar(self, reason: str) -> None:
        self._progress.stage(self.stage_id, "failed", reason, attempts=self._attempts())

    def cerrar(self) -> None:
        if self.total and len(self.fallidos) == self.total:
            self.fallar(pdl_failure_reason(self.fallidos))
            return
        motivo = None if self.encontrados else "no_matches"
        self._progress.stage(self.stage_id, "completed", motivo, attempts=self._attempts())


WARN_NO_PERSON_ENRICHMENT = (
    "No se encontró información adicional sobre esta persona. "
    "Añade más información o revisa que el nombre completo sea correcto para mayor exactitud."
)


def fetch_pdl_profiles(
    req: PersonResearchRequest,
    progress: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """
    Devuelve (profiles, search_attempts, warnings).

    Flujo: person/enrich por estrategia → fallback person/search (SQL).

    ``progress`` (S5.10) recibe las etapas ``person.pdl_enrich`` y
    ``person.pdl_search`` con sus intentos reales; no cambia el flujo.
    """
    from dossier.services.dossier_job_progress import NULL_SCOPE

    progress = progress if progress is not None else NULL_SCOPE
    warnings: list[str] = []
    attempts: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        client = PdlClient()
    except ValueError as e:
        warnings.append(str(e))
        progress.stage("person.pdl_enrich", "skipped", "configuration_missing")
        progress.stage("person.pdl_search", "skipped", "configuration_missing")
        return profiles, attempts, warnings

    max_collect = max(8, req.max_profiles * 3)
    estrategias = build_pdl_enrich_strategies(req)
    enrich = _Fase(progress, "person.pdl_enrich")
    if not estrategias:
        progress.stage("person.pdl_enrich", "skipped", "insufficient_input")

    for label, params in estrategias:
        enrich.intento()
        try:
            data = client.person_enrich(params)
        except PdlApiError as e:
            enrich.fallidos.append(e.status)
            attempts.append({
                "strategy": label,
                "params": params,
                "error": str(e),
                "http_status": e.status,
                "provider": "pdl",
            })
            if e.status == 401:
                warnings.append(pdl_error_message(e))
                enrich.fallar("upstream_auth_failed")
                progress.stage("person.pdl_search", "skipped", "upstream_auth_failed")
                return profiles, attempts, warnings
            if e.status == 402:
                # Cuota de person/enrich agotada: seguir con otras estrategias y person/search.
                continue
            continue
        except Exception as e:
            enrich.fallar(exception_reason(e))
            raise

        person = pdl_person_from_enrich(data) if data else None
        if person:
            enrich.encontrados += 1
            profile = _person_to_profile(person)
            key = _contact_key(profile)
            if key not in seen:
                seen.add(key)
                profiles.append(profile)
            likelihood = data.get("likelihood") if isinstance(data, dict) else None
            attempts.append({
                "strategy": label,
                "params": params,
                "response": {
                    "matched": True,
                    "pdl_id": profile.get("provider_id"),
                    "likelihood": likelihood,
                },
                "provider": "pdl",
            })
        else:
            attempts.append({
                "strategy": label,
                "params": params,
                "response": {"_pdlEmptyMatch": True},
                "provider": "pdl",
            })

        if len(profiles) >= max_collect:
            break

    if estrategias:
        enrich.cerrar()

    if len(profiles) >= req.max_profiles:
        progress.stage("person.pdl_search", "skipped", "sufficient_profiles")
    else:
        # SQL con todos los filtros y, si no hay resultados, solo por nombre (empresa/país
        # a veces no coinciden literalmente con cómo PDL almacena los datos).
        sqls: list[tuple[str, str]] = []
        full_sql = build_pdl_search_sql(req, limit=max_collect)
        if full_sql:
            sqls.append(("person/search (SQL)", full_sql))
        name_only_req = req.model_copy(update={"company": None, "country": None, "city": None})
        name_sql = build_pdl_search_sql(name_only_req, limit=max_collect)
        if name_sql and name_sql != full_sql:
            sqls.append(("person/search (solo nombre)", name_sql))

        search = _Fase(progress, "person.pdl_search")
        if not sqls:
            progress.stage("person.pdl_search", "skipped", "insufficient_input")
        for label, sql in sqls:
            if len(profiles) >= req.max_profiles:
                break
            search.intento()
            try:
                search_data = client.person_search(sql=sql, size=max_collect)
                found = pdl_people_from_search(search_data, max_items=max_collect)
                search.encontrados += len(found)
                attempts.append({
                    "strategy": label,
                    "params": {"sql": sql},
                    "response": {"count": len(found), "total": search_data.get("total")},
                    "provider": "pdl",
                })
                for person in found:
                    profile = _person_to_profile(person)
                    key = _contact_key(profile)
                    if key in seen:
                        continue
                    seen.add(key)
                    profiles.append(profile)
                    if len(profiles) >= max_collect:
                        break
            except PdlApiError as e:
                attempts.append({
                    "strategy": label,
                    "params": {"sql": sql},
                    "error": str(e),
                    "http_status": e.status,
                    "provider": "pdl",
                })
                if e.status != 404:  # 404 en search: sin resultados, no un fallo
                    search.fallidos.append(e.status)
                if e.status == 401 or e.status == 402:
                    warnings.append(pdl_error_message(e))
                elif e.status == 404:
                    continue
            except Exception as e:
                search.fallar(exception_reason(e))
                raise
        if sqls:
            search.cerrar()

    profiles = profiles[: req.max_profiles]

    if profiles:
        pass  # éxito: no añadir aviso en UI (profiles_count basta)
    elif attempts:
        failed = [a for a in attempts if "http_status" in a]
        if failed and all(a.get("http_status") in (401, 402) for a in failed):
            warnings.append(pdl_error_message(PdlApiError(int(failed[0]["http_status"]), str(failed[0].get("error") or ""))))
        elif failed and any(a.get("http_status") == 429 for a in failed):
            warnings.append("Límite de solicitudes alcanzado. Espera un momento y reintenta.")
        else:
            warnings.append(WARN_NO_PERSON_ENRICHMENT)

    if req.reveal_contact_details:
        warnings.append(
            "El email y teléfono se incluyen en el match cuando existen; no hay paso «reveal» aparte."
        )

    return profiles, attempts, warnings
