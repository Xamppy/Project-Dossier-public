"""UX-KPI-01 · evidencia mínima de generación contra Postgres real (migración 0003 y servicio).

Requiere ``TEST_DATABASE_URL`` (ver fixture ``pg_vacia`` en conftest.py). Cubre:
- la migración de ida y vuelta, idempotente y coherente con el arranque por parches;
- el relleno desde dossiers vigentes sin inventar el pasado (CA6, CA9);
- el registro idempotente de resultados (CA4), la marca de borrado y la purga (CA8).
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from dossier.db.schema_patches import apply_schema_patches
from dossier.services.meeting_prep_evidence import (
    load_facts,
    mark_dossiers_deleted,
    purge_expired_facts,
    record_generation_fact,
    recording_started_at,
)
from dossier.services.meeting_prep_kpi import meeting_key

REVISION_ANTERIOR = "b7e2d4f1a9c3"
REVISION_0003 = "c5a9e3b7d1f2"
AHORA = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)


def _org_y_usuario(conn) -> tuple[uuid.UUID, uuid.UUID]:
    sufijo = uuid.uuid4().hex[:8]
    org = conn.execute(
        text("INSERT INTO organizations (name, slug) VALUES (:n, :s) RETURNING id"),
        {"n": f"Org {sufijo}", "s": f"org-{sufijo}"},
    ).scalar_one()
    user = conn.execute(
        text("INSERT INTO users (email) VALUES (:e) RETURNING id"),
        {"e": f"u-{sufijo}@example.test"},
    ).scalar_one()
    return org, user


def _dossier(conn, org, user, *, status="complete", trigger="manual", evento_interno=None,
             carpeta=None, rol="corporate", indice=None, calendar=None, completado=AHORA,
             proveedor="google", ext="ev-1", inicio="2026-10-05T13:00:00Z") -> uuid.UUID:
    data: dict = {"billing": "none", "calendar_folder_role": rol}
    if calendar is None and ext is not None:
        calendar = {"provider": proveedor, "external_event_id": ext, "inicio": inicio}
    if calendar is not None:
        data["calendar"] = calendar
    if indice is not None:
        data["person_filters"] = {"contact_index": indice}
    return conn.execute(
        text(
            "INSERT INTO dossiers (organization_id, requested_by_user_id, status, trigger_source, "
            "calendar_event_id, dossier_folder_id, dossier_data, generation_completed_at) "
            "VALUES (:o, :u, :s, :t, :ce, :f, CAST(:d AS JSONB), :c) RETURNING id"
        ),
        {"o": org, "u": user, "s": status, "t": trigger, "ce": evento_interno, "f": carpeta,
         "d": json.dumps(data), "c": completado},
    ).scalar_one()


def _tablas(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


# ── migración ────────────────────────────────────────────────────────────────


def test_upgrade_head_crea_las_tablas_y_registra_desde_cuando(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    assert {"dossier_generation_facts", "prep_evidence_meta"} <= _tablas(pg_vacia)
    with Session(pg_vacia) as s:
        desde = recording_started_at(s)
    assert desde is not None
    assert abs((datetime.now(UTC) - desde).total_seconds()) < 120


def test_la_migracion_es_de_ida_y_vuelta_y_repetible(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, REVISION_ANTERIOR)
    assert not {"dossier_generation_facts", "prep_evidence_meta"} & _tablas(pg_vacia)
    command.upgrade(alembic_cfg, "head")
    assert {"dossier_generation_facts", "prep_evidence_meta"} <= _tablas(pg_vacia)


def test_el_arranque_por_parches_es_idempotente_y_no_pierde_el_registro(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    with Session(pg_vacia) as s:
        antes = recording_started_at(s)
    apply_schema_patches(pg_vacia)
    apply_schema_patches(pg_vacia)
    with Session(pg_vacia) as s:
        assert recording_started_at(s) == antes


def test_el_arranque_por_parches_crea_la_evidencia_en_una_base_sin_alembic(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, REVISION_ANTERIOR)
    assert "dossier_generation_facts" not in _tablas(pg_vacia)
    apply_schema_patches(pg_vacia)
    assert {"dossier_generation_facts", "prep_evidence_meta"} <= _tablas(pg_vacia)


def test_el_origen_solo_admite_manual_o_automatico(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org, user = _org_y_usuario(conn)
    with pytest.raises(IntegrityError), Session(pg_vacia) as s:
        record_generation_fact(
            s, result_key="k", organization_id=org, user_id=user, provider="google",
            external_event_id="e", role_key="corporate", origin="desconocido", dossier_id=None,
            expected_keys=None, meeting_starts_at=None, completed_at=AHORA,
        )
        s.commit()


# ── relleno desde dossiers vigentes (CA6, CA9) ───────────────────────────────


def test_el_relleno_recupera_solo_asociaciones_inequivocas(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, REVISION_ANTERIOR)
    carpeta = uuid.uuid4()
    with pg_vacia.begin() as conn:
        org, user = _org_y_usuario(conn)
        evento_interno = conn.execute(
            text("SELECT uuid_generate_v4()")
        ).scalar_one()
        manual_corp = _dossier(conn, org, user, carpeta=carpeta, rol="corporate")
        manual_per = _dossier(conn, org, user, carpeta=carpeta, rol="person", indice=2)
        # fallida en la misma carpeta: define el conjunto esperado, pero no es un hecho
        _dossier(conn, org, user, carpeta=carpeta, rol="person", indice=3, status="failed")
        auto = _dossier(conn, org, user, trigger="calendar", evento_interno=evento_interno,
                        ext="ev-auto", carpeta=uuid.uuid4())
        # ambiguos o sin evidencia suficiente: no se rellenan
        _dossier(conn, org, user, trigger="calendar", ext="ev-ruta-sincrona", carpeta=uuid.uuid4())
        _dossier(conn, org, user, ext=None, calendar=None, rol="person")  # sin metadatos de calendario
        _dossier(conn, org, user, ext="ev-sin-fin", completado=None, carpeta=uuid.uuid4())
        _dossier(conn, org, user, proveedor="otro", ext="ev-prov-raro", carpeta=uuid.uuid4())
        malo = _dossier(conn, org, user, ext="ev-fecha-mala", inicio="no-es-fecha", carpeta=uuid.uuid4())
    command.upgrade(alembic_cfg, "head")

    with pg_vacia.connect() as conn:
        filas = conn.execute(
            text(
                "SELECT dossier_id, role_key, origin, external_event_id, expected_keys, "
                "meeting_starts_at, generation_completed_at, result_key FROM dossier_generation_facts"
            )
        ).mappings().all()
    por_dossier = {f["dossier_id"]: f for f in filas}
    assert set(por_dossier) == {manual_corp, manual_per, auto, malo}

    assert por_dossier[manual_corp]["role_key"] == "corporate"
    assert por_dossier[manual_corp]["origin"] == "manual"
    assert por_dossier[manual_per]["role_key"] == "person:2"
    assert set(por_dossier[manual_corp]["expected_keys"]) == {"corporate", "person:2", "person:3"}
    assert por_dossier[manual_corp]["meeting_starts_at"] == datetime(2026, 10, 5, 13, 0, tzinfo=UTC)
    assert por_dossier[manual_corp]["generation_completed_at"] == AHORA
    assert por_dossier[auto]["origin"] == "automatic"
    assert por_dossier[malo]["meeting_starts_at"] is None  # no se inventa un inicio
    assert len({f["result_key"] for f in filas}) == len(filas)


def test_ids_iguales_de_proveedores_o_usuarios_distintos_quedan_separados(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, REVISION_ANTERIOR)
    with pg_vacia.begin() as conn:
        org, user_a = _org_y_usuario(conn)
        user_b = conn.execute(
            text("INSERT INTO users (email) VALUES ('b@example.test') RETURNING id")
        ).scalar_one()
        _dossier(conn, org, user_a, proveedor="google", ext="mismo-id", carpeta=uuid.uuid4())
        _dossier(conn, org, user_a, proveedor="microsoft", ext="mismo-id", carpeta=uuid.uuid4())
        _dossier(conn, org, user_b, proveedor="google", ext="mismo-id", carpeta=uuid.uuid4())
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.connect() as conn:
        filas = conn.execute(
            text("SELECT user_id, provider FROM dossier_generation_facts")
        ).all()
    assert sorted((str(u), p) for u, p in filas) == sorted(
        [(str(user_a), "google"), (str(user_a), "microsoft"), (str(user_b), "google")]
    )


def test_el_relleno_no_se_duplica_al_repetir_la_migracion(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, REVISION_ANTERIOR)
    with pg_vacia.begin() as conn:
        org, user = _org_y_usuario(conn)
        _dossier(conn, org, user, carpeta=uuid.uuid4())
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, REVISION_ANTERIOR)
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM dossier_generation_facts")).scalar_one() == 1


# ── servicio: registro idempotente, borrado, purga, aislamiento ───────────────


@pytest.fixture
def base(pg_vacia, alembic_cfg):
    command.upgrade(alembic_cfg, "head")
    with pg_vacia.begin() as conn:
        org, user = _org_y_usuario(conn)
        otro_org, otro_user = _org_y_usuario(conn)
    return pg_vacia, org, user, otro_org, otro_user


def _registrar(s, org, user, *, clave="r1:corporate", rol="corporate", ext="ev-1", origen="manual",
               dossier=None, completado=AHORA, inicio=AHORA + timedelta(days=1), proveedor="google",
               esperado=("corporate",)):
    return record_generation_fact(
        s, result_key=clave, organization_id=org, user_id=user, provider=proveedor,
        external_event_id=ext, role_key=rol, origin=origen, dossier_id=dossier,
        expected_keys=list(esperado) if esperado is not None else None,
        meeting_starts_at=inicio, completed_at=completado,
    )


def test_registrar_el_mismo_resultado_dos_veces_deja_un_solo_hecho(base):
    engine, org, user, _, _ = base
    with Session(engine) as s:
        assert _registrar(s, org, user) is True
        assert _registrar(s, org, user) is False
        s.commit()
        assert len(load_facts(s, organization_id=org, user_id=user, since=AHORA - timedelta(days=1))) == 1


def test_una_regeneracion_con_resultado_nuevo_crea_otro_hecho(base):
    engine, org, user, _, _ = base
    with Session(engine) as s:
        _registrar(s, org, user, clave="job1:corporate")
        _registrar(s, org, user, clave="job2:corporate")
        s.commit()
        assert len(load_facts(s, organization_id=org, user_id=user, since=AHORA - timedelta(days=1))) == 2


def test_load_facts_entrega_la_identidad_compuesta_y_el_conjunto_esperado(base):
    engine, org, user, _, _ = base
    with Session(engine) as s:
        _registrar(s, org, user, proveedor="microsoft", ext="abc", esperado=("corporate", "person:1"))
        s.commit()
        (f,) = load_facts(s, organization_id=org, user_id=user, since=AHORA - timedelta(days=1))
    assert f.meeting_key == meeting_key("microsoft", "abc")
    assert f.expected_keys == frozenset({"corporate", "person:1"})
    assert f.origin == "manual" and f.deleted_at is None


def test_load_facts_no_mezcla_usuarios_ni_organizaciones(base):
    engine, org, user, otro_org, otro_user = base
    with Session(engine) as s:
        _registrar(s, org, user, clave="mio")
        _registrar(s, otro_org, otro_user, clave="ajeno-otra-org")
        _registrar(s, org, otro_user, clave="ajeno-misma-org")
        s.commit()
        mios = load_facts(s, organization_id=org, user_id=user, since=AHORA - timedelta(days=1))
    assert [f.result_key for f in mios] == ["mio"]


def test_load_facts_respeta_la_ventana(base):
    engine, org, user, _, _ = base
    with Session(engine) as s:
        _registrar(s, org, user, clave="viejo", completado=AHORA - timedelta(days=100),
                   inicio=AHORA - timedelta(days=99))
        _registrar(s, org, user, clave="reciente")
        s.commit()
        r = load_facts(s, organization_id=org, user_id=user, since=AHORA - timedelta(days=90))
    assert [f.result_key for f in r] == ["reciente"]


def test_borrar_el_dossier_marca_el_hecho_una_sola_vez(base):
    engine, org, user, _, _ = base
    dossier = uuid.uuid4()
    primero, segundo = AHORA, AHORA + timedelta(days=3)
    with Session(engine) as s:
        _registrar(s, org, user, dossier=dossier)
        _registrar(s, org, user, clave="otro", dossier=uuid.uuid4())
        s.commit()
        assert mark_dossiers_deleted(s, [dossier], when=primero) == 1
        assert mark_dossiers_deleted(s, [dossier], when=segundo) == 0  # no reescribe
        s.commit()
        por_clave = {
            f.result_key: f
            for f in load_facts(s, organization_id=org, user_id=user, since=AHORA - timedelta(days=1))
        }
    assert por_clave["r1:corporate"].deleted_at == primero
    assert por_clave["otro"].deleted_at is None


def test_borrar_sin_dossiers_no_hace_nada(base):
    engine, *_ = base
    with Session(engine) as s:
        assert mark_dossiers_deleted(s, []) == 0


def test_la_purga_elimina_solo_hechos_fuera_de_ventana(base):
    engine, org, user, _, _ = base
    with Session(engine) as s:
        _registrar(s, org, user, clave="vencido", completado=AHORA - timedelta(days=200),
                   inicio=AHORA - timedelta(days=199))
        _registrar(s, org, user, clave="sin-inicio-vencido", completado=AHORA - timedelta(days=200), inicio=None)
        _registrar(s, org, user, clave="vigente", completado=AHORA - timedelta(days=95),
                   inicio=AHORA - timedelta(days=10))  # reunión reciente: se conserva
        _registrar(s, org, user, clave="futuro", inicio=AHORA + timedelta(days=30))
        s.commit()
        assert purge_expired_facts(s, now=AHORA) == 2
        s.commit()
        quedan = {
            f.result_key
            for f in load_facts(s, organization_id=org, user_id=user, since=AHORA - timedelta(days=365))
        }
    assert quedan == {"vigente", "futuro"}


def test_eliminar_el_usuario_o_la_organizacion_borra_su_evidencia(base):
    engine, org, user, otro_org, otro_user = base
    with Session(engine) as s:
        _registrar(s, org, user, clave="a")
        _registrar(s, otro_org, otro_user, clave="b")
        s.commit()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": otro_user})
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM dossier_generation_facts")).scalar_one() == 0
