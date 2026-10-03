"""UX-KPI-01: evidencia mínima de generación para los indicadores de Resumen.

Revision ID: c5a9e3b7d1f2
Revises: b7e2d4f1a9c3
Create Date: 2026-10-03

Dos tablas nuevas, sin tocar ninguna columna existente:

- ``dossier_generation_facts``: un hecho por resultado exitoso (usuario, organización,
  proveedor, evento externo, rol, origen manual/automático, finalización real, inicio de
  la reunión, conjunto esperado, marca de borrado). Sin cuerpos, nombres ni correos.
  ``dossier_id`` no es una FK: borrar el documento no debe borrar el hecho que ya ocurrió.
- ``prep_evidence_meta``: una fila con el instante desde el que se registra, que fija el
  límite de lo verificable para el historial.

El DDL es ``schema_patches.PREP_EVIDENCE_PATCHES`` (idempotente; lo reutiliza el arranque
por parches, igual que S4.5). El relleno desde dossiers vigentes es de una sola vez y vive
aquí, autocontenido: una migración es una foto fija y no debe depender de código que luego
cambie.

Relleno (solo evidencia inequívoca; ver docs/exec-plans/active/UX-KPI-01-indicadores-resumen.md):
- ``trigger_source='manual'`` con metadatos de calendario  → origen ``manual``.
- ``trigger_source='calendar'`` con ``calendar_event_id``     → origen ``automatic``.
- ``trigger_source='calendar'`` sin ``calendar_event_id`` es la ruta síncrona antigua: no se
  puede probar quién la inició como acción manual, así que no se rellena.
- Sin ``generation_completed_at`` no hay hecho (no se inventan marcas de tiempo).
- Un inicio de reunión ilegible queda en NULL; no se sustituye por otra fecha.
- El conjunto esperado se deduce de la carpeta: todos los roles que esa generación intentó
  (incluidos los fallidos). Un corporativo que falló no se guardaba, así que ese caso no
  puede reconstruirse: el esperado puede quedar corto, y con él la puntualidad histórica
  rellenada puede ser optimista. Es el límite declarado de este relleno.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from alembic import op

revision = "c5a9e3b7d1f2"
down_revision = "b7e2d4f1a9c3"
branch_labels = None
depends_on = None

_PROVEEDORES = ("google", "microsoft")
_LOTE = 500

_SELECT_DOSSIERS_CON_CALENDARIO = text(
    """
    SELECT id, organization_id, requested_by_user_id, status, trigger_source,
           calendar_event_id, dossier_folder_id, generation_completed_at,
           dossier_data->'calendar'->>'provider'             AS provider,
           dossier_data->'calendar'->>'external_event_id'    AS external_event_id,
           dossier_data->'calendar'->>'inicio'               AS inicio,
           dossier_data->>'calendar_folder_role'             AS rol,
           dossier_data->'person_filters'->>'contact_index'  AS contact_index
    FROM dossiers
    WHERE jsonb_typeof(dossier_data) = 'object' AND dossier_data ? 'calendar'
    """
)

_INSERT_HECHO = text(
    """
    INSERT INTO dossier_generation_facts
        (result_key, organization_id, user_id, provider, calendar_key, external_event_id,
         role_key, origin, dossier_id, expected_keys, meeting_starts_at, generation_completed_at)
    VALUES
        (:result_key, :organization_id, :user_id, :provider, 'primary', :external_event_id,
         :role_key, :origin, :dossier_id, CAST(:expected_keys AS text[]), :meeting_starts_at,
         :generation_completed_at)
    ON CONFLICT (result_key) DO NOTHING
    """
)


def _inicio_utc(valor: str | None) -> datetime | None:
    if not valor or "T" not in valor:
        return None
    s = valor.strip()
    if s[-1] in "zZ":
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(UTC)


def _rol(rol: str | None, contact_index: str | None) -> str | None:
    if rol == "corporate":
        return "corporate"
    if rol == "person":
        try:
            idx = int(contact_index) if contact_index else 1
        except ValueError:
            idx = 1
        return f"person:{idx if idx > 0 else 1}"
    return None


def _origen(trigger_source: str | None, calendar_event_id) -> str | None:
    if trigger_source == "manual":
        return "manual"
    if trigger_source == "calendar" and calendar_event_id is not None:
        return "automatic"
    return None


def _rellenar_desde_dossiers_vigentes(conn) -> None:
    filas = conn.execute(_SELECT_DOSSIERS_CON_CALENDARIO).mappings().all()
    esperado_por_grupo: dict[str, set[str]] = {}
    for f in filas:
        rol = _rol(f["rol"], f["contact_index"])
        if rol is not None:
            grupo = str(f["dossier_folder_id"] or f["id"])
            esperado_por_grupo.setdefault(grupo, set()).add(rol)

    lote: list[dict] = []
    for f in filas:
        rol = _rol(f["rol"], f["contact_index"])
        origen = _origen(f["trigger_source"], f["calendar_event_id"])
        ext = (f["external_event_id"] or "").strip()
        if (
            f["status"] != "complete"
            or rol is None
            or origen is None
            or not ext
            or f["provider"] not in _PROVEEDORES
            or f["generation_completed_at"] is None
        ):
            continue
        grupo = str(f["dossier_folder_id"] or f["id"])
        lote.append(
            {
                "result_key": f"legacy:{f['id']}",
                "organization_id": f["organization_id"],
                "user_id": f["requested_by_user_id"],
                "provider": f["provider"],
                "external_event_id": ext[:512],
                "role_key": rol,
                "origin": origen,
                "dossier_id": f["id"],
                "expected_keys": "{" + ",".join(sorted(esperado_por_grupo[grupo])) + "}",
                "meeting_starts_at": _inicio_utc(f["inicio"]),
                "generation_completed_at": f["generation_completed_at"],
            }
        )
    for i in range(0, len(lote), _LOTE):
        conn.execute(_INSERT_HECHO, lote[i : i + _LOTE])


def upgrade() -> None:
    from dossier.db.schema_patches import PREP_EVIDENCE_PATCHES

    for sql in PREP_EVIDENCE_PATCHES:
        op.execute(text(sql))
    _rellenar_desde_dossiers_vigentes(op.get_bind())


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS dossier_generation_facts"))
    op.execute(text("DROP TABLE IF EXISTS prep_evidence_meta"))
