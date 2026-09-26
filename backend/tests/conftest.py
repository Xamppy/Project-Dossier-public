"""Configuración compartida de pruebas.

Dos cosas pasan aquí:

1. Cada prueba recibe su marcador según la carpeta en que vive. Nadie tiene que
   acordarse de escribir `@pytest.mark.unit` a mano.
2. Se fijan las variables de entorno mínimas para que importar la aplicación no
   falle, y se garantiza que ninguna prueba salga a la red de verdad.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).parent

# Carpeta -> marcador. Lo que está en la raíz de tests/ es unitario.
CARPETA_A_MARCADOR = {
    "integration": "integration",
    "stress": "stress",
    "security": "security",
}


def pytest_collection_modifyitems(items):
    """Marca cada prueba según dónde vive."""
    for item in items:
        try:
            relativa = Path(item.fspath).relative_to(TESTS_ROOT)
        except ValueError:
            continue
        carpeta = relativa.parts[0] if len(relativa.parts) > 1 else ""
        item.add_marker(CARPETA_A_MARCADOR.get(carpeta, "unit"))


@pytest.fixture(scope="session", autouse=True)
def entorno_de_pruebas():
    """Entorno mínimo y explícito.

    Sin esto, importar `dossier.api.app` puede fallar o, peor, tomar la
    configuración real del desarrollador. Los trabajadores en segundo plano se
    apagan: una prueba no debe arrancar hilos que consultan calendarios.

    Deliberadamente NO se fija `DOSSIER_CHARGE_CREDITS`: por omisión el cobro
    está activo y las pruebas de `test_credit_policy.py` verifican justamente
    eso. Apagarlo aquí las volvería verdes sin probar nada.

    "No fijarla" no basta por sí solo: `dossier.api.app` llama `load_env()` a
    nivel de módulo (línea de import), y algunas pruebas (p. ej.
    `tests/integration/test_dossier_stream_route.py`,
    `tests/security/test_dossier_stream_seguridad.py`) importan ese módulo.
    pytest importa todos los módulos de prueba en la fase de recolección,
    antes de que este fixture corra siquiera una vez — así que si el `.env`
    real del desarrollador trae `DOSSIER_CHARGE_CREDITS=false` (como en
    `backend/.env`, pensado para demos), `load_dotenv()` ya la dejó en
    `os.environ` antes de este punto, y quedaba ahí para el resto de la
    sesión. Por eso `test_credit_policy.py` pasaba solo mientras que fallaba
    dentro de la suite completa: dependía de qué otro archivo se hubiera
    importado antes. Se quita explícitamente para garantizar el "no fijada"
    que el docstring ya prometía, venga de donde venga.
    """
    previo = dict(os.environ)
    os.environ.pop("DOSSIER_CHARGE_CREDITS", None)
    os.environ.update(
        {
            "JWT_SECRET": "clave-solo-para-pruebas-no-usar-en-produccion",
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "15",
            "DATABASE_AUTO_CREATE_TABLES": "0",
            "CALENDAR_AUTOMATION_ENABLED": "0",
            "DOSSIER_GENERATION_WORKER_ENABLED": "0",
            "DOSSIER_RETENTION_WORKER_ENABLED": "0",
            "DOSSIER_REDIS_ENABLED": "0",
        }
    )
    yield
    os.environ.clear()
    os.environ.update(previo)


@pytest.fixture(autouse=True)
def sin_red(request, monkeypatch):
    """Ninguna prueba sale a la red real (pero sí permite loopback).

    Una prueba que depende de internet no es una prueba: es un monitor de
    disponibilidad ajena. Falla los viernes por razones que no son tuyas.

    Loopback (127.0.0.1 / ::1 / localhost) queda permitido: en Windows, crear
    un event loop de asyncio abre un socketpair local internamente
    (``asyncio.proactor_events._make_self_pipe``), y `TestClient` de FastAPI
    (tests/integration/) necesita poder crear ese event loop.

    Para saltarlo del todo en un caso justificado y documentado:

        @pytest.mark.parametrize("sin_red", [False], indirect=True)
    """
    if getattr(request, "param", True) is False:
        return

    import socket

    _connect_real = socket.socket.connect
    _create_connection_real = socket.create_connection

    def _es_loopback(direccion) -> bool:
        host = direccion[0] if isinstance(direccion, tuple) else direccion
        return str(host) in ("127.0.0.1", "::1", "localhost")

    def _mensaje() -> str:
        return (
            "Esta prueba intentó abrir una conexión de red. Simula la respuesta "
            "del proveedor con monkeypatch o con un doble de prueba."
        )

    def connect_bloqueado(self, direccion, *args, **kwargs):
        if _es_loopback(direccion):
            return _connect_real(self, direccion, *args, **kwargs)
        raise RuntimeError(_mensaje())

    def create_connection_bloqueada(direccion, *args, **kwargs):
        if _es_loopback(direccion):
            return _create_connection_real(direccion, *args, **kwargs)
        raise RuntimeError(_mensaje())

    monkeypatch.setattr(socket.socket, "connect", connect_bloqueado)
    monkeypatch.setattr(socket, "create_connection", create_connection_bloqueada)


@pytest.fixture
def respuesta_fija():
    """Construye respuestas de proveedor sin depender de la red.

        def test_algo(respuesta_fija):
            r = respuesta_fija({"items": []}, status=200)
    """

    class RespuestaFija:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status_code = status
            self.text = str(payload)

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    return RespuestaFija


BACKEND_ROOT = TESTS_ROOT.parent


@pytest.fixture
def pg_vacia():
    """Engine sobre un Postgres de pruebas con el esquema ``public`` recién recreado.

    Lee ``TEST_DATABASE_URL`` y salta la prueba si no está definida (la CI no
    levanta Postgres todavía). Borra todo el esquema, así que se niega a correr
    si el nombre de la base no contiene «test»: nunca contra la base de desarrollo.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from dossier.db.settings import _database_url_for_sqlalchemy

    crudo = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if not crudo:
        pytest.skip("TEST_DATABASE_URL no definida: prueba contra Postgres omitida")
    url = make_url(_database_url_for_sqlalchemy(crudo))
    if "test" not in (url.database or ""):
        pytest.fail("TEST_DATABASE_URL debe apuntar a una base cuyo nombre contenga 'test'")

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


@pytest.fixture
def alembic_cfg(pg_vacia, monkeypatch):
    """Config de Alembic apuntando a la base de ``pg_vacia``.

    Sin archivo .ini a propósito: ``env.py`` solo llama ``fileConfig`` si hay
    archivo, y ese ``fileConfig`` silenciaría los loggers del resto de la suite.
    """
    from alembic.config import Config

    monkeypatch.setenv("DATABASE_URL", pg_vacia.url.render_as_string(hide_password=False))
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


@pytest.fixture
def sembrar_dossier():
    """Inserta organización + usuario + dossier sin cobro y devuelve el id del dossier."""
    import uuid

    from sqlalchemy import text

    def _sembrar(conn) -> uuid.UUID:
        sufijo = uuid.uuid4().hex[:8]
        org_id = conn.execute(
            text("INSERT INTO organizations (name, slug) VALUES (:n, :s) RETURNING id"),
            {"n": f"Org {sufijo}", "s": f"org-{sufijo}"},
        ).scalar_one()
        user_id = conn.execute(
            text("INSERT INTO users (email) VALUES (:e) RETURNING id"),
            {"e": f"prueba-{sufijo}@example.test"},
        ).scalar_one()
        return conn.execute(
            text(
                "INSERT INTO dossiers (organization_id, requested_by_user_id, dossier_data) "
                "VALUES (:o, :u, CAST(:d AS JSONB)) RETURNING id"
            ),
            {"o": org_id, "u": user_id, "d": '{"billing": "none"}'},
        ).scalar_one()

    return _sembrar
