"""Coordinador del progreso de un job de generación (S5.10, ADR 0009).

Un ``JobProgress`` por job serializa los cambios de sus scopes: cada uno se aplica
en una transacción propia con el job bloqueado (``SELECT … FOR UPDATE``), sube la
revisión persistida y, solo después del commit, se publica en el bus SSE. Los
nodos del grafo que corren en paralelo no comparten una ``Session``.

El progreso nunca hace fallar una generación: si guardar o publicar falla, o el
cambio no respeta el contrato, se descarta y queda en el log. Un job que ya
terminó no acepta cambios (un callback tardío no lo resucita).
"""
from __future__ import annotations

import copy
import logging
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from dossier.db.models import DossierGenerationJob
from dossier.services import dossier_progress_model as m
from dossier.services.dossier_progress_events import publish_if_changed

logger = logging.getLogger(__name__)

PROGRESS_KEY = "_progress"
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})

Change = Callable[[dict[str, Any] | None], tuple[dict[str, Any], Any] | None]
Publish = Callable[[UUID, str, dict[str, Any]], Any]


class ProgressStore(Protocol):
    def apply(self, job_id: UUID, change: Change) -> tuple[Any, dict[str, Any], dict[str, Any]] | None:
        """Aplica ``change`` al progreso del job bloqueado.

        ``change`` recibe una copia del progreso (``None`` si aún no hay) y devuelve
        ``(progreso_nuevo, resultado)`` o ``None`` si no cambia nada. Devuelve
        ``(resultado, progreso_guardado, job_serializado)``, o ``None`` si el job no
        existe, ya terminó o no hubo cambio.
        """
        ...


class SqlProgressStore:
    """Guarda el progreso en ``dossier_generation_jobs.result_payload["_progress"]``."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        serialize: Callable[[DossierGenerationJob], dict[str, Any]],
    ) -> None:
        self._factory = session_factory
        self._serialize = serialize

    def apply(self, job_id: UUID, change: Change) -> tuple[Any, dict[str, Any], dict[str, Any]] | None:
        with self._factory() as db:
            job = db.get(DossierGenerationJob, job_id, with_for_update=True, populate_existing=True)
            if job is None or job.status in TERMINAL_JOB_STATUSES:
                db.rollback()
                return None
            payload = dict(job.result_payload) if isinstance(job.result_payload, dict) else {}
            cambio = change(copy.deepcopy(payload.get(PROGRESS_KEY)))
            if cambio is None:
                db.rollback()
                return None
            nuevo, resultado = cambio
            payload[PROGRESS_KEY] = nuevo
            job.result_payload = payload
            db.commit()
            return resultado, copy.deepcopy(nuevo), self._serialize(job)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ScopeProgress:
    """Vista de un scope del job: lo que llaman el grafo y la investigación de personas."""

    def __init__(self, job: JobProgress, scope_id: str) -> None:
        self._job = job
        self.scope_id = scope_id

    @property
    def job_id(self) -> str:
        return str(self._job.job_id)

    @property
    def research_source(self) -> str | None:
        scope = self.snapshot()
        return scope.get("research_source") if scope else None

    def agent(self, agent_name: str, status: str, reason_code: str | None = None) -> None:
        self._job._update(self.scope_id, agent_name, status, reason_code, {})

    def stage(self, stage_id: str, status: str, reason_code: str | None = None, **meta: Any) -> None:
        self._job._update(self.scope_id, stage_id, status, reason_code, meta)

    def partial(self, partial: dict[str, Any] | None) -> None:
        if partial is not None:
            self._job._partial(self.scope_id, partial)

    def fields(self, **fields: Any) -> None:
        self._job._fields(self.scope_id, fields)

    def snapshot(self) -> dict[str, Any] | None:
        scope = m.find_scope(self._job.snapshot(), self.scope_id)
        return copy.deepcopy(scope) if scope else None


class _NullScope:
    """Scope sin job (ruta manual, API síncrona): todas las llamadas se ignoran."""

    scope_id = None
    job_id = None
    research_source = None

    def agent(self, *args: Any, **kwargs: Any) -> None:
        return None

    def stage(self, *args: Any, **kwargs: Any) -> None:
        return None

    def partial(self, *args: Any, **kwargs: Any) -> None:
        return None

    def fields(self, **kwargs: Any) -> None:
        return None

    def snapshot(self) -> None:
        return None


NULL_SCOPE: Any = _NullScope()


class JobProgress:
    def __init__(
        self,
        job_id: UUID,
        store: ProgressStore,
        *,
        publish: Publish = publish_if_changed,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.job_id = job_id
        self._store = store
        self._publish = publish
        self._clock = clock
        self._lock = threading.Lock()
        self._last: dict[str, Any] | None = None

    # --- API -----------------------------------------------------------------

    def declare(self, scopes: Iterable[dict[str, Any]]) -> None:
        """Declara scopes con su catálogo; publica el job completo para que llegue antes que las transiciones."""
        nuevos = list(scopes)

        def change(p: dict[str, Any] | None) -> tuple[dict[str, Any], Any] | None:
            p = p or m.new_progress()
            if not [s for s in nuevos if m.add_scope(p, s)]:
                return None
            m.bump_revision(p)
            return p, True

        self._run(change, lambda _r, _p, job: [("job_status", job)])

    def scope(self, scope_id: str) -> ScopeProgress:
        return ScopeProgress(self, scope_id)

    def snapshot(self) -> dict[str, Any] | None:
        """Último progreso confirmado por esta instancia."""
        return copy.deepcopy(self._last)

    # --- internos --------------------------------------------------------------

    def _update(
        self, scope_id: str, entity_id: str, status: str, reason_code: str | None, meta: dict[str, Any]
    ) -> None:
        now = self._clock()

        def change(p: dict[str, Any] | None) -> tuple[dict[str, Any], Any] | None:
            if p is None:
                raise ValueError(f"{entity_id!r}: el job no tiene scopes declarados")
            entidad = m.update_entity(p, scope_id, entity_id, status, reason_code=reason_code, meta=meta, now=now)
            return None if entidad is None else (p, entidad)

        def eventos(entidad: dict[str, Any], guardado: dict[str, Any], _job: dict[str, Any]):
            scope = m.find_scope(guardado, scope_id) or {}
            base = {
                "schema_version": m.SCHEMA_VERSION,
                "job_id": str(self.job_id),
                "scope_id": scope_id,
                "revision": entidad["revision"],
            }
            if scope.get("kind") == "corporate":
                return [
                    (
                        "agent_progress",
                        {
                            **base,
                            "agent_name": entidad["agent_name"],
                            "status": entidad["status"],
                            "timestamp": entidad["timestamp"],
                            "reason_code": entidad["reason_code"],
                        },
                    )
                ]
            extra = {k: entidad[k] for k in m.ENTITY_META if k in entidad}
            return [
                (
                    "stage_progress",
                    {
                        **base,
                        "research_source": scope.get("research_source"),
                        "stage_id": entidad["stage_id"],
                        "status": entidad["status"],
                        "timestamp": entidad["timestamp"],
                        "reason_code": entidad["reason_code"],
                        **extra,
                    },
                )
            ]

        self._run(change, eventos)

    def _partial(self, scope_id: str, partial: dict[str, Any]) -> None:
        def change(p: dict[str, Any] | None) -> tuple[dict[str, Any], Any] | None:
            if p is None:
                raise ValueError("parcial sin scopes declarados")
            guardado = m.put_partial(p, scope_id, partial)
            return None if guardado is None else (p, guardado)

        def eventos(guardado: dict[str, Any], progreso: dict[str, Any], _job: dict[str, Any]):
            scope = m.find_scope(progreso, scope_id) or {}
            datos = {
                "schema_version": m.SCHEMA_VERSION,
                "job_id": str(self.job_id),
                "scope_id": scope_id,
                **guardado,
            }
            if scope.get("kind") == "person":
                datos["research_source"] = scope.get("research_source")
            return [("partial_result", datos)]

        self._run(change, eventos)

    def _fields(self, scope_id: str, fields: dict[str, Any]) -> None:
        def change(p: dict[str, Any] | None) -> tuple[dict[str, Any], Any] | None:
            if p is None:
                raise ValueError("campos sin scopes declarados")
            return (p, True) if m.set_scope_fields(p, scope_id, fields) else None

        # Sin evento propio en el contrato: el cambio viaja en el snapshot del job.
        self._run(change, lambda _r, _p, job: [("job_status", job)])

    def _run(self, change: Change, eventos: Callable[..., list[tuple[str, dict[str, Any]]]]) -> None:
        # El candado ordena además la publicación: dentro del proceso, el bus recibe
        # los eventos en el mismo orden que sus revisiones.
        with self._lock:
            try:
                aplicado = self._store.apply(self.job_id, change)
            except Exception as exc:  # el progreso no tumba la generación
                logger.warning("Progreso del job %s descartado: %s", self.job_id, exc, exc_info=True)
                return
            if aplicado is None:
                return
            resultado, guardado, job = aplicado
            self._last = guardado
            for evento, datos in eventos(resultado, guardado, job):
                try:
                    self._publish(self.job_id, evento, datos)
                except Exception:
                    logger.warning("No se pudo publicar %s del job %s", evento, self.job_id, exc_info=True)


class _NullJobProgress:
    """Sin job: el calendario y Personas corren igual que antes de S5.10."""

    job_id = None

    def declare(self, scopes: Iterable[dict[str, Any]]) -> None:
        return None

    def scope(self, scope_id: str) -> Any:
        return NULL_SCOPE

    def snapshot(self) -> None:
        return None


NULL_JOB_PROGRESS: Any = _NullJobProgress()


# --- result_payload ------------------------------------------------------------


def split_result_payload(payload: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Separa el resultado real del progreso interno guardado junto a él."""
    if not isinstance(payload, dict):
        return None, None
    progreso = payload.get(PROGRESS_KEY)
    resultado = {k: v for k, v in payload.items() if k != PROGRESS_KEY}
    return (resultado or None), (progreso if isinstance(progreso, dict) else None)


def merge_result_payload(
    result: dict[str, Any] | None, current_payload: Any, job_status: str
) -> dict[str, Any] | None:
    """Resultado final más el progreso cerrado: se fusiona, no se reemplaza (ADR 0009)."""
    _, progreso = split_result_payload(current_payload)
    cerrado = m.finalize_progress(progreso, job_status, now=_now())
    if cerrado is None:
        return result
    return {**(result or {}), PROGRESS_KEY: cerrado}
