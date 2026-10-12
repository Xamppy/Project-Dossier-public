"""Agente de registros corporativos europeos (Francia, Alemania) - S2.1.

Consulta en paralelo las fuentes soportadas por ``eu_registry.client``,
normaliza cada resultado al modelo comun ``RegistroCorporativo`` (S1.9)
envuelto en su cita de origen obligatoria (``CorporateRecordCitation``), y
devuelve resultados mas errores por jurisdiccion: el fallo de un pais no
tumba a los demas.

No integra esto al orquestador (grafo LangGraph, S2.2) ni implementa la
tolerancia a fallos formal del dossier completo (``agents_failed``, S2.4):
aqui basta con no propagar la excepcion y reportarla.
"""
from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dossier.eu_registry.client import (
    RegistroEuropeoError,
    search_france_companies,
    search_germany_companies,
)
from dossier.eu_registry.mapper import mapear_registro_aleman, mapear_registro_frances
from dossier.schemas.corporate_registry import JurisdiccionRegistro, RegistroCorporativo
from dossier.schemas.dossier_executive_payload import (
    CorporateRecordCitation,
    SourceCitation,
    SourceType,
)

LIMITE_POR_DEFECTO = 5


@dataclass
class ResultadoAgenteEuropeo:
    """Resultado del agente: citas normalizadas y errores por jurisdiccion.

    ``errores`` usa el valor de ``JurisdiccionRegistro`` ("fr", "de") como
    clave; una jurisdiccion sin error no aparece en el dict.
    """

    citas: list[CorporateRecordCitation] = field(default_factory=list)
    errores: dict[str, str] = field(default_factory=dict)


def _buscar_frances(nombre: str, limite: int) -> list[dict[str, Any]]:
    return search_france_companies(nombre, limite=limite)


def _buscar_aleman(nombre: str, limite: int) -> list[dict[str, Any]]:
    return search_germany_companies(nombre, limite=limite)


def _mapear_frances(fila: dict[str, Any]) -> RegistroCorporativo:
    return mapear_registro_frances(fila)


def _mapear_aleman(fila: dict[str, Any]) -> RegistroCorporativo:
    return mapear_registro_aleman(fila)


@dataclass(frozen=True)
class _FuenteEuropea:
    buscar: Any
    mapear: Any
    nombre_fuente: str


# Se referencia el nombre del wrapper (``_buscar_frances``), no la funcion del
# cliente directamente: asi un monkeypatch sobre ``search_france_companies``
# en este modulo sigue teniendo efecto (el wrapper la busca por nombre en
# cada llamada, no queda una referencia congelada desde el momento del import).
_FUENTES: dict[JurisdiccionRegistro, _FuenteEuropea] = {
    JurisdiccionRegistro.fr: _FuenteEuropea(
        buscar=_buscar_frances,
        mapear=_mapear_frances,
        nombre_fuente="Recherche d'entreprises (data.gouv.fr)",
    ),
    JurisdiccionRegistro.de: _FuenteEuropea(
        buscar=_buscar_aleman,
        mapear=_mapear_aleman,
        nombre_fuente="Handelsregister (OffeneRegister.de)",
    ),
}

JURISDICCIONES_SOPORTADAS: tuple[JurisdiccionRegistro, ...] = tuple(_FUENTES)


def _normalizar_jurisdicciones(
    jurisdicciones: Iterable[JurisdiccionRegistro | str] | None,
) -> list[JurisdiccionRegistro]:
    if jurisdicciones is None:
        return list(JURISDICCIONES_SOPORTADAS)

    resultado: list[JurisdiccionRegistro] = []
    for j in jurisdicciones:
        jur = j if isinstance(j, JurisdiccionRegistro) else JurisdiccionRegistro(str(j))
        if jur not in _FUENTES:
            raise ValueError(f"Jurisdiccion no soportada por el agente europeo: {jur.value}")
        if jur not in resultado:
            resultado.append(jur)
    return resultado


def _consultar_pais(
    fuente: _FuenteEuropea, nombre_empresa: str, limite: int
) -> tuple[list[CorporateRecordCitation], str | None]:
    """Busca y normaliza una jurisdiccion. Nunca lanza: devuelve el error como texto."""
    try:
        filas = fuente.buscar(nombre_empresa, limite)
    except RegistroEuropeoError as e:
        return [], str(e)
    except Exception as e:  # noqa: BLE001 - un pais no debe tumbar a los demas (requisito de la tarea)
        return [], f"Error inesperado al consultar {fuente.nombre_fuente}: {e}"

    citas: list[CorporateRecordCitation] = []
    for fila in filas:
        try:
            registro = fuente.mapear(fila)
        except Exception as e:  # noqa: BLE001 - idem: un dato mal formado no debe tumbar al resto
            return citas, f"Error al normalizar respuesta de {fuente.nombre_fuente}: {e}"

        retrieved_at = datetime.now(UTC)
        registro.consultado_en = retrieved_at
        citas.append(
            CorporateRecordCitation(
                record=registro,
                source=SourceCitation(
                    source_type=SourceType.eu_registry,
                    source_name=fuente.nombre_fuente,
                    url=registro.url_fuente,
                    retrieved_at=retrieved_at,
                    record_id=registro.identificador_registro or None,
                ),
            )
        )
    return citas, None


def _deduplicar(citas: list[CorporateRecordCitation]) -> list[CorporateRecordCitation]:
    """Descarta repetidos por (jurisdiccion, identificador de registro), primero gana."""
    vistos: set[tuple[str, str]] = set()
    unicas: list[CorporateRecordCitation] = []
    for cita in citas:
        clave = (cita.record.jurisdiccion.value, cita.record.identificador_registro)
        if clave in vistos:
            continue
        vistos.add(clave)
        unicas.append(cita)
    return unicas


def run_eu_registry_agent(
    company_name: str,
    *,
    jurisdicciones: Iterable[JurisdiccionRegistro | str] | None = None,
    limite: int = LIMITE_POR_DEFECTO,
) -> ResultadoAgenteEuropeo:
    """Consulta los registros europeos soportados (Francia, Alemania por defecto).

    Cada jurisdiccion se consulta en paralelo y de forma independiente: si
    una falla (red, timeout, formato inesperado), queda en ``errores`` y las
    demas se entregan igual. Los duplicados dentro del resultado combinado
    se eliminan.
    """
    nombre = (company_name or "").strip()
    jurisdicciones_a_consultar = _normalizar_jurisdicciones(jurisdicciones)

    resultado = ResultadoAgenteEuropeo()
    if not nombre or not jurisdicciones_a_consultar:
        return resultado

    with ThreadPoolExecutor(max_workers=len(jurisdicciones_a_consultar)) as pool:
        futuros = {
            jur: pool.submit(_consultar_pais, _FUENTES[jur], nombre, limite)
            for jur in jurisdicciones_a_consultar
        }
        for jur in jurisdicciones_a_consultar:
            citas, error = futuros[jur].result()
            resultado.citas.extend(citas)
            if error:
                resultado.errores[jur.value] = error

    resultado.citas = _deduplicar(resultado.citas)
    return resultado
