"""UX-KPI-01 · lógica pura de los indicadores de Resumen (CA1–CA4, CA6, CA7, CA10).

Sin base de datos ni red: la elegibilidad, el conjunto esperado, la preparación y el costo
estimado de lo que falta se calculan sobre datos ya leídos. Cada prueba nombra su criterio.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dossier.services.meeting_prep_kpi import (
    CalendarEntry,
    Meeting,
    collect_meetings,
    expected_roles,
    meeting_key,
    parse_start,
    preparation_role_cost,
    summarize_preparation_cost,
    summarize_upcoming,
)

AS_OF = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)
OWNER = "mi-empresa.test"


def _reunion(i: int, inicio: datetime, **extra) -> dict:
    base = {
        "id": f"ev{i}",
        "tema": "Reunión comercial — Tesla",
        "descripcion": "Empresa: Tesla\nContacto: Ana Pérez",
        "participantes": "yo@mi-empresa.test (organizador), ana@tesla.test",
        "correos": ["yo@mi-empresa.test", "ana@tesla.test"],
        "inicio": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fin": (inicio + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ubicacion": "",
        "todo_el_dia": False,
    }
    base.update(extra)
    return base


def _entrada(i, inicio, provider="google", **extra) -> CalendarEntry:
    return CalendarEntry(
        provider=provider,
        calendar_key="primary",
        owner_domain=OWNER,
        reunion=_reunion(i, inicio, **extra),
    )


def _meeting(i, inicio, expected=("corporate", "person:1"), provider="google") -> Meeting:
    return Meeting(
        keys=(meeting_key(provider, f"ev{i}"),),
        starts_at=inicio,
        expected=frozenset(expected),
    )


# ── identidad y lectura ──────────────────────────────────────────────────────


def test_la_identidad_incluye_proveedor_calendario_y_evento():
    assert meeting_key("google", "abc") != meeting_key("microsoft", "abc")
    assert meeting_key("google", "abc", "primary") != meeting_key("google", "abc", "otro")
    assert meeting_key("google", "abc") == meeting_key("google", "abc", "primary")


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("2026-10-05T10:00:00-03:00", datetime(2026, 10, 5, 13, 0, tzinfo=UTC)),
        ("2026-10-05T13:00:00Z", datetime(2026, 10, 5, 13, 0, tzinfo=UTC)),
        ("2026-10-05", None),  # fecha sin hora: día completo, no es una reunión con inicio
        ("2026-10-05T13:00:00", None),  # sin offset: ambiguo, no se adivina
        ("", None),
        (None, None),
        ("no-es-fecha", None),
    ],
)
def test_parse_start_solo_acepta_instantes_con_offset(valor, esperado):
    assert parse_start(valor) == esperado


# ── conjunto esperado (CA7) ──────────────────────────────────────────────────


def test_el_conjunto_esperado_es_empresa_mas_cada_contacto():
    r = _reunion(1, AS_OF, descripcion="Empresa: Tesla\nContacto 1: Ana Pérez\nContacto 2: Luis Gómez")
    assert expected_roles(r, "pro") == {"corporate", "person:1", "person:2"}


def test_en_plan_free_el_corporativo_no_se_exige():
    """CA7 — un módulo que el plan no incluye no se exige para dar la reunión por preparada."""
    r = _reunion(1, AS_OF, descripcion="Empresa: Tesla\nContacto: Ana Pérez")
    assert expected_roles(r, "free") == {"person:1"}


def test_sin_contacto_y_sin_corporativo_incluido_el_conjunto_esperado_es_vacio():
    """Plan Free sin «Contacto:»: nada que preparar, así que nunca se da por preparada."""
    r = _reunion(1, AS_OF, tema="Sync", descripcion="")
    assert expected_roles(r, "free") == frozenset()


# ── elegibilidad y recolección ───────────────────────────────────────────────


def test_solo_las_reuniones_elegibles_entran():
    futuro = AS_OF + timedelta(days=1)
    entradas = [
        _entrada(1, futuro),  # elegible
        _entrada(2, futuro, todo_el_dia=True),  # día completo
        _entrada(3, futuro, respuesta_usuario="declined"),  # rechazada por el usuario
        _entrada(4, futuro, correos=["yo@mi-empresa.test", "colega@mi-empresa.test"],
                 participantes="yo@mi-empresa.test, colega@mi-empresa.test"),  # solo internos
        CalendarEntry("google", "primary", OWNER, {**_reunion(5, futuro), "inicio": "2026-10-04"}),  # sin hora
    ]
    snap = collect_meetings(entradas, plan="pro")
    assert [m.keys for m in snap.meetings] == [(meeting_key("google", "ev1"),)]


def test_los_filtros_de_automatizacion_no_excluyen_una_reunion_preparable_a_mano():
    """El ajuste «omitir internas» de la integración no cambia qué reunión es elegible aquí."""
    snap = collect_meetings([_entrada(1, AS_OF + timedelta(days=1))], plan="pro")
    assert len(snap.meetings) == 1


def test_los_correos_reales_deciden_lo_externo_aunque_participantes_lleve_nombres():
    """Graph entrega nombres en `participantes`; el dominio se decide con los correos."""
    e = _entrada(1, AS_OF + timedelta(days=1), participantes="Yo (organizador), Ana Pérez")
    assert len(collect_meetings([e], plan="pro").meetings) == 1


def test_misma_ocurrencia_en_dos_calendarios_se_unifica_con_ical_uid():
    """CA10 — duplicado verificable (mismo iCalUID y mismo instante): una sola reunión."""
    inicio = AS_OF + timedelta(days=2)
    g = _entrada(1, inicio, provider="google", ical_uid="uid-1")
    m = _entrada(9, inicio, provider="microsoft", ical_uid="uid-1")
    snap = collect_meetings([g, m], plan="pro")
    assert len(snap.meetings) == 1
    assert set(snap.meetings[0].keys) == {meeting_key("google", "ev1"), meeting_key("microsoft", "ev9")}


def test_no_se_unifica_por_titulo_ni_cercania_horaria():
    inicio = AS_OF + timedelta(days=2)
    g = _entrada(1, inicio, provider="google")
    m = _entrada(2, inicio + timedelta(minutes=5), provider="microsoft")
    assert len(collect_meetings([g, m], plan="pro").meetings) == 2


def test_dos_ocurrencias_de_una_recurrencia_son_dos_reuniones():
    """CA10 — mismo iCalUID, distinto instante: cada ocurrencia cuenta una vez."""
    a = _entrada(1, AS_OF + timedelta(days=1), ical_uid="serie")
    b = _entrada(2, AS_OF + timedelta(days=2), ical_uid="serie")
    assert len(collect_meetings([a, b], plan="pro").meetings) == 2


def test_ids_iguales_en_proveedores_distintos_no_se_mezclan():
    a = _entrada(1, AS_OF + timedelta(days=1), provider="google")
    b = _entrada(1, AS_OF + timedelta(days=3), provider="microsoft")
    snap = collect_meetings([a, b], plan="pro")
    assert len(snap.meetings) == 2


# ── próximas reuniones (CA1, CA7, CA10) ──────────────────────────────────────


def _futuras(n):
    return [_meeting(i, AS_OF + timedelta(days=1, hours=i)) for i in range(n)]


def test_ca1_cinco_futuras_tres_preparadas():
    ms = _futuras(5)
    disponible = {m.keys[0]: frozenset({"corporate", "person:1"}) for m in ms[:3]}
    r = summarize_upcoming(ms, disponible, as_of=AS_OF)
    assert (r.eligible, r.prepared, r.pending, r.percent) == (5, 3, 2, 60.0)


def test_el_porcentaje_conserva_precision():
    ms = _futuras(3)
    disponible = {ms[0].keys[0]: frozenset({"corporate", "person:1"})}
    assert summarize_upcoming(ms, disponible, as_of=AS_OF).percent == pytest.approx(100 / 3)


def test_ca7_dos_esperados_y_uno_completo_sigue_pendiente():
    ms = _futuras(1)
    r = summarize_upcoming(ms, {ms[0].keys[0]: frozenset({"corporate"})}, as_of=AS_OF)
    assert (r.prepared, r.pending) == (0, 1)


def test_dossier_de_mas_no_perjudica_y_el_exacto_prepara():
    ms = [_meeting(0, AS_OF + timedelta(days=1), expected=("person:1",))]
    extra = frozenset({"corporate", "person:1", "person:2"})
    assert summarize_upcoming(ms, {ms[0].keys[0]: extra}, as_of=AS_OF).prepared == 1


def test_conjunto_esperado_vacio_nunca_es_preparada():
    ms = [_meeting(0, AS_OF + timedelta(days=1), expected=())]
    r = summarize_upcoming(ms, {ms[0].keys[0]: frozenset({"corporate"})}, as_of=AS_OF)
    assert (r.eligible, r.prepared, r.pending) == (1, 0, 1)


def test_sin_reuniones_el_porcentaje_es_null_no_cero():
    r = summarize_upcoming([], {}, as_of=AS_OF)
    assert (r.eligible, r.prepared, r.pending, r.percent) == (0, 0, 0, None)


def test_la_disponibilidad_se_toma_de_cualquiera_de_los_alias_de_la_reunion():
    clave_g, clave_m = meeting_key("google", "a"), meeting_key("microsoft", "b")
    m = Meeting(keys=(clave_g, clave_m), starts_at=AS_OF + timedelta(days=1), expected=frozenset({"corporate"}))
    assert summarize_upcoming([m], {clave_m: frozenset({"corporate"})}, as_of=AS_OF).prepared == 1


def test_los_limites_del_periodo_futuro_son_cerrado_abierto():
    en_as_of = _meeting(1, AS_OF)  # [as_of, ...): entra
    justo_fin = _meeting(2, AS_OF + timedelta(days=7))  # as_of+7d: no entra
    antes_fin = _meeting(3, AS_OF + timedelta(days=7) - timedelta(seconds=1))
    pasada = _meeting(4, AS_OF - timedelta(seconds=1))
    r = summarize_upcoming([en_as_of, justo_fin, antes_fin, pasada], {}, as_of=AS_OF)
    assert r.eligible == 2


def test_los_limites_se_miden_en_instantes_utc_aunque_la_zona_cambie_por_dst():
    """CA10 — 2026-10-25 02:30 Europe/Madrid ocurre dos veces; el instante UTC manda."""
    primera = parse_start("2026-10-25T02:30:00+02:00")  # 00:30Z
    segunda = parse_start("2026-10-25T02:30:00+01:00")  # 01:30Z
    assert primera is not None and segunda is not None
    assert segunda - primera == timedelta(hours=1)
    as_of = datetime(2026, 10, 25, 0, 45, tzinfo=UTC)
    ms = [Meeting(keys=("k1",), starts_at=primera, expected=frozenset({"corporate"})),
          Meeting(keys=("k2",), starts_at=segunda, expected=frozenset({"corporate"}))]
    # la primera ya empezó (00:30Z < 00:45Z); la segunda es futura
    assert summarize_upcoming(ms, {}, as_of=as_of).eligible == 1


# ── créditos para preparar (CA2, CA3, CA4, CA7) ──────────────────────────────

COSTO_PRO = {"corporate": 3, "person:1": 1, "person:2": 1}.__getitem__


def test_el_costo_por_rol_sale_del_plan():
    pro, free, ent = preparation_role_cost("pro"), preparation_role_cost("free"), preparation_role_cost("enterprise")
    assert (pro("corporate"), pro("person:1"), pro("person:7")) == (3, 1, 1)  # estándar = 3, identidad = 1
    assert free("corporate") == 1  # profundidad básica por defecto en Free
    assert ent("corporate") == 3


def test_ca2_dos_pendientes_suman_lo_que_falta_de_cada_una():
    ms = _futuras(5)
    disponible = {m.keys[0]: frozenset({"corporate", "person:1"}) for m in ms[:3]}
    disponible[ms[4].keys[0]] = frozenset({"corporate"})  # a la quinta solo le falta la persona
    r = summarize_preparation_cost(ms, disponible, as_of=AS_OF, role_cost=COSTO_PRO)
    assert (r.meetings_to_generate, r.estimated_credits) == (2, 3 + 1 + 1)


def test_ca3_un_dossier_completo_no_suma_y_una_reunion_preparada_no_cuenta():
    ms = _futuras(2)
    disponible = {k: frozenset({"corporate", "person:1"}) for m in ms for k in m.keys}
    r = summarize_preparation_cost(ms, disponible, as_of=AS_OF, role_cost=COSTO_PRO)
    assert (r.meetings_to_generate, r.estimated_credits) == (0, 0)


def test_ca3_conjunto_esperado_vacio_no_suma_ni_cuenta_como_a_generar():
    ms = [_meeting(0, AS_OF + timedelta(days=1), expected=())]
    r = summarize_preparation_cost(ms, {}, as_of=AS_OF, role_cost=COSTO_PRO)
    assert (r.meetings_to_generate, r.estimated_credits) == (0, 0)


def test_ca7_varios_contactos_suman_uno_por_contacto_faltante():
    ms = [_meeting(0, AS_OF + timedelta(days=1), expected=("corporate", "person:1", "person:2"))]
    r = summarize_preparation_cost(ms, {ms[0].keys[0]: frozenset({"person:1"})}, as_of=AS_OF, role_cost=COSTO_PRO)
    assert r.estimated_credits == 3 + 1


def test_el_costo_solo_cuenta_reuniones_del_periodo():
    dentro = _meeting(0, AS_OF + timedelta(days=1))
    pasada = _meeting(1, AS_OF - timedelta(hours=1))
    fuera = _meeting(2, AS_OF + timedelta(days=7))
    r = summarize_preparation_cost([dentro, pasada, fuera], {}, as_of=AS_OF, role_cost=COSTO_PRO)
    assert (r.meetings_to_generate, r.estimated_credits) == (1, 4)


def test_lo_disponible_en_cualquier_alias_de_la_reunion_no_se_cobra():
    clave_g, clave_m = meeting_key("google", "a"), meeting_key("microsoft", "b")
    m = Meeting(keys=(clave_g, clave_m), starts_at=AS_OF + timedelta(days=1),
                expected=frozenset({"corporate", "person:1"}))
    r = summarize_preparation_cost([m], {clave_m: frozenset({"corporate"})}, as_of=AS_OF, role_cost=COSTO_PRO)
    assert r.estimated_credits == 1


def test_sin_reuniones_el_costo_es_cero_real():
    r = summarize_preparation_cost([], {}, as_of=AS_OF, role_cost=COSTO_PRO)
    assert (r.meetings_to_generate, r.estimated_credits) == (0, 0)

