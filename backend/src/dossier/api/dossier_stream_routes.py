"""Canal SSE de estados progresivos de un job de generación de dossiers (S4.8).

Ver specs/proposals/S0.11-protocolo-estados-progresivos.md. Reutiliza la misma
autenticación y el mismo aislamiento por organización que
``api/dossier_job_routes.py`` (404, no 403, si el job no es del usuario/org —
así no se revela si el id existe en otra organización).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from dossier.api.auth_routes import get_current_user_and_org, get_db_if_configured
from dossier.db.models import DossierGenerationJob, Organization, User
from dossier.services.dossier_generation_job_service import serialize_job
from dossier.services.dossier_progress_stream import stream_job_events

router = APIRouter(tags=["Dossier jobs"])


def lector_de_job(
    db: Session, job_id: UUID, *, user_id: UUID, org_id: UUID
) -> Callable[[], dict | None]:
    """Lee el job del usuario y cierra la transacción enseguida.

    Sin el ``rollback``, la sesión quedaba en transacción y cada cliente SSE retenía
    una conexión del pool durante todo el stream (hasta 10 minutos).
    """

    def leer() -> dict | None:
        db.expire_all()
        try:
            job = db.get(DossierGenerationJob, job_id)
            if job is None or job.organization_id != org_id or job.requested_by_user_id != user_id:
                return None
            return serialize_job(job)
        finally:
            db.rollback()

    return leer


@router.get("/dossier-generation-jobs/{job_id}/stream")
def api_stream_dossier_generation_job(
    job_id: UUID,
    user_org: Annotated[tuple[User, Organization], Depends(get_current_user_and_org)],
    db: Session = Depends(get_db_if_configured),
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    user, org = user_org
    fetch_job = lector_de_job(db, job_id, user_id=user.id, org_id=org.id)

    if fetch_job() is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    last_id = int(last_event_id) if last_event_id and last_event_id.isdigit() else None

    return StreamingResponse(
        stream_job_events(job_id, fetch_job, last_event_id=last_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
