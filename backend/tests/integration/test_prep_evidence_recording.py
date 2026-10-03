"""UX-KPI-01 · la generación registra su evidencia (CA3, CA4, CA6, CA8, CA9).

Contra Postgres real y con el pipeline de IA sustituido por resultados fijos: lo que se
verifica es qué hecho queda escrito, quién lo inició y qué ocurre al borrar el documento.
Requiere ``TEST_DATABASE_URL`` (fixture ``pg_vacia``).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.models import (
    CalendarEvent,
    CalendarIntegration,
    Dossier,
    DossierGenerationFact,
    DossierGenerationJob,
    Organization,
    User,
)
from dossier.services import calendar_automation
from dossier.services import dossier_generation_job_service as jobs
from dossier.services.calendar_event_dossiers import (
    parse_calendar_event_for_dossiers,
    persist_calendar_dossiers,
)
from dossier.services.dossier_deletion_service import delete_dossier_record
from dossier.services.dossier_retention_worker import purge_expired_dossiers

INICIO = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)


@pytest.fixture
def db(pg_vacia, alembic_cfg, monkeypatch):
    command.upgrade(alembic_cfg, "head")
    # `dossier_generation_jobs` solo existe como modelo ORM: ni Migracion.md ni Alembic la crean
    # (en desarrollo la crea `create_all` al arrancar). Se crea aquí igual que lo haría la app.
    DossierGenerationJob.__table__.create(bind=pg_vacia, checkfirst=True)
    monkeypatch.setenv("DOSSIER_CHARGE_CREDITS", "0")  # sin triggers de cobro: aquí no se prueba el cobro
    with Session(pg_vacia) as s:
        yield s


def _org(db: Session, plan="pro") -> Organization:
    sufijo = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {sufijo}", slug=f"org-{sufijo}", plan=plan, credits_balance=100)
    db.add(org)
    db.commit()
    return org


def _user(db: Session, retention: int | None = 30) -> User:
    u = User(email=f"u-{uuid.uuid4().hex[:8]}@example.test", dossier_retention_days=retention)
    db.add(u)
    db.commit()
    return u


def _reunion(ext="ev-1", inicio=INICIO, descripcion="Empresa: Tesla\nContacto 1: Ana Pérez\nContacto 2: Luis Gómez"):
    return {
        "id": ext,
        "tema": "Reunión comercial — Tesla",
        "descripcion": descripcion,
        "participantes": "yo@mi-empresa.test, ana@tesla.test",
        "inicio": inicio.strftime("%Y-%m-%dT%H:%M:%SZ") if inicio else "",
        "fin": "",
        "ubicacion": "",
        "todo_el_dia": False,
    }


def _resultado(reunion=None, *, corp="# Dossier Tesla\ncuerpo", personas=None, plan_free=False,
               cache_corp=False, cache_persona=False) -> dict[str, Any]:
    reunion = reunion or _reunion()
    parsed = parse_calendar_event_for_dossiers(reunion)
    if personas is None:
        personas = [(1, "Ana Pérez", "# Ana\ninforme"), (2, "Luis Gómez", None)]  # el segundo falla
    return {
        "reunion": reunion,
        "parse": parsed,
        "dossier_corporativo": corp,
        "dossier_persona": next((md for _, _, md in personas if md), None),
        "dossier_personas": [
            {"index": i, "full_name": n, "md": md, "payload": None, "cache_hit": cache_persona,
             "cache_key": None, "email": None}
            for i, n, md in personas
        ],
        "errors": [],
        "corporate_cache_hit": cache_corp,
        "person_cache_hit": cache_persona,
        "corporate_skipped_plan_free": plan_free,
        "output_language": "es",
    }


def _persistir(db, org, user, resultado, **kw):
    kw.setdefault("calendar_provider", "google")
    kw.setdefault("generation_duration_ms", 10)
    kw.setdefault("charge_credits", False)
    return persist_calendar_dossiers(db, user_id=user.id, org_id=org.id, result=resultado, **kw)


def _hechos(db, user=None) -> list[DossierGenerationFact]:
    stmt = select(DossierGenerationFact).order_by(DossierGenerationFact.role_key)
    if user is not None:
        stmt = stmt.where(DossierGenerationFact.user_id == user.id)
    return list(db.scalars(stmt).all())


# ── persistencia ─────────────────────────────────────────────────────────────


def test_un_hecho_por_dossier_completo_con_su_origen_conjunto_esperado_e_inicio(db):
    org, user = _org(db), _user(db)
    res = _persistir(db, org, user, _resultado(), trigger_source="manual", generation_origin="manual")
    hechos = _hechos(db)
    assert [h.role_key for h in hechos] == ["corporate", "person:1"]  # person:2 falló: no es un resultado exitoso
    assert {h.origin for h in hechos} == {"manual"}
    assert all(set(h.expected_keys) == {"corporate", "person:1", "person:2"} for h in hechos)
    assert all(h.meeting_starts_at == INICIO for h in hechos)
    assert all((h.provider, h.external_event_id, h.calendar_key) == ("google", "ev-1", "primary") for h in hechos)
    assert all(h.user_id == user.id and h.organization_id == org.id for h in hechos)
    dossier = db.get(Dossier, uuid.UUID(res["saved_dossiers"]["corporate"]["id"]))
    corp = next(h for h in hechos if h.role_key == "corporate")
    assert corp.dossier_id == dossier.id
    assert corp.generation_completed_at == dossier.generation_completed_at  # finalización real, no updated_at


def test_ca9_la_finalizacion_registrada_nunca_es_updated_at(db):
    org, user = _org(db), _user(db)
    res = _persistir(db, org, user, _resultado(), trigger_source="manual", generation_origin="manual")
    dossier = db.get(Dossier, uuid.UUID(res["saved_dossiers"]["corporate"]["id"]))
    dossier.updated_at = dossier.generation_completed_at + timedelta(days=3)  # edición posterior cualquiera
    db.commit()
    assert _hechos(db)[0].generation_completed_at == dossier.generation_completed_at


def test_los_resultados_fallidos_no_dejan_hecho(db):
    org, user = _org(db), _user(db)
    res = _resultado(corp="# Error en dossier corporativo\nfalló", personas=[(1, "Ana Pérez", None)])
    _persistir(db, org, user, res, trigger_source="manual", generation_origin="manual")
    assert _hechos(db) == []


def test_ca4_un_reintento_de_la_misma_persistencia_no_duplica_hechos(db):
    org, user = _org(db), _user(db)
    corrida = str(uuid.uuid4())
    for _ in range(2):
        _persistir(db, org, user, _resultado(), trigger_source="manual", generation_origin="manual",
                   generation_run_key=corrida)
    assert [h.role_key for h in _hechos(db)] == ["corporate", "person:1"]


def test_ca4_una_regeneracion_con_resultado_nuevo_si_cuenta(db):
    org, user = _org(db), _user(db)
    for _ in range(2):
        _persistir(db, org, user, _resultado(), trigger_source="manual", generation_origin="manual",
                   generation_run_key=str(uuid.uuid4()))
    assert len(_hechos(db)) == 4


def test_un_resultado_recuperado_de_cache_tambien_deja_hecho_aunque_no_cobre(db):
    org, user = _org(db), _user(db)
    res = _resultado(cache_corp=True, cache_persona=True)
    _persistir(db, org, user, res, trigger_source="manual", generation_origin="manual")
    assert [h.role_key for h in _hechos(db)] == ["corporate", "person:1"]


def test_el_origen_se_deduce_del_disparador_cuando_no_se_indica(db):
    org, user = _org(db), _user(db)
    _persistir(db, org, user, _resultado(_reunion("ev-m")), trigger_source="manual")
    _persistir(db, org, user, _resultado(_reunion("ev-a")), trigger_source="calendar",
               calendar_event_id=uuid.uuid4())
    origenes = {h.external_event_id: h.origin for h in _hechos(db)}
    assert origenes == {"ev-m": "manual", "ev-a": "automatic"}


def test_sin_origen_demostrable_no_se_inventa_uno(db):
    """Disparador «calendar» sin evento interno ni origen explícito: no se sabe quién lo inició."""
    org, user = _org(db), _user(db)
    _persistir(db, org, user, _resultado(), trigger_source="calendar")
    assert _hechos(db) == []


def test_en_plan_free_el_conjunto_esperado_no_incluye_el_corporativo(db):
    org, user = _org(db, plan="free"), _user(db)
    res = _resultado(corp=None, plan_free=True, personas=[(1, "Ana Pérez", "# Ana\ninforme")])
    _persistir(db, org, user, res, trigger_source="manual", generation_origin="manual")
    (h,) = _hechos(db)
    assert h.role_key == "person:1"
    assert set(h.expected_keys) == {"person:1", "person:2"}  # el corporativo no se exige en Free


def test_sin_id_de_evento_no_hay_reunion_asociada_y_no_se_registra(db):
    org, user = _org(db), _user(db)
    res = _resultado(_reunion(ext=""))
    _persistir(db, org, user, res, trigger_source="manual", generation_origin="manual")
    assert _hechos(db) == []


def test_un_inicio_ilegible_se_guarda_como_null_sin_sustituirlo(db):
    org, user = _org(db), _user(db)
    res = _resultado(_reunion(inicio=None))
    _persistir(db, org, user, res, trigger_source="manual", generation_origin="manual")
    assert all(h.meeting_starts_at is None for h in _hechos(db))


# ── borrado y retención (CA8) ────────────────────────────────────────────────


def test_borrar_el_dossier_marca_el_hecho_sin_borrarlo(db):
    org, user = _org(db), _user(db)
    res = _persistir(db, org, user, _resultado(), trigger_source="manual", generation_origin="manual")
    dossier = db.get(Dossier, uuid.UUID(res["saved_dossiers"]["corporate"]["id"]))
    delete_dossier_record(db, dossier)
    db.commit()
    por_rol = {h.role_key: h for h in _hechos(db)}
    assert por_rol["corporate"].dossier_deleted_at is not None
    assert por_rol["person:1"].dossier_deleted_at is None
    assert db.get(Dossier, dossier.id) is None


def test_la_retencion_borra_el_documento_pero_conserva_el_hecho(db):
    org, user = _org(db, ), _user(db, retention=7)
    res = _persistir(db, org, user, _resultado(), trigger_source="manual", generation_origin="manual")
    ids = [uuid.UUID(res["saved_dossiers"][k]["id"]) for k in ("corporate",)]
    db.execute(
        text("UPDATE dossiers SET created_at = :c WHERE id = ANY(:ids)"),
        {"c": datetime.now(UTC) - timedelta(days=20), "ids": ids},
    )
    db.commit()
    assert purge_expired_dossiers(db) >= 1
    assert db.get(Dossier, ids[0]) is None
    corp = next(h for h in _hechos(db) if h.role_key == "corporate")
    assert corp.dossier_deleted_at is not None
    assert corp.generation_completed_at is not None  # el hecho histórico sigue ahí


# ── job manual y automatización ──────────────────────────────────────────────


def _integracion(db, user, org, provider="google") -> CalendarIntegration:
    i = CalendarIntegration(user_id=user.id, organization_id=org.id, provider=provider,
                            provider_email="yo@mi-empresa.test")
    db.add(i)
    db.commit()
    return i


def _evento_interno(db, integ, user, org, ext="ev-1") -> CalendarEvent:
    ev = CalendarEvent(calendar_integration_id=integ.id, organization_id=org.id, user_id=user.id,
                       external_event_id=ext, starts_at=INICIO, processing_status="detected")
    db.add(ev)
    db.commit()
    return ev


def _job(db, user, org, ext="ev-1", provider="google") -> DossierGenerationJob:
    job = DossierGenerationJob(
        id=uuid.uuid4(), organization_id=org.id, requested_by_user_id=user.id, status="queued",
        job_type="calendar_manual", calendar_provider=provider, external_event_id=ext,
        reunion_snapshot=_reunion(ext), depth_level="standard", credits_estimated=0,
    )
    db.add(job)
    db.commit()
    return job


@pytest.fixture
def pipeline_falso(monkeypatch):
    """Sustituye lectura fresca del evento y generación con IA por un resultado fijo."""
    monkeypatch.setattr(jobs, "_refresh_reunion_for_job", lambda *a, snapshot, **k: dict(snapshot or {}))

    def _generar(reunion, **_):
        return _resultado(reunion)

    monkeypatch.setattr(jobs, "generate_dossiers_from_calendar_event", _generar)


def test_el_job_manual_registra_origen_manual_con_la_corrida_del_job(db, pipeline_falso):
    org, user = _org(db), _user(db)
    job = _job(db, user, org)
    jobs.process_dossier_generation_job(db, job.id)
    db.refresh(job)
    assert job.status == "completed"  # corporativo y persona 1 completos; persona 2 fallida
    hechos = _hechos(db)
    assert {h.origin for h in hechos} == {"manual"}
    assert {h.result_key for h in hechos} == {f"{job.id}:corporate", f"{job.id}:person:1"}
    assert all(h.user_id == user.id for h in hechos)


def test_ca6_el_job_manual_enlaza_el_evento_interno_cuando_existe(db, pipeline_falso):
    org, user = _org(db), _user(db)
    evento = _evento_interno(db, _integracion(db, user, org), user, org)
    job = _job(db, user, org)
    jobs.process_dossier_generation_job(db, job.id)
    dossiers = list(db.scalars(select(Dossier)).all())
    assert dossiers and all(d.calendar_event_id == evento.id for d in dossiers)
    assert all(d.trigger_source == "manual" for d in dossiers)


def test_ca6_el_enlace_no_cruza_proveedores_ni_usuarios(db, pipeline_falso):
    org, user, otro = _org(db), _user(db), _user(db)
    _evento_interno(db, _integracion(db, otro, org), otro, org)  # mismo id, otro usuario
    _evento_interno(db, _integracion(db, user, org, provider="microsoft"), user, org)  # mismo id, otro proveedor
    job = _job(db, user, org)
    jobs.process_dossier_generation_job(db, job.id)
    assert all(d.calendar_event_id is None for d in db.scalars(select(Dossier)).all())
    assert _hechos(db, user)  # aun sin evento interno, el hecho queda con su identidad compuesta


def test_un_job_que_falla_no_registra_hechos(db, monkeypatch):
    org, user = _org(db), _user(db)
    job = _job(db, user, org)
    monkeypatch.setattr(jobs, "_refresh_reunion_for_job", lambda *a, snapshot, **k: dict(snapshot or {}))

    def _explota(*a, **k):
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr(jobs, "generate_dossiers_from_calendar_event", _explota)
    jobs.process_dossier_generation_job(db, job.id)
    db.refresh(job)
    assert job.status == "failed"
    assert _hechos(db) == []


def test_la_automatizacion_registra_origen_automatico_con_su_evento(db, monkeypatch):
    org, user = _org(db), _user(db)
    integ = _integracion(db, user, org)
    evento = _evento_interno(db, integ, user, org)
    evento.processing_status = "scheduled"
    evento.dossier_scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
    evento.starts_at = datetime.now(UTC) + timedelta(minutes=10)
    db.commit()
    monkeypatch.setattr(calendar_automation, "_reunion_for_processing", lambda *a, **k: _reunion())
    monkeypatch.setattr(calendar_automation, "generate_dossiers_from_calendar_event", lambda r, **_: _resultado(r))
    stats = calendar_automation.process_due_calendar_events(db)
    assert stats["processed"] == 1
    hechos = _hechos(db)
    assert {h.origin for h in hechos} == {"automatic"}
    assert all(d.calendar_event_id == evento.id for d in db.scalars(select(Dossier)).all())


def test_la_ruta_sincrona_antigua_registra_origen_manual(db, monkeypatch):
    """GET/POST /calendario/generar-dossiers persisten con disparador «calendar» sin evento."""
    import sys

    import dossier.api.app  # noqa: F401  (registra el módulo)

    app_module = sys.modules["dossier.api.app"]
    org, user = _org(db), _user(db)
    monkeypatch.setattr(app_module, "generate_dossiers_from_calendar_event", lambda r, **_: _resultado(r))
    app_module._run_calendar_dossier_batch(
        db, user=user, org=org, reuniones=[_reunion()], calendar_provider="google", org_ctx="", depth="basic",
    )
    assert {h.origin for h in _hechos(db)} == {"manual"}
    assert all(d.trigger_source == "calendar" for d in db.scalars(select(Dossier)).all())  # sin cambiar etiquetas
