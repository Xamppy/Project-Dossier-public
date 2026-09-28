"""Agente de noticias: consulta GDELT y NewsAPI y deduplica (ADR 0004, S3.2).

Usa el cliente HTTP de S3.1 (``news/client.py``). No filtra homonimos (S3.3) ni
registra procedencia en base de datos (S3.4): solo recolecta y deduplica.
"""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dossier.news.client import ProveedorNoticiasError, search_gdelt_articles, search_newsapi_articles
from dossier.schemas.dossier_executive_payload import PressMention, SourceCitation, SourceType

# Tiempo maximo de espera por proveedor. Un poco por encima del timeout HTTP
# del cliente (DEFAULT_TIMEOUT=20s): si la red responde, el cliente ya corto
# antes; esto solo protege contra un proveedor colgado en la propia llamada.
TIEMPO_ESPERA_PROVEEDOR_SEG = 25.0

_ArticulosProveedor = Callable[..., list[dict[str, Any]]]


@dataclass
class FalloProveedor:
    """Un proveedor que no respondio a tiempo o devolvio un error."""

    provider: str
    error: str


@dataclass
class ResultadoRecoleccionPrensa:
    """Salida del agente: menciones deduplicadas + que proveedores fallaron."""

    mentions: list[PressMention]
    failed_providers: list[FalloProveedor] = field(default_factory=list)
    query_context: dict[str, Any] = field(default_factory=dict)


def _normalizar_url(url: str) -> str:
    """Misma URL si difieren solo en esquema, ``www.``, tracking o barra final."""
    partes = urlsplit(url.strip())
    host = partes.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    ruta = partes.path.rstrip("/")
    query = [(k, v) for k, v in parse_qsl(partes.query) if not k.lower().startswith("utm_")]
    return urlunsplit(("http", host, ruta, urlencode(sorted(query)), ""))


def _normalizar_titular(titular: str) -> str:
    return " ".join(titular.strip().lower().split())


def _desde_gdelt(articulo: dict[str, Any], source: SourceCitation) -> PressMention | None:
    url = str(articulo.get("url") or "").strip()
    titulo = str(articulo.get("title") or "").strip()
    if not url or not titulo:
        return None
    dominio = str(articulo.get("domain") or "").strip()
    seendate = articulo.get("seendate")
    # GDELT no trae descripcion/snippet: alternativa minima razonable (S3.2).
    resumen = f"Mencion de prensa en {dominio or 'un medio no identificado'}: {titulo}"
    return PressMention(
        headline=titulo,
        publisher=dominio or "Desconocido",
        published_date=str(seendate) if seendate else None,
        summary=resumen,
        url=url,
        source=source,
    )


def _desde_newsapi(articulo: dict[str, Any], source: SourceCitation) -> PressMention | None:
    url = str(articulo.get("url") or "").strip()
    titulo = str(articulo.get("title") or "").strip()
    if not url or not titulo:
        return None
    fuente = articulo.get("source")
    medio = str(fuente.get("name") or "").strip() if isinstance(fuente, dict) else ""
    descripcion = str(articulo.get("description") or "").strip()
    resumen = descripcion or f"Mencion de prensa en {medio or 'un medio no identificado'}: {titulo}"
    publicado = articulo.get("publishedAt")
    return PressMention(
        headline=titulo,
        publisher=medio or "Desconocido",
        published_date=str(publicado) if publicado else None,
        summary=resumen,
        url=url,
        source=source,
    )


_PROVEEDORES: tuple[tuple[str, _ArticulosProveedor, SourceType, Callable[..., PressMention | None]], ...] = (
    ("gdelt_news", search_gdelt_articles, SourceType.gdelt_news, _desde_gdelt),
    ("news_api", search_newsapi_articles, SourceType.news_api, _desde_newsapi),
)


def collect_press_mentions(
    subject_query: str,
    *,
    limite: int = 10,
    timeout_seg: float = TIEMPO_ESPERA_PROVEEDOR_SEG,
) -> ResultadoRecoleccionPrensa:
    """Recolecta menciones de prensa de GDELT y NewsAPI, deduplicadas.

    Consulta ambos proveedores en paralelo (dos llamadas HTTP independientes;
    en serie duplicarian la latencia sin ganar nada). Si uno falla o supera
    `timeout_seg`, se registra en `failed_providers` y se sigue con el otro;
    no se propaga la excepcion. Si fallan los dos, el resultado queda vacio en
    vez de romper la generacion del dossier: es preferible un dossier sin
    noticias a uno bloqueado por un proveedor caido (criterio del ADR 0004).
    """
    resultado = ResultadoRecoleccionPrensa(
        mentions=[],
        query_context={
            "subject_query": subject_query,
            "providers_queried": [nombre for nombre, _, _, _ in _PROVEEDORES],
        },
    )

    # Se lee `globals()` (y no la tupla `_PROVEEDORES`, fijada al importar el
    # modulo) para que los tests puedan monkeypatchear
    # `agent.search_gdelt_articles` / `agent.search_newsapi_articles`.
    funciones_actuales: dict[str, _ArticulosProveedor] = {
        "gdelt_news": globals()["search_gdelt_articles"],
        "news_api": globals()["search_newsapi_articles"],
    }
    tipos_por_proveedor = {nombre: tipo for nombre, _, tipo, _ in _PROVEEDORES}

    # Sin `with`: `shutdown(wait=False)` deja que un proveedor colgado siga en
    # segundo plano sin bloquear el retorno de esta funcion (ponytail: no hay
    # cancelacion cooperativa del hilo; aceptable para una llamada de lectura
    # sin efectos secundarios — el hilo termina solo cuando el proveedor real
    # responda o el proceso finalice).
    executor = ThreadPoolExecutor(max_workers=len(_PROVEEDORES))
    futuros: dict[Future[list[dict[str, Any]]], str] = {
        executor.submit(funciones_actuales[nombre], subject_query, limite=limite): nombre
        for nombre, _, _, _ in _PROVEEDORES
    }

    crudos: list[tuple[str, dict[str, Any], SourceCitation]] = []
    for futuro, nombre in futuros.items():
        try:
            articulos = futuro.result(timeout=timeout_seg)
        except FutureTimeoutError:
            resultado.failed_providers.append(FalloProveedor(provider=nombre, error="tiempo de espera agotado"))
            continue
        except ProveedorNoticiasError as exc:
            resultado.failed_providers.append(FalloProveedor(provider=nombre, error=str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - proveedor externo: cualquier fallo se reporta, no se propaga
            resultado.failed_providers.append(FalloProveedor(provider=nombre, error=str(exc)))
            continue

        source = SourceCitation(
            source_type=tipos_por_proveedor[nombre],
            source_name=nombre,
            url=None,
            retrieved_at=datetime.now(UTC),
            record_id=None,
        )
        for articulo in articulos:
            crudos.append((nombre, articulo, source))
    executor.shutdown(wait=False)

    parsers = {nombre: parser for nombre, _, _, parser in _PROVEEDORES}
    vistos_url: set[str] = set()
    vistos_titular: set[tuple[str, str]] = set()
    for nombre, articulo, source in crudos:
        mencion = parsers[nombre](articulo, source)
        if mencion is None:
            continue
        clave_url = _normalizar_url(mencion.url)
        clave_titular = (_normalizar_titular(mencion.headline), mencion.publisher.strip().lower())
        if clave_url in vistos_url or clave_titular in vistos_titular:
            continue
        vistos_url.add(clave_url)
        vistos_titular.add(clave_titular)
        resultado.mentions.append(mencion)

    return resultado
