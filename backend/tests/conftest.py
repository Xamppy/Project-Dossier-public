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
    """
    previo = dict(os.environ)
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
    """Ninguna prueba sale a la red real.

    Una prueba que depende de internet no es una prueba: es un monitor de
    disponibilidad ajena. Falla los viernes por razones que no son tuyas.

    Para saltarlo en un caso justificado y documentado:

        @pytest.mark.parametrize("sin_red", [False], indirect=True)
    """
    if getattr(request, "param", True) is False:
        return

    import socket

    def bloqueado(*args, **kwargs):
        raise RuntimeError(
            "Esta prueba intentó abrir una conexión de red. Simula la respuesta "
            "del proveedor con monkeypatch o con un doble de prueba."
        )

    monkeypatch.setattr(socket.socket, "connect", bloqueado)
    monkeypatch.setattr(socket, "create_connection", bloqueado)


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
