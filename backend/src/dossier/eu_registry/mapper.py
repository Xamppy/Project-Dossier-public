"""Normaliza las filas crudas de Francia y Alemania al modelo comun (S1.9).

Mapeo de campos segun la tabla de referencia de
``specs/proposals/S1.9-modelo-comun-registro-corporativo.md``. El esquema real
de Handelsregister (OffeneRegister.de) no esta verificado en vivo (ver
docstring de ``eu_registry/client.py``: el servicio respondio 502 al
verificarlo), por lo que el mapeo aleman es defensivo (``dict.get``) y guarda
la fila completa en ``datos_brutos`` para no perder informacion si los
nombres de columna reales difieren de lo esperado.
"""
from __future__ import annotations

from typing import Any

from dossier.schemas.corporate_registry import (
    Directivo,
    DomicilioRegistrado,
    JurisdiccionRegistro,
    RegistroCorporativo,
)


def _texto(valor: Any) -> str | None:
    """Convierte a texto no vacio o ``None``; evita cadenas vacias como dato util."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def mapear_registro_frances(fila: dict[str, Any]) -> RegistroCorporativo:
    """Fila cruda de la API Recherche d'entreprises -> ``RegistroCorporativo``."""
    siege = fila.get("siege") or {}
    domicilio = None
    if siege:
        domicilio = DomicilioRegistrado(
            calle=_texto(siege.get("adresse")),
            localidad=_texto(siege.get("libelle_commune")),
            region=_texto(siege.get("region")),
            codigo_postal=_texto(siege.get("code_postal")),
            pais=_texto(siege.get("pays")) or "France",
        )

    directivos = [
        Directivo(nombre=nombre, cargo=_texto(d.get("qualite")))
        for d in (fila.get("dirigeants") or [])
        if (nombre := _texto(d.get("nom")))
    ]

    codigo_actividad = _texto(fila.get("activite_principale"))

    return RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.fr,
        fuente="recherche_entreprises",
        identificador_registro=_texto(fila.get("siren")) or _texto(fila.get("siret")) or "",
        razon_social=_texto(fila.get("nom_complet")) or _texto(fila.get("nom_raison_sociale")) or "",
        estado=_texto(fila.get("etat_administratif")),
        forma_juridica=_texto(fila.get("nature_juridique")),
        fecha_constitucion=_texto(fila.get("date_creation")),
        domicilio=domicilio,
        codigos_actividad=[codigo_actividad] if codigo_actividad else [],
        directivos=directivos,
        datos_brutos=fila,
    )


def mapear_registro_aleman(fila: dict[str, Any]) -> RegistroCorporativo:
    """Fila cruda de Handelsregister (OffeneRegister.de) -> ``RegistroCorporativo``.

    Los nombres de columna asumidos (``current_status``, ``company_type``,
    ``incorporation_date``, ``registered_address_in_full``,
    ``opencorporates_url``) siguen el formato habitual de los volcados de
    OpenCorporates que este proveedor republica, pero no fueron verificados
    contra el servicio real (ver docstring del cliente). Si difieren, quedan
    en ``None`` sin romper nada; la fila completa sigue disponible en
    ``datos_brutos``.
    """
    direccion = _texto(fila.get("registered_address_in_full")) or _texto(fila.get("registered_address"))
    domicilio = DomicilioRegistrado(calle=direccion, pais="Deutschland") if direccion else None

    return RegistroCorporativo(
        jurisdiccion=JurisdiccionRegistro.de,
        fuente="handelsregister",
        identificador_registro=_texto(fila.get("company_number")) or "",
        razon_social=_texto(fila.get("name")) or "",
        estado=_texto(fila.get("current_status")),
        forma_juridica=_texto(fila.get("company_type")),
        fecha_constitucion=_texto(fila.get("incorporation_date")),
        domicilio=domicilio,
        url_fuente=_texto(fila.get("opencorporates_url")),
        datos_brutos=fila,
    )
