"""UX-KPI-01 · lógica pura de los indicadores de Resumen (CA1–CA4, CA6–CA8, CA10).

Sin base de datos ni red: la elegibilidad, el conjunto esperado, la preparación y la
puntualidad se calculan sobre datos ya leídos. Cada prueba nombra el criterio que cubre.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dossier.services.meeting_prep_kpi import (
    CalendarEntry,
    Fact,
    Meeting,
    collect_meetings,
    expected_roles,
    meeting_key,
    parse_start,
    summarize_history,
    summarize_upcoming,
)

AS_OF = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)
DESDE_30 = AS_OF - timedelta(days=30)
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


def _hecho(i, rol, completado, *, origen="manual", inicio=None, run="r1", provider="google",
           esperado=("corporate", "person:1"), borrado=None) -> Fact:
    return Fact(
        result_key=f"{run}:{i}:{rol}",
        meeting_key=meeting_key(provider, f"ev{i}"),
        role_key=rol,
        origin=origen,
        completed_at=completado,
        meeting_starts_at=inicio,
        expected_keys=frozenset(esperado) if esperado is not None else None,
        deleted_at=borrado,
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
    assert set(snap.seen) == {meeting_key("google", f"ev{i}") for i in (1, 2, 3, 4)}


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


# ── historial: preparadas a tiempo por el usuario (CA2, CA3, CA4, CA8) ────────


def test_ca2_ocho_pasadas_seis_a_tiempo_y_once_dossiers():
    def inicio(i):
        return AS_OF - timedelta(days=2 + i)

    ms = [_meeting(i, inicio(i)) for i in range(8)]
    hechos = []
    for i in range(5):  # cinco reuniones con empresa y contacto: 10 dossiers
        hechos.append(_hecho(i, "corporate", inicio(i) - timedelta(hours=3), inicio=inicio(i)))
        hechos.append(_hecho(i, "person:1", inicio(i) - timedelta(hours=2), inicio=inicio(i)))
    # una sexta cuyo conjunto esperado era solo la empresa: 1 dossier más = 11
    hechos.append(_hecho(5, "corporate", inicio(5) - timedelta(hours=3), inicio=inicio(5), esperado=("corporate",)))
    # las reuniones 6 y 7 no tienen resultados manuales
    r = summarize_history(ms, {}, hechos, measured_from=DESDE_30, as_of=AS_OF)
    assert (r.eligible, r.on_time_meetings, r.percent, r.on_time_dossiers) == (8, 6, 75.0, 11)


def test_ca3_automatico_fallido_o_posterior_al_inicio_no_acredita():
    inicio = AS_OF - timedelta(days=1)
    ms = [_meeting(i, inicio, expected=("corporate",)) for i in range(4)]
    hechos = [
        _hecho(0, "corporate", inicio - timedelta(hours=1), origen="automatic", inicio=inicio, esperado=("corporate",)),
        _hecho(1, "corporate", inicio, inicio=inicio, esperado=("corporate",)),  # termina justo al inicio
        _hecho(2, "corporate", inicio + timedelta(minutes=5), inicio=inicio, esperado=("corporate",)),
        # ev3 sin hechos: falló, está en proceso o lo generó otra persona
    ]
    r = summarize_history(ms, {}, hechos, measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_meetings == 0 and r.eligible == 4 and r.percent == 0.0


def test_un_resultado_automatico_no_cuenta_como_dossier_manual_a_tiempo():
    inicio = AS_OF - timedelta(days=1)
    ms = [_meeting(0, inicio, expected=("corporate",))]
    h = _hecho(0, "corporate", inicio - timedelta(hours=1), origen="automatic", inicio=inicio, esperado=("corporate",))
    r = summarize_history(ms, {}, [h], measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_dossiers == 0


def test_ca4_dos_dossiers_de_una_reunion_son_dos_dossiers_y_una_reunion():
    inicio = AS_OF - timedelta(days=1)
    ms = [_meeting(0, inicio)]
    hechos = [
        _hecho(0, "corporate", inicio - timedelta(hours=3), inicio=inicio),
        _hecho(0, "person:1", inicio - timedelta(hours=2), inicio=inicio),
    ]
    r = summarize_history(ms, {}, hechos, measured_from=DESDE_30, as_of=AS_OF)
    assert (r.on_time_meetings, r.on_time_dossiers) == (1, 2)


def test_ca4_una_regeneracion_con_resultado_nuevo_cuenta_una_vez_mas():
    inicio = AS_OF - timedelta(days=1)
    ms = [_meeting(0, inicio, expected=("corporate",))]
    hechos = [
        _hecho(0, "corporate", inicio - timedelta(hours=5), inicio=inicio, run="r1", esperado=("corporate",)),
        _hecho(0, "corporate", inicio - timedelta(hours=2), inicio=inicio, run="r2", esperado=("corporate",)),
    ]
    r = summarize_history(ms, {}, hechos, measured_from=DESDE_30, as_of=AS_OF)
    assert (r.on_time_meetings, r.on_time_dossiers) == (1, 2)


def test_el_mismo_resultado_repetido_no_se_duplica():
    inicio = AS_OF - timedelta(days=1)
    ms = [_meeting(0, inicio, expected=("corporate",))]
    h = _hecho(0, "corporate", inicio - timedelta(hours=2), inicio=inicio, esperado=("corporate",))
    r = summarize_history(ms, {}, [h, h], measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_dossiers == 1


def test_resultado_parcial_y_reintento_posterior_al_inicio_no_prepara_a_tiempo():
    """Persona 1 salió antes del inicio; la corporativa se reintentó cuando la reunión ya había empezado."""
    inicio = AS_OF - timedelta(days=1)
    ms = [_meeting(0, inicio)]
    hechos = [
        _hecho(0, "person:1", inicio - timedelta(hours=2), inicio=inicio, run="r1"),
        _hecho(0, "corporate", inicio + timedelta(hours=1), inicio=inicio, run="r2"),
    ]
    r = summarize_history(ms, {}, hechos, measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_meetings == 0
    assert r.on_time_dossiers == 1  # solo el de persona terminó antes del inicio


def test_reintento_que_completa_antes_del_inicio_si_prepara():
    inicio = AS_OF - timedelta(days=1)
    ms = [_meeting(0, inicio)]
    hechos = [
        _hecho(0, "person:1", inicio - timedelta(hours=4), inicio=inicio, run="r1"),
        _hecho(0, "corporate", inicio - timedelta(hours=1), inicio=inicio, run="r2"),
    ]
    assert summarize_history(ms, {}, hechos, measured_from=DESDE_30, as_of=AS_OF).on_time_meetings == 1


def test_ca8_borrado_antes_del_inicio_no_acredita_y_despues_no_reescribe():
    inicio = AS_OF - timedelta(days=20)
    ms = [_meeting(0, inicio, expected=("corporate",)), _meeting(1, inicio, expected=("corporate",))]
    hechos = [
        # ev0: el documento se borró antes de la reunión → no estaba disponible
        _hecho(0, "corporate", inicio - timedelta(hours=3), inicio=inicio, esperado=("corporate",),
               borrado=inicio - timedelta(hours=1)),
        # ev1: se borró (p. ej. retención de 7 días) después de la reunión → el hecho se mantiene
        _hecho(1, "corporate", inicio - timedelta(hours=3), inicio=inicio, esperado=("corporate",),
               borrado=inicio + timedelta(days=7)),
    ]
    r = summarize_history(ms, {}, hechos, measured_from=DESDE_30, as_of=AS_OF)
    assert (r.on_time_meetings, r.on_time_dossiers) == (1, 1)


def test_la_puntualidad_usa_el_inicio_actual_si_la_reunion_se_reprogramo():
    """CA10 — la reunión se movió después de generar: manda el inicio vigente del calendario."""
    inicio_nuevo = AS_OF - timedelta(days=1)
    inicio_viejo = inicio_nuevo - timedelta(days=3)
    ms = [_meeting(0, inicio_nuevo, expected=("corporate",))]
    generado = inicio_viejo - timedelta(hours=1)
    h = _hecho(0, "corporate", generado, inicio=inicio_viejo, esperado=("corporate",))
    assert summarize_history(ms, {}, [h], measured_from=DESDE_30, as_of=AS_OF).on_time_meetings == 1
    # y si se adelantó a antes de la generación, ya no llegó a tiempo
    ms2 = [_meeting(0, generado - timedelta(hours=2), expected=("corporate",))]
    assert summarize_history(ms2, {}, [h], measured_from=DESDE_30, as_of=AS_OF).on_time_meetings == 0


def test_se_usa_el_conjunto_esperado_registrado_y_no_el_del_plan_actual():
    """«Sin reinterpretar hechos pasados»: hoy el evento exige más, pero entonces bastaba corporate."""
    inicio = AS_OF - timedelta(days=2)
    ms = [_meeting(0, inicio, expected=("corporate", "person:1", "person:2"))]
    h = _hecho(0, "corporate", inicio - timedelta(hours=2), inicio=inicio, esperado=("corporate",))
    assert summarize_history(ms, {}, [h], measured_from=DESDE_30, as_of=AS_OF).on_time_meetings == 1


def test_sin_conjunto_registrado_se_cae_al_que_el_parser_deduce_del_evento():
    inicio = AS_OF - timedelta(days=2)
    ms = [_meeting(0, inicio, expected=("corporate", "person:1"))]
    h = _hecho(0, "corporate", inicio - timedelta(hours=2), inicio=inicio, esperado=None)
    assert summarize_history(ms, {}, [h], measured_from=DESDE_30, as_of=AS_OF).on_time_meetings == 0


def test_el_historial_solo_mide_reuniones_dentro_del_intervalo_medido():
    medido_desde = AS_OF - timedelta(days=10)
    dentro = _meeting(0, AS_OF - timedelta(days=5), expected=("corporate",))
    fuera = _meeting(1, AS_OF - timedelta(days=20), expected=("corporate",))  # antes de lo verificable
    futura = _meeting(2, AS_OF + timedelta(days=1), expected=("corporate",))
    r = summarize_history([dentro, fuera, futura], {}, [], measured_from=medido_desde, as_of=AS_OF)
    assert r.eligible == 1


def test_sin_reuniones_pasadas_el_porcentaje_es_null():
    r = summarize_history([], {}, [], measured_from=DESDE_30, as_of=AS_OF)
    assert (r.eligible, r.percent, r.on_time_dossiers) == (0, None, 0)


# ── conteo de dossiers manuales: periodo por finalización, reunión asociada ───


def test_el_conteo_de_dossiers_se_acota_por_finalizacion_no_por_inicio():
    """Un dossier preparado antes del periodo acredita la reunión pero no es una generación del periodo."""
    inicio = AS_OF - timedelta(days=2)
    ms = [_meeting(0, inicio, expected=("corporate",))]
    h = _hecho(0, "corporate", DESDE_30 - timedelta(days=1), inicio=inicio, esperado=("corporate",))
    r = summarize_history(ms, {}, [h], measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_meetings == 1
    assert r.on_time_dossiers == 0


def test_un_dossier_para_una_reunion_futura_lejana_cuenta_con_su_inicio_registrado():
    inicio = AS_OF + timedelta(days=20)
    h = _hecho(0, "corporate", AS_OF - timedelta(days=1), inicio=inicio, esperado=("corporate",))
    r = summarize_history([], {}, [h], measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_dossiers == 1


def test_un_dossier_sin_inicio_de_reunion_conocido_no_permite_afirmar_a_tiempo():
    h = _hecho(0, "corporate", AS_OF - timedelta(days=1), inicio=None, esperado=("corporate",))
    r = summarize_history([], {}, [h], measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_dossiers == 0


def test_un_dossier_de_una_reunion_que_ya_no_esta_en_el_calendario_no_cuenta():
    """Su inicio registrado cae dentro de lo leído y la reunión no aparece: cancelada o movida."""
    inicio = AS_OF - timedelta(days=3)
    h = _hecho(0, "corporate", inicio - timedelta(hours=2), inicio=inicio, esperado=("corporate",))
    r = summarize_history([], {}, [h], measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_dossiers == 0


def test_un_dossier_de_una_reunion_vista_pero_no_elegible_no_cuenta():
    inicio = AS_OF - timedelta(days=3)
    h = _hecho(0, "corporate", inicio - timedelta(hours=2), inicio=inicio, esperado=("corporate",))
    visto = {meeting_key("google", "ev0"): inicio}
    r = summarize_history([], visto, [h], measured_from=DESDE_30, as_of=AS_OF)
    assert r.on_time_dossiers == 0
