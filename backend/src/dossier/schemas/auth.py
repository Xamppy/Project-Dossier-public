"""Esquemas Pydantic para registro, login y respuestas públicas de usuario."""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError


class RegisterRequest(BaseModel):
    """Cuerpo POST /auth/register — coincide con los campos del formulario Next.js."""

    email: EmailStr
    password: str = Field(
        min_length=8,
        max_length=128,
        description="Entre 8 caracteres y 72 bytes UTF-8; no se trunca la contraseña.",
    )
    full_name: str = Field(min_length=1, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    workspace_kind: Literal["personal", "work"] = "work"
    invite_token: str | None = Field(default=None, max_length=128)
    locale: str | None = Field(
        default=None,
        max_length=16,
        description="Idioma de interfaz (en, es, pt, it, fr, de, en-gb).",
    )

    @field_validator("password", mode="before")
    @classmethod
    def password_fits_bcrypt(cls, value: Any) -> Any:
        # Antes del límite de caracteres para que todo exceso tenga el mismo error.
        if isinstance(value, str) and len(value.encode("utf-8")) > 72:
            raise PydanticCustomError(
                "password_too_long_bytes",
                "La contraseña supera el máximo de {max_bytes} bytes. Usa una más corta; "
                "las tildes y los emojis pueden ocupar varios bytes.",
                {"max_bytes": 72},
            )
        return value

    @model_validator(mode="before")
    @classmethod
    def infer_workspace_kind_if_omitted(cls, data: Any) -> Any:
        """
        Clientes antiguos u omiten `workspace_kind`: si no hay nombre de empresa,
        asumir cuenta personal (evita 422). Si hay `company_name` o `invite_token`, work.
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)
        raw_invite = out.get("invite_token")
        has_invite = isinstance(raw_invite, str) and bool(raw_invite.strip())

        raw_wk = out.get("workspace_kind")
        if isinstance(raw_wk, str):
            wk = raw_wk.strip().lower()
            out["workspace_kind"] = wk if wk in ("personal", "work") else None
        elif raw_wk is not None:
            out["workspace_kind"] = None

        wk_final = out.get("workspace_kind")
        if wk_final not in ("personal", "work"):
            cn = out.get("company_name")
            cn_str = cn.strip() if isinstance(cn, str) else ""
            out["workspace_kind"] = "work" if cn_str or has_invite else "personal"
        return out

    @field_validator("invite_token", mode="before")
    @classmethod
    def strip_invite_token(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            t = v.strip()
            return t or None
        return None

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("no puede quedar vacío")
        return s

    @field_validator("company_name", mode="before")
    @classmethod
    def empty_company_to_none(cls, v: object) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            t = v.strip()
            return t or None
        return None

    @model_validator(mode="after")
    def company_required_for_work(self) -> RegisterRequest:
        invite = (self.invite_token or "").strip()
        if invite:
            # Registro vía invitación: se une a la org existente, sin company_name.
            self.company_name = None
            return self
        if self.workspace_kind == "work":
            cn = (self.company_name or "").strip()
            if not cn:
                raise ValueError("company_name es obligatorio para cuenta de empresa")
            self.company_name = cn
        else:
            self.company_name = None
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ForgotPasswordRequest(BaseModel):
    """Cuerpo POST /auth/forgot-password — solo correo (misma forma que login)."""

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Respuesta siempre idéntica para no revelar si el email está registrado."""

    ok: Literal[True] = True


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    current_password: str = Field(min_length=1, max_length=128)


class DeleteAccountRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    confirm: Literal["DELETE"] = Field(
        description="Escribe DELETE para confirmar la eliminación irreversible."
    )


class UserPreferencesPatch(BaseModel):
    """Cuerpo PATCH /auth/me/preferences — idioma de interfaz y salida de dossiers."""

    locale: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=100)
    dossier_output_language: str | None = Field(
        default=None,
        max_length=10,
        description="match | es | en | pt | it | fr | de | auto",
    )
    dossier_retention_days: int | None = Field(
        default=None,
        description="7, 14, 30, 90 o null (conservar indefinidamente)",
    )

    @field_validator("locale", "timezone", "dossier_output_language", mode="before")
    @classmethod
    def strip_optional(cls, v: object) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


class UserPublic(BaseModel):
    """Perfil público + tenant activo (organización primaria)."""

    id: UUID
    email: str
    full_name: str
    company_name: str
    organization_id: UUID
    role: str
    is_platform_admin: bool = False
    organization_plan: str = "free"
    credits_balance: int = 0
    credits_monthly_limit: int = 0
    workspace_kind: Literal["personal", "work"] = "work"
    # Contexto opcional (JSON `organizations.settings.dossier_context`) para personalizar dossiers.
    organization_company_summary: str | None = None
    organization_industry_or_area: str | None = None
    locale: str = "es"
    timezone: str = "UTC"
    dossier_output_language: str = "match"
    dossier_retention_days: int | None = 30


class OrganizationPlanPatch(BaseModel):
    """Cuerpo PATCH /auth/organization/plan — solo administradores de la organización."""

    plan: Literal["free", "pro", "enterprise"]


class OrganizationDossierContextPatch(BaseModel):
    """Cuerpo PATCH /auth/organization/dossier-context — solo administradores de la organización."""

    company_summary: str = Field(default="", max_length=500)
    industry_or_area: str = Field(default="", max_length=200)

    @field_validator("company_summary", "industry_or_area", mode="before")
    @classmethod
    def strip_text(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
