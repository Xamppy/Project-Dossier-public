"""User-Agent para las peticiones a la SEC (EDGAR, data.sec.gov).

La política de acceso de la SEC exige que cada petición se identifique con un
nombre y un correo de contacto («Sample Company Name AdminContact@example.com»).
El valor se toma de ``SEC_USER_AGENT`` en cada llamada, para respetar el ``.env``
aunque se cargue después de importar el módulo. Sin la variable se usa un valor
ficticio válido: en producción conviene definirla con un correo del equipo.
"""
from __future__ import annotations

import os

SEC_USER_AGENT_DEFAULT = "Project Dossier contacto@example.com"


def sec_user_agent() -> str:
    """User-Agent configurado en ``SEC_USER_AGENT`` o el valor por defecto."""
    return (os.getenv("SEC_USER_AGENT") or "").strip() or SEC_USER_AGENT_DEFAULT


def sec_request_headers() -> dict[str, str]:
    """Cabeceras comunes de las peticiones a la SEC."""
    return {"User-Agent": sec_user_agent(), "Accept-Encoding": "gzip, deflate"}
