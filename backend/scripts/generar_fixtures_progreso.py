#!/usr/bin/env python3
"""Genera las fixtures de progreso de S5.10 para el frontend de S5.4.

Corre jobs reales (worker, grafo corporativo, investigación de personas y
guardado) contra una base de pruebas, con **todos** los proveedores simulados, y
guarda los frames SSE que publicó el backend, con IDs y fechas normalizados.

    TEST_DATABASE_URL=postgresql://usuario@127.0.0.1:5432/algo_test \\
        backend/.venv/bin/python backend/scripts/generar_fixtures_progreso.py

Borra el esquema ``public`` de esa base, como las pruebas: se niega a correr si
el nombre de la base no contiene «test». Ninguna llamada sale a la red.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

RAIZ = Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "specs" / "fixtures" / "S5.10-progreso"
FECHA_FIJA = "2026-10-15T12:00:00+00:00"
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

os.environ.update(
    {
        "DOSSIER_REDIS_ENABLED": "0",
        "DOSSIER_GENERATION_WORKER_ENABLED": "0",
        "CALENDAR_AUTOMATION_ENABLED": "0",
        "DATABASE_AUTO_CREATE_TABLES": "0",
    }
)


def _sin_red() -> None:
    real = socket.socket.connect

    def connect(self: socket.socket, direccion: Any, *a: Any, **k: Any) -> Any:
        host = direccion[0] if isinstance(direccion, tuple) else direccion
        if str(host) not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"El generador no sale a la red ({host}).")
        return real(self, direccion, *a, **k)

    socket.socket.connect = connect  # type: ignore[method-assign]


# --- normalización ----------------------------------------------------------------


class Normalizador:
    """UUID → marcador estable por orden de aparición; fechas ISO → una fecha fija."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def _id(self, valor: str) -> str:
        if valor not in self._ids:
            self._ids[valor] = f"00000000-0000-4000-8000-{len(self._ids) + 1:012d}"
        return self._ids[valor]

    def __call__(self, dato: Any) -> Any:
        if isinstance(dato, dict):
            return {k: self(v) for k, v in dato.items()}
        if isinstance(dato, list):
            return [self(v) for v in dato]
        if isinstance(dato, str):
            if _ISO.match(dato):
                return FECHA_FIJA
            return _UUID.sub(lambda m: self._id(m.group(0)), dato)
        return dato


# --- proveedores simulados -----------------------------------------------------------


PAYLOAD_VALIDO = json.dumps(
    {
        "meeting_context": {},
        "executive_summary": "Ana Prueba dirige Empresa de Prueba SA desde 2019.",
        "participants": [{"name": "Ana Prueba"}],
        "conversation_starters": [],
        "final_recommendation": {"overall_risk": "low", "decision": "proceed"},
        "confidence_assessment": {"high_confidence": ["Cargo actual según registros profesionales."]},
    }
)


class PdlFalso:
    """Encuentra a Ana Prueba; a nadie más."""

    def person_enrich(self, params: dict[str, Any]) -> dict[str, Any] | None:
        if "ana" not in json.dumps(params).lower():
            return None
        return {
            "data": {
                "id": "pdl-ficticio-1",
                "full_name": "Ana Prueba",
                "job_title": "Directora general",
                "job_company_name": "Empresa de Prueba SA",
                "linkedin_url": "https://www.linkedin.com/in/ana-prueba-ficticia",
            },
            "likelihood": 8,
        }

    def person_search(self, **_: Any) -> dict[str, Any]:
        return {"data": [], "total": 0}


def _lanza(exc: BaseException) -> Callable[..., Any]:
    def _f(*_a: Any, **_k: Any) -> Any:
        raise exc

    return _f


@contextmanager
def proveedores(
    *,
    clave_llm: str = "clave-ficticia",
    sintesis: list[str] | None = None,
    contextual: Callable[..., str] | None = None,
    contexto_deshabilitado: bool = False,
) -> Iterator[None]:
    import dossier.llm.text_generate as llm
    import dossier.services.corporate_registry_context as ctx
    from dossier.eu_registry.agent import ResultadoAgenteEuropeo
    from dossier.news.agent import ResultadoRecoleccionPrensa
    from dossier.services import calendar_event_dossiers as cal
    from dossier.services import pdl_research, person_research_service

    respuestas = list(sintesis or [PAYLOAD_VALIDO])
    env = {"DEEPSEEK_DISABLE_PERSON_WEB": "1"} if contexto_deshabilitado else {}
    with ExitStack() as pila:
        pila.enter_context(mock.patch.dict(os.environ, env))
        if not contexto_deshabilitado:
            os.environ.pop("DEEPSEEK_DISABLE_PERSON_WEB", None)
        parches: list[tuple[Any, str, Any]] = [
            (pdl_research, "PdlClient", PdlFalso),
            (person_research_service, "deepseek_api_key", lambda: clave_llm),
            (
                person_research_service,
                "analyze_person_with_google_search",
                contextual or (lambda **_: "## Informe con IA\n\nAna Prueba, según el encargo y el contexto."),
            ),
            (
                person_research_service,
                "analyze_person_profile_bundle",
                lambda **_: "## Informe de respaldo\n\nAna Prueba dirige Empresa de Prueba SA.",
            ),
            (
                __import__("dossier.llm.structured_synthesis", fromlist=["x"]),
                "chat_completion",
                lambda *_a, **_k: respuestas.pop(0) if len(respuestas) > 1 else respuestas[0],
            ),
            (ctx, "build_uk_corporate_context_markdown", _lanza(RuntimeError("Companies House no responde"))),
            (ctx, "build_us_corporate_context_markdown", lambda p: "## USA\n\nRegistro ficticio.\n"),
            (llm, "generate_text_with_llm", lambda user, system_instruction=None: "# Dossier corporativo\n\nResumen ficticio."),
            (cal, "resolve_corporate_brief", lambda q: (q, "dual")),
        ]
        for objetivo, nombre, valor in parches:
            pila.enter_context(mock.patch.object(objetivo, nombre, valor))
        pila.enter_context(
            mock.patch("dossier.eu_registry.agent.run_eu_registry_agent", lambda e, **_: ResultadoAgenteEuropeo())
        )
        pila.enter_context(
            mock.patch(
                "dossier.news.agent.collect_press_mentions",
                lambda e, **_: ResultadoRecoleccionPrensa(mentions=[]),
            )
        )
        yield


# --- base de datos y jobs ------------------------------------------------------------


def preparar_base() -> tuple[Any, uuid.UUID, uuid.UUID]:
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from alembic import command
    from dossier.db.settings import _database_url_for_sqlalchemy

    crudo = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if not crudo:
        sys.exit("Falta TEST_DATABASE_URL (una base de pruebas: su esquema se borra).")
    url = make_url(_database_url_for_sqlalchemy(crudo))
    if "test" not in (url.database or ""):
        sys.exit("TEST_DATABASE_URL debe apuntar a una base cuyo nombre contenga «test».")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    cfg = Config()
    cfg.set_main_option("script_location", str(RAIZ / "backend" / "alembic"))
    command.upgrade(cfg, "head")
    with engine.begin() as conn:
        org_id = conn.execute(
            text(
                "INSERT INTO organizations (name, slug, plan, credits_balance) "
                "VALUES ('Organización de prueba', 'org-fixtures', 'pro', 1000) RETURNING id"
            )
        ).scalar_one()
        user_id = conn.execute(
            text("INSERT INTO users (email) VALUES ('fixtures@example.com') RETURNING id")
        ).scalar_one()
    return engine, org_id, user_id


def crear_job(engine: Any, org_id: uuid.UUID, user_id: uuid.UUID, **campos: Any) -> uuid.UUID:
    from sqlalchemy.orm import Session

    from dossier.db.models import DossierGenerationJob

    with Session(engine) as db:
        job = DossierGenerationJob(
            organization_id=org_id, requested_by_user_id=user_id, status="queued", **campos
        )
        db.add(job)
        db.commit()
        return job.id


def job_persona(engine: Any, org_id: uuid.UUID, user_id: uuid.UUID, fuente: str, **extra: Any) -> uuid.UUID:
    pedido = {
        "full_name": "Ana Prueba",
        "company": "Empresa de Prueba SA",
        "research_source": fuente,
        "max_profiles": 1,
        **extra,
    }
    return crear_job(
        engine,
        org_id,
        user_id,
        job_type="person_manual",
        external_event_id=f"person:{uuid.uuid4().hex}",
        reunion_snapshot={"person_request": pedido},
        depth_level="basic",
        meeting_label="Ana Prueba",
        credits_estimated=1,
    )


def procesar(engine: Any, job_id: uuid.UUID) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from sqlalchemy.orm import Session

    from dossier.db.models import DossierGenerationJob
    from dossier.services import dossier_progress_events as bus
    from dossier.services.dossier_generation_job_service import (
        process_dossier_generation_job,
        serialize_job,
    )

    with Session(engine) as db:
        process_dossier_generation_job(db, job_id)
    with Session(engine) as db:
        final = serialize_job(db.get(DossierGenerationJob, job_id))
    frames = [{"id": seq, "event": evento, "data": datos} for seq, evento, datos in bus.events_since(job_id, 0)]
    bus.forget(job_id)
    return frames, final


# --- escenarios ------------------------------------------------------------------------


def escenarios(engine: Any, org_id: uuid.UUID, user_id: uuid.UUID) -> Iterator[tuple[str, str, Any]]:
    from sqlalchemy.orm import Session

    from dossier.db.models import DossierGenerationJob
    from dossier.services import dossier_generation_job_service as servicio
    from dossier.services import person_research_pipeline

    def calendario() -> Any:
        job_id = crear_job(
            engine,
            org_id,
            user_id,
            job_type="calendar_manual",
            calendar_provider="google",
            external_event_id=None,
            reunion_snapshot={
                "tema": "Kick-off con Empresa de Prueba SA",
                "descripcion": (
                    "Empresa: Empresa de Prueba SA\n"
                    "Contacto 1: Ana Prueba\nCargo 1: Directora general\n"
                    "Contacto 2: Beto Ficticio\nCargo 2: Gerente"
                ),
                "participantes": "",
                "inicio": "2026-10-20T10:00:00Z",
            },
            depth_level="standard",
            meeting_label="Kick-off con Empresa de Prueba SA",
            credits_estimated=5,
        )
        with proveedores(contexto_deshabilitado=True):
            return procesar(engine, job_id)

    yield (
        "calendario-agente-caido",
        "Calendario Google: el agente UK falla y el resto completa; Ana Prueba se encuentra en PDL "
        "y Beto Ficticio no (su dossier queda failed). Análisis contextual deshabilitado.",
        calendario,
    )

    def pdl() -> Any:
        with proveedores():
            return procesar(engine, job_persona(engine, org_id, user_id, "pdl", email="ana@example.com"))

    yield ("personas-pdl", "Personas / Registros PDL: enrich encuentra el perfil y la síntesis JSON valida.", pdl)

    def pdl_respaldo() -> Any:
        with proveedores(sintesis=["no es JSON", "tampoco es JSON"]):
            return procesar(engine, job_persona(engine, org_id, user_id, "pdl", email="ana@example.com"))

    yield (
        "personas-pdl-respaldo",
        "Personas / PDL: el JSON no valida y el respaldo Markdown recupera el informe (recovered_by).",
        pdl_respaldo,
    )

    def pdl_sin_informe() -> Any:
        with proveedores(clave_llm=""):
            return procesar(engine, job_persona(engine, org_id, user_id, "pdl", email="ana@example.com"))

    yield (
        "personas-pdl-informe-fallido",
        "Personas / PDL sin clave de LLM: hay perfiles (parcial person_profiles) pero no informe; "
        "el job termina failed y el dossier guardado es failed.",
        pdl_sin_informe,
    )

    def web() -> Any:
        with proveedores():
            return procesar(engine, job_persona(engine, org_id, user_id, "gemini_web"))

    yield (
        "personas-web-publica",
        "Personas / Web pública: una llamada a DeepSeek sin buscador (live_web_search=false); "
        "el texto solo aparece cuando vuelve la llamada.",
        web,
    )

    def web_fallida() -> Any:
        with proveedores(contextual=_lanza(RuntimeError("DeepSeek no responde"))):
            return procesar(engine, job_persona(engine, org_id, user_id, "gemini_web"))

    yield (
        "personas-web-publica-fallida",
        "Personas / Web pública con el modelo caído: context_analysis failed y ningún parcial.",
        web_fallida,
    )

    def cache() -> Any:
        antigua = {
            "markdown": "## Informe en caché\n\nAna Prueba dirige Empresa de Prueba SA.",
            "profiles_count": 2,
            "profile_urls": [],
            "warnings": [],
        }
        with proveedores(), ExitStack() as pila:
            for nombre, valor in (
                ("redis_person_cache_available", lambda: True),
                ("get_person_cached_payload", lambda fp: dict(antigua)),
                ("run_with_person_cache_lock", lambda fp, fn: fn()),
            ):
                pila.enter_context(mock.patch.object(person_research_pipeline, nombre, valor))
            return procesar(engine, job_persona(engine, org_id, user_id, "pdl", email="ana@example.com"))

    yield (
        "personas-cache",
        "Personas / PDL desde caché antigua: profiles_count=2 sin perfiles; nada se ejecuta de nuevo "
        "y no se cobra.",
        cache,
    )

    def cancelada() -> Any:
        job_id = job_persona(engine, org_id, user_id, "pdl", email="ana@example.com")
        original = person_research_pipeline.run_person_research

        def investigar_y_cancelar(body: Any, **kwargs: Any) -> Any:
            progress = kwargs["progress"]
            progress.stage("person.pdl_enrich", "running")
            with Session(engine) as db:
                servicio.cancel_dossier_generation_job(db, job=db.get(DossierGenerationJob, job_id))
            return original(body, **kwargs)

        with proveedores(), mock.patch.object(person_research_pipeline, "run_person_research", investigar_y_cancelar):
            return procesar(engine, job_id)

    yield (
        "personas-cancelada",
        "Personas / PDL cancelado durante la investigación: el progreso se cierra al cancelar y los "
        "callbacks posteriores no se publican. El guardado ya iniciado no se deshace.",
        cancelada,
    )


def main() -> None:
    _sin_red()
    engine, org_id, user_id = preparar_base()
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre, descripcion, correr in escenarios(engine, org_id, user_id):
        frames, final = correr()
        normalizar = Normalizador()
        salida = {
            "escenario": nombre,
            "descripcion": descripcion,
            "contrato": "docs/architecture/decisions/0009-contrato-progreso-por-scopes.md",
            "generado_por": "backend/scripts/generar_fixtures_progreso.py",
            "frames": normalizar(frames),
            "snapshot_final": normalizar(final),
        }
        ruta = DESTINO / f"{nombre}.json"
        ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{ruta.relative_to(RAIZ)}: {len(frames)} frames, job {final['status']}")


if __name__ == "__main__":
    main()
