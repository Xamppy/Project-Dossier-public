"""Modelo comun de registro corporativo (UK / US / EU) - ver ADR 0003 y S1.9.

Normaliza lo que hoy entregan Companies House (UK) y SEC EDGAR (US), y lo que
entregaran la API Recherche d'entreprises (Francia) y Handelsregister (Alemania)
cuando se implementen en S1.8/S2.1. No incluye adaptadores de fuente real: eso
es S2.1 y S2.3.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JurisdiccionRegistro(str, Enum):
    """Alcance firme de S1.9-S2.7 (ADR 0003)."""

    uk = "uk"
    us = "us"
    fr = "fr"
    de = "de"


class DomicilioRegistrado(BaseModel):
    calle: str | None = None
    localidad: str | None = None
    region: str | None = None
    codigo_postal: str | None = None
    pais: str | None = None


class Directivo(BaseModel):
    """Un director/dirigeant, cuando la fuente lo entrega (Francia, Alemania)."""

    nombre: str
    cargo: str | None = None
    fecha_nombramiento: str | None = None


class Presentacion(BaseModel):
    """Un item de filing history (CH) o de submissions (SEC), o su equivalente europeo."""

    fecha: str | None = None
    tipo: str | None = None
    descripcion: str | None = None
    url: str | None = None


class RegistroCorporativo(BaseModel):
    """Esquema unificado interoperable entre Companies House, SEC EDGAR y las fuentes europeas."""

    jurisdiccion: JurisdiccionRegistro
    fuente: str = Field(
        description="companies_house | sec_edgar | recherche_entreprises | handelsregister"
    )
    identificador_registro: str = Field(
        description="company_number / CIK / SIREN-SIRET / numero HRB-HRA"
    )
    razon_social: str

    estado: str | None = None
    forma_juridica: str | None = None
    fecha_constitucion: str | None = None

    domicilio: DomicilioRegistrado | None = None
    codigos_actividad: list[str] = Field(default_factory=list)
    directivos: list[Directivo] = Field(default_factory=list)
    presentaciones: list[Presentacion] = Field(default_factory=list)

    url_fuente: str | None = None
    consultado_en: datetime | None = None
    datos_brutos: dict[str, Any] | None = None
