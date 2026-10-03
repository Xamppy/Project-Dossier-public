"""UX-KPI-01 · GET /dashboard/summary contra Postgres real (CA1–CA5, CA10–CA13).

El calendario es simulado (páginas de Google/Graph); la base de datos y la autenticación
son reales. Requiere ``TEST_DATABASE_URL`` (fixture ``pg_vacia``).
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from alembic import command
from dossier.api.app import app
from dossier.api.auth_routes import get_db_if_configured
from dossier.db.models import (
    CalendarIntegration,
    Dossier,
    DossierGenerationJob,
    Organization,
    OrgMembership,
    User,
)
from dossier.security.jwt_tokens import create_access_token
from dossier.services import dashboard_summary as ds
from dossier.services.calendar_range import ErrorProveedorCalendario, ResultadoRango
from dossier.services.meeting_prep_evidence import record_generation_fact

AHORA = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)


class Mundo:
    """Org, usuarios, integraciones, calendarios simulados y utilidades de siembra."""

    def __init__(self, engine, monkeypatch):
        self.engine = engine
        self.s = Session(engine)
        self.monkeypatch = monkeypatch
        self.calendarios: dict[str, ResultadoRango | Exception] = {}
        self.llamadas: list[str] = []
        self.org = self.org_nueva(plan="pro")
        self.user = self.usuario(self.org, "yo", role="user")

    # siembra ----------------------------------------------------------------
    def org_nueva(self, plan="pro", balance=42, limite=500) -> Organization:
        sufijo = uuid.uuid4().hex[:8]
        o = Organization(name=f"O{sufijo}", slug=f"o-{sufijo}", plan=plan,
                         credits_balance=balance, credits_monthly_limit=limite)
        self.s.add(o)
        self.s.commit()
        return o

    def usuario(self, org, nombre, role="user", retencion=None) -> User:
        u = User(email=f"{nombre}-{uuid.uuid4().hex[:6]}@mi-empresa.test", dossier_retention_days=retencion)
        self.s.add(u)
        self.s.flush()
        self.s.add(OrgMembership(organization_id=org.id, user_id=u.id, role=role, is_primary_org=True))
        self.s.commit()
        if retencion is None:  # el ORM aplica el valor por defecto (30) a un None explícito
            self.s.execute(text("UPDATE users SET dossier_retention_days = NULL WHERE id = :i"), {"i": u.id})
            self.s.commit()
            self.s.refresh(u)
        return u

    def integracion(self, user, org, provider="google"):
        self.s.add(CalendarIntegration(user_id=user.id, organization_id=org.id, provider=provider,
                                       provider_email=user.email, access_token_encrypted="t"))
        self.s.commit()

    def token(self, user=None, org=None, role="user") -> dict:
        user, org = user or self.user, org or self.org
        t = create_access_token(user_id=str(user.id), email=user.email,
                                organization_id=str(org.id), role=role)
        return {"Authorization": f"Bearer {t}"}

    # calendario -------------------------------------------------------------
    def reunion(self, i, inicio, **extra) -> dict:
        r = {
            "id": f"ev{i}", "tema": "Reunión comercial — Tesla",
            "descripcion": "Empresa: Tesla\nContacto: Ana Pérez",
            "participantes": "yo@mi-empresa.test, ana@tesla.test",
            "correos": ["yo@mi-empresa.test", "ana@tesla.test"],
            "inicio": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fin": (inicio + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ubicacion": "", "todo_el_dia": False,
        }
        r.update(extra)
        return r

    def calendario(self, provider, reuniones, completo=True, motivo=None):
        self.calendarios[provider] = ResultadoRango(reuniones=list(reuniones), completo=completo,
                                                    motivo_incompleto=motivo)

    # dossiers y hechos --------------------------------------------------------
    def dossier_vivo(self, user, org, ext, rol="corporate", indice=None, provider="google",
                     status="complete"):
        data = {"billing": "none", "calendar_folder_role": rol,
                "calendar": {"provider": provider, "external_event_id": ext}}
        if indice:
            data["person_filters"] = {"contact_index": indice}
        self.s.execute(
            text("INSERT INTO dossiers (organization_id, requested_by_user_id, status, dossier_data) "
                 "VALUES (:o, :u, :s, CAST(:d AS JSONB))"),
            {"o": org.id, "u": user.id, "s": status, "d": json.dumps(data)},
        )
        self.s.commit()

    def hecho(self, user, org, i, rol, completado, inicio, *, origen="manual", clave=None,
              esperado=("corporate",), provider="google", borrado=None):
        record_generation_fact(
            self.s, result_key=clave or f"{uuid.uuid4()}", organization_id=org.id, user_id=user.id,
            provider=provider, external_event_id=f"ev{i}", role_key=rol, origin=origen,
            dossier_id=None, expected_keys=list(esperado), meeting_starts_at=inicio,
            completed_at=completado,
        )
        if borrado is not None:
            self.s.execute(text("UPDATE dossier_generation_facts SET dossier_deleted_at = :b "
                                "WHERE result_key = :k"), {"b": borrado, "k": clave})
        self.s.commit()


@pytest.fixture
def mundo(pg_vacia, alembic_cfg, monkeypatch):
    command.upgrade(alembic_cfg, "head")
    DossierGenerationJob.__table__.create(bind=pg_vacia, checkfirst=True)
    m = Mundo(pg_vacia, monkeypatch)
    # el historial es fiable desde mucho antes: salvo en las pruebas que lo cambian expresamente
    m.s.execute(text("UPDATE prep_evidence_meta SET recording_started_at = :t"),
                {"t": AHORA - timedelta(days=120)})
    m.s.commit()
    ds.SUMMARY_CACHE.clear()
    monkeypatch.setattr(ds, "_utcnow", lambda: AHORA)

    def _db():
        with Session(pg_vacia) as sesion:
            yield sesion

    app.dependency_overrides[get_db_if_configured] = _db

    def _lector(nombre):
        def _leer(token, rango, **_):
            m.llamadas.append(nombre)
            r = m.calendarios.get(nombre)
            if isinstance(r, Exception):
                raise r
            assert r is not None, f"calendario {nombre} no simulado"
            return r
        return _leer

    monkeypatch.setattr(ds, "listar_reuniones_google_rango", _lector("google"))
    monkeypatch.setattr(ds, "listar_reuniones_rango", _lector("microsoft"))
    monkeypatch.setattr(ds, "get_google_calendar_access_token_for_user", lambda db, uid: "tok-g")
    monkeypatch.setattr(ds, "get_microsoft_graph_access_token_for_user", lambda db, uid: "tok-m")
    yield m
    app.dependency_overrides.pop(get_db_if_configured, None)
    m.s.close()


@pytest.fixture
def client():
    return TestClient(app)


def _pedir(client, mundo, **kw):
    r = client.get("/dashboard/summary", headers=mundo.token(**kw))
    assert r.status_code == 200, r.text
    return r.json()


# ── contrato y autenticación ─────────────────────────────────────────────────


def test_requiere_autenticacion(client, mundo):
    assert client.get("/dashboard/summary").status_code == 401
    assert client.get("/dashboard/summary", headers={"Authorization": "Bearer basura"}).status_code == 401


def test_el_contrato_tiene_las_tres_secciones_y_ningun_dato_personal(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [])
    cuerpo = _pedir(client, mundo)
    assert set(cuerpo) == {"as_of", "timezone", "upcoming", "history", "credits"}
    assert set(cuerpo["upcoming"]) == {
        "state", "reason", "measured_from", "measured_to", "from", "to",
        "eligible_meetings", "prepared_meetings", "pending_meetings", "coverage_percent",
    }
    assert set(cuerpo["history"]) == {
        "state", "reason", "measured_from", "measured_to", "from", "to", "eligible_meetings",
        "manually_prepared_on_time_meetings", "on_time_percent", "manual_on_time_dossiers",
    }
    assert set(cuerpo["credits"]) == {"state", "reason", "measured_from", "measured_to", "balance", "monthly_limit"}
    assert "yo@mi-empresa.test" not in json.dumps(cuerpo)  # sin correos ni títulos


def test_no_acepta_user_id_ni_organization_id_del_cliente(client, mundo):
    otro = mundo.usuario(mundo.org, "otro")
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [])
    r = client.get(f"/dashboard/summary?user_id={otro.id}&organization_id={uuid.uuid4()}",
                   headers=mundo.token())
    assert r.status_code == 200
    assert mundo.llamadas == ["google"]  # se resolvió con la sesión, no con los parámetros


# ── CA1: próximas reuniones ──────────────────────────────────────────────────


def test_ca1_cinco_futuras_tres_preparadas_dos_pendientes_sesenta_por_ciento(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(i, AHORA + timedelta(days=1, hours=i)) for i in range(5)])
    for i in range(3):
        mundo.dossier_vivo(mundo.user, mundo.org, f"ev{i}", "corporate")
        mundo.dossier_vivo(mundo.user, mundo.org, f"ev{i}", "person", indice=1)
    up = _pedir(client, mundo)["upcoming"]
    assert (up["state"], up["eligible_meetings"], up["prepared_meetings"], up["pending_meetings"],
            up["coverage_percent"]) == ("ok", 5, 3, 2, 60.0)
    assert up["from"] == "2026-10-03T15:00:00Z" and up["to"] == "2026-10-10T15:00:00Z"


def test_ca7_un_dossier_de_los_dos_esperados_no_prepara(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1))])
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "corporate")  # falta la persona
    assert _pedir(client, mundo)["upcoming"]["prepared_meetings"] == 0
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "person", indice=1)
    ds.SUMMARY_CACHE.clear()
    assert _pedir(client, mundo)["upcoming"]["prepared_meetings"] == 1


def test_un_dossier_fallido_no_prepara(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1))])
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "corporate", status="failed")
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "person", indice=1, status="failed")
    assert _pedir(client, mundo)["upcoming"]["prepared_meetings"] == 0


def test_borrar_un_dossier_antes_de_la_reunion_la_devuelve_a_pendiente(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1))])
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "corporate")
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "person", indice=1)
    assert _pedir(client, mundo)["upcoming"]["pending_meetings"] == 0
    mundo.s.execute(text("DELETE FROM dossiers WHERE dossier_data->>'calendar_folder_role' = 'person'"))
    mundo.s.commit()
    ds.SUMMARY_CACHE.clear()
    assert _pedir(client, mundo)["upcoming"]["pending_meetings"] == 1


# ── CA2/CA3/CA8: historial ───────────────────────────────────────────────────


def _pasadas(mundo, n=8):
    inicios = [AHORA - timedelta(days=2 + i) for i in range(n)]
    mundo.calendario("google", [mundo.reunion(i, t) for i, t in enumerate(inicios)])
    return inicios


def test_ca2_ocho_pasadas_seis_a_tiempo_once_dossiers_setenta_y_cinco_por_ciento(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    inicios = _pasadas(mundo)
    for i in range(5):
        mundo.hecho(mundo.user, mundo.org, i, "corporate", inicios[i] - timedelta(hours=3), inicios[i],
                    esperado=("corporate", "person:1"))
        mundo.hecho(mundo.user, mundo.org, i, "person:1", inicios[i] - timedelta(hours=2), inicios[i],
                    esperado=("corporate", "person:1"))
    mundo.hecho(mundo.user, mundo.org, 5, "corporate", inicios[5] - timedelta(hours=3), inicios[5])
    h = _pedir(client, mundo)["history"]
    assert (h["state"], h["eligible_meetings"], h["manually_prepared_on_time_meetings"], h["on_time_percent"],
            h["manual_on_time_dossiers"]) == ("ok", 8, 6, 75.0, 11)
    assert h["from"] == "2026-09-03T15:00:00Z" and h["measured_from"] == h["from"]


def test_ca3_automatico_de_otro_usuario_o_posterior_al_inicio_no_acredita(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    inicios = _pasadas(mundo, 4)
    otro = mundo.usuario(mundo.org, "otro")
    mundo.hecho(mundo.user, mundo.org, 0, "corporate", inicios[0] - timedelta(hours=1), inicios[0], origen="automatic")
    mundo.hecho(otro, mundo.org, 1, "corporate", inicios[1] - timedelta(hours=1), inicios[1])  # lo generó otra persona
    mundo.hecho(mundo.user, mundo.org, 2, "corporate", inicios[2] + timedelta(minutes=1), inicios[2])  # tarde
    h = _pedir(client, mundo)["history"]
    assert (h["manually_prepared_on_time_meetings"], h["manual_on_time_dossiers"], h["on_time_percent"]) == (0, 0, 0.0)


def test_ca8_documento_borrado_despues_de_la_reunion_conserva_el_hecho(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    inicios = _pasadas(mundo, 2)
    mundo.hecho(mundo.user, mundo.org, 0, "corporate", inicios[0] - timedelta(hours=1), inicios[0], clave="a",
                borrado=inicios[0] + timedelta(days=7))
    mundo.hecho(mundo.user, mundo.org, 1, "corporate", inicios[1] - timedelta(hours=1), inicios[1], clave="b",
                borrado=inicios[1] - timedelta(minutes=30))  # borrado antes de la reunión
    h = _pedir(client, mundo)["history"]
    assert (h["manually_prepared_on_time_meetings"], h["manual_on_time_dossiers"]) == (1, 1)


def test_ca9_historial_parcial_declara_el_intervalo_realmente_medido(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.user.dossier_retention_days = 7  # los dossiers viejos ya se purgaron: no hay evidencia previa
    mundo.s.commit()
    desde = AHORA - timedelta(days=5)
    mundo.s.execute(text("UPDATE prep_evidence_meta SET recording_started_at = :t"), {"t": desde})
    mundo.s.commit()
    mundo.calendario("google", [mundo.reunion(0, AHORA - timedelta(days=20)), mundo.reunion(1, AHORA - timedelta(days=2))])
    h = _pedir(client, mundo)["history"]
    assert h["state"] == "partial" and h["reason"] == "history_partial_evidence"
    assert h["measured_from"] == "2026-09-28T15:00:00Z" and h["from"] == "2026-09-03T15:00:00Z"
    assert h["eligible_meetings"] == 1  # la reunión de hace 20 días queda fuera de lo verificable


def test_sin_retencion_el_historial_es_fiable_aunque_la_evidencia_sea_reciente(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.s.execute(text("UPDATE prep_evidence_meta SET recording_started_at = :t"), {"t": AHORA - timedelta(days=2)})
    mundo.s.commit()
    mundo.calendario("google", [mundo.reunion(0, AHORA - timedelta(days=20))])
    h = _pedir(client, mundo)["history"]
    assert h["state"] == "ok" and h["eligible_meetings"] == 1


def test_sin_tabla_de_evidencia_el_historial_no_se_inventa_pero_lo_demas_responde(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1))])
    mundo.s.execute(text("DROP TABLE dossier_generation_facts"))
    mundo.s.commit()
    cuerpo = _pedir(client, mundo)
    assert cuerpo["history"]["state"] == "unavailable" and cuerpo["history"]["reason"] == "evidence_unavailable"
    assert cuerpo["history"]["on_time_percent"] is None
    assert cuerpo["upcoming"]["state"] == "ok" and cuerpo["credits"]["balance"] == 42


# ── CA5: volumen y paginación ────────────────────────────────────────────────


def test_ca5_mas_de_ochenta_dossiers_y_varias_paginas_dan_totales_completos(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    n = 120
    reuniones = [mundo.reunion(i, AHORA + timedelta(hours=1 + i)) for i in range(n)]  # 120 reuniones en 7 días
    mundo.calendario("google", reuniones)
    for i in range(n):
        mundo.dossier_vivo(mundo.user, mundo.org, f"ev{i}", "corporate")
        mundo.dossier_vivo(mundo.user, mundo.org, f"ev{i}", "person", indice=1)
    up = _pedir(client, mundo)["upcoming"]
    assert (up["eligible_meetings"], up["prepared_meetings"], up["coverage_percent"]) == (n, n, 100.0)


def test_ca5_una_pagina_incompleta_no_entrega_un_porcentaje_aparentemente_definitivo(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1))], completo=False, motivo="error_proveedor")
    cuerpo = _pedir(client, mundo)
    for k in ("upcoming", "history"):
        assert cuerpo[k]["state"] == "unavailable" and cuerpo[k]["reason"] == "calendar_incomplete"
    assert cuerpo["upcoming"]["coverage_percent"] is None and cuerpo["history"]["on_time_percent"] is None
    assert cuerpo["upcoming"]["eligible_meetings"] is None
    assert cuerpo["credits"]["state"] == "ok"


# ── CA11: estados distintos ──────────────────────────────────────────────────


def test_ca11_sin_calendario_conectado_no_afirma_cero_reuniones(client, mundo):
    cuerpo = _pedir(client, mundo)
    assert cuerpo["upcoming"]["state"] == "not_connected" and cuerpo["upcoming"]["reason"] == "no_calendar_connected"
    assert cuerpo["upcoming"]["eligible_meetings"] is None and cuerpo["history"]["state"] == "not_connected"
    assert cuerpo["credits"] == {"state": "ok", "reason": None, "measured_from": None, "measured_to": None,
                                 "balance": 42, "monthly_limit": 500}


def test_ca11_conectado_sin_reuniones_es_empty_con_porcentaje_null(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [])
    cuerpo = _pedir(client, mundo)
    for k in ("upcoming", "history"):
        assert cuerpo[k]["state"] == "empty" and cuerpo[k]["reason"] == "no_meetings_in_period"
        assert cuerpo[k]["eligible_meetings"] == 0
    assert cuerpo["upcoming"]["coverage_percent"] is None and cuerpo["history"]["on_time_percent"] is None


def test_ca11_un_cero_real_requiere_denominador_positivo(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1))])
    up = _pedir(client, mundo)["upcoming"]
    assert up["state"] == "ok" and up["coverage_percent"] == 0.0 and up["pending_meetings"] == 1


@pytest.mark.parametrize(
    "error,motivo",
    [
        (ErrorProveedorCalendario(502, "Token inválido", reautenticar=True), "calendar_reauth_required"),
        (ErrorProveedorCalendario(504, "tarda"), "calendar_unavailable"),
        (ErrorProveedorCalendario(502, "falla"), "calendar_unavailable"),
    ],
)
def test_ca11_error_de_consulta_es_unavailable_y_los_creditos_siguen_visibles(client, mundo, error, motivo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendarios["google"] = error
    cuerpo = _pedir(client, mundo)
    assert cuerpo["upcoming"]["state"] == "unavailable" and cuerpo["upcoming"]["reason"] == motivo
    assert cuerpo["upcoming"]["eligible_meetings"] is None
    assert cuerpo["credits"]["balance"] == 42


def test_un_proveedor_caido_invalida_ambos_no_se_calcula_con_uno_solo(client, mundo):
    mundo.integracion(mundo.user, mundo.org, "google")
    mundo.integracion(mundo.user, mundo.org, "microsoft")
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1))])
    mundo.calendarios["microsoft"] = ErrorProveedorCalendario(502, "falla")
    up = _pedir(client, mundo)["upcoming"]
    assert up["state"] == "unavailable" and up["coverage_percent"] is None


def test_token_que_no_se_puede_renovar_pide_reconectar(client, mundo, monkeypatch):
    from fastapi import HTTPException

    def _sin_token(db, uid):
        raise HTTPException(status_code=401, detail="expiró")

    mundo.integracion(mundo.user, mundo.org)
    monkeypatch.setattr(ds, "get_google_calendar_access_token_for_user", _sin_token)
    assert _pedir(client, mundo)["upcoming"]["reason"] == "calendar_reauth_required"


# ── CA10: dos proveedores ────────────────────────────────────────────────────


def test_ca10_misma_ocurrencia_en_google_y_outlook_cuenta_una_vez(client, mundo):
    mundo.integracion(mundo.user, mundo.org, "google")
    mundo.integracion(mundo.user, mundo.org, "microsoft")
    inicio = AHORA + timedelta(days=1)
    mundo.calendario("google", [mundo.reunion(0, inicio, ical_uid="uid-1")])
    mundo.calendario("microsoft", [mundo.reunion(9, inicio, ical_uid="uid-1")])
    mundo.dossier_vivo(mundo.user, mundo.org, "ev9", "corporate", provider="microsoft")
    mundo.dossier_vivo(mundo.user, mundo.org, "ev9", "person", indice=1, provider="microsoft")
    up = _pedir(client, mundo)["upcoming"]
    assert (up["eligible_meetings"], up["prepared_meetings"]) == (1, 1)


def test_ids_iguales_de_proveedores_distintos_no_se_mezclan(client, mundo):
    mundo.integracion(mundo.user, mundo.org, "google")
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1))])
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "corporate", provider="microsoft")
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "person", indice=1, provider="microsoft")
    assert _pedir(client, mundo)["upcoming"]["prepared_meetings"] == 0


# ── CA12: aislamiento ────────────────────────────────────────────────────────


def test_ca12_dossiers_y_hechos_de_otro_usuario_u_organizacion_no_se_ven(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    inicios = _pasadas(mundo, 2)
    mundo.calendarios["google"].reuniones.append(mundo.reunion(7, AHORA + timedelta(days=1)))
    otro = mundo.usuario(mundo.org, "otro")
    otra_org = mundo.org_nueva()
    ajeno = mundo.usuario(otra_org, "ajeno")
    for u, o in ((otro, mundo.org), (ajeno, otra_org)):
        mundo.dossier_vivo(u, o, "ev7", "corporate")
        mundo.dossier_vivo(u, o, "ev7", "person", indice=1)
        mundo.hecho(u, o, 0, "corporate", inicios[0] - timedelta(hours=1), inicios[0])
    cuerpo = _pedir(client, mundo)
    assert cuerpo["upcoming"]["prepared_meetings"] == 0
    assert cuerpo["history"]["manual_on_time_dossiers"] == 0


def test_un_admin_sigue_viendo_solo_sus_propios_indicadores_personales(client, mundo):
    admin = mundo.usuario(mundo.org, "admin", role="admin")
    mundo.integracion(mundo.user, mundo.org)
    mundo.integracion(admin, mundo.org)
    inicios = _pasadas(mundo, 1)
    mundo.hecho(mundo.user, mundo.org, 0, "corporate", inicios[0] - timedelta(hours=1), inicios[0])
    cuerpo = _pedir(client, mundo, user=admin, org=mundo.org, role="admin")
    assert cuerpo["history"]["manual_on_time_dossiers"] == 0
    assert cuerpo["credits"]["balance"] == 42  # el saldo sí es de la organización


def test_un_viewer_puede_consultar_sus_indicadores(client, mundo):
    viewer = mundo.usuario(mundo.org, "viewer", role="viewer")
    mundo.integracion(viewer, mundo.org)
    mundo.calendario("google", [])
    assert _pedir(client, mundo, user=viewer, role="viewer")["upcoming"]["state"] == "empty"


# ── CA13: leer no crea jobs ni cobra; cache e invalidación ────────────────────


def _estado(mundo):
    s = mundo.s
    s.expire_all()
    return (
        s.scalar(select(func.count()).select_from(DossierGenerationJob)),
        s.scalar(select(func.count()).select_from(Dossier)),
        s.scalar(select(Organization.credits_balance).where(Organization.id == mundo.org.id)),
        s.execute(text("SELECT count(*) FROM calendar_events")).scalar_one(),
    )


def test_ca13_consultar_el_resumen_no_crea_jobs_ni_dossiers_ni_cobra_ni_programa(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(i, AHORA + timedelta(days=1, hours=i)) for i in range(3)])
    antes = _estado(mundo)
    for _ in range(3):
        _pedir(client, mundo)
        ds.SUMMARY_CACHE.clear()
    assert _estado(mundo) == antes


def test_la_cache_evita_releer_el_calendario_y_se_separa_por_usuario(client, mundo):
    otro = mundo.usuario(mundo.org, "otro")
    mundo.integracion(mundo.user, mundo.org)
    mundo.integracion(otro, mundo.org)
    mundo.calendario("google", [])
    _pedir(client, mundo)
    _pedir(client, mundo)
    assert mundo.llamadas == ["google"]
    _pedir(client, mundo, user=otro)  # otro usuario: no comparte caché
    assert mundo.llamadas == ["google", "google"]


def test_los_creditos_no_se_cachean(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [])
    assert _pedir(client, mundo)["credits"]["balance"] == 42
    mundo.s.execute(text("UPDATE organizations SET credits_balance = 40 WHERE id = :o"), {"o": mundo.org.id})
    mundo.s.commit()
    assert _pedir(client, mundo)["credits"]["balance"] == 40


def test_generar_un_dossier_invalida_la_cache_del_usuario(client, mundo):
    from dossier.services.calendar_event_dossiers import (
        parse_calendar_event_for_dossiers,
        persist_calendar_dossiers,
    )

    mundo.integracion(mundo.user, mundo.org)
    reunion = mundo.reunion(0, AHORA + timedelta(days=1), descripcion="Empresa: Tesla")
    mundo.calendario("google", [reunion])
    assert _pedir(client, mundo)["upcoming"]["prepared_meetings"] == 0
    parsed = parse_calendar_event_for_dossiers(reunion)
    persist_calendar_dossiers(
        mundo.s, user_id=mundo.user.id, org_id=mundo.org.id, calendar_provider="google",
        generation_duration_ms=1, charge_credits=False, trigger_source="manual", generation_origin="manual",
        result={"reunion": reunion, "parse": parsed, "dossier_corporativo": "# Tesla\ncuerpo",
                "dossier_personas": [], "errors": [], "output_language": "es"},
    )
    assert _pedir(client, mundo)["upcoming"]["prepared_meetings"] == 1  # sin limpiar la caché a mano


def test_borrar_un_dossier_invalida_la_cache(client, mundo):
    from dossier.services.dossier_deletion_service import delete_dossier_record

    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [mundo.reunion(0, AHORA + timedelta(days=1), descripcion="Empresa: Tesla")])
    mundo.dossier_vivo(mundo.user, mundo.org, "ev0", "corporate")
    assert _pedir(client, mundo)["upcoming"]["prepared_meetings"] == 1
    d = mundo.s.scalars(select(Dossier)).first()
    delete_dossier_record(mundo.s, d)
    mundo.s.commit()
    assert _pedir(client, mundo)["upcoming"]["prepared_meetings"] == 0


def test_los_estados_de_error_no_se_quedan_en_cache_mucho_tiempo(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendarios["google"] = ErrorProveedorCalendario(502, "falla")
    assert _pedir(client, mundo)["upcoming"]["state"] == "unavailable"
    mundo.calendario("google", [])
    ds.SUMMARY_CACHE.expire_errors()  # equivale a esperar el TTL corto de los errores
    assert _pedir(client, mundo)["upcoming"]["state"] == "empty"


def test_el_periodo_es_movil_y_no_mes_calendario(client, mundo):
    mundo.integracion(mundo.user, mundo.org)
    mundo.calendario("google", [])
    h = _pedir(client, mundo)["history"]
    assert h["from"] == "2026-09-03T15:00:00Z" and h["to"] == "2026-10-03T15:00:00Z"
