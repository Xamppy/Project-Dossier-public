"""Tests - el fixture `sin_red` debe seguir bloqueando internet real, pero
permitir loopback: en Windows, crear un event loop de asyncio abre un
socketpair 127.0.0.1 internamente (asyncio.proactor_events), y sin esta
excepcion ninguna prueba con TestClient (S4.8, tests/integration/) puede
correr en este entorno.
"""
from __future__ import annotations

import socket

import pytest


def test_sigue_bloqueando_conexiones_no_loopback():
    with pytest.raises(RuntimeError):
        socket.create_connection(("example.com", 80), timeout=1)


def test_permite_loopback_para_que_asyncio_funcione_en_windows():
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        assert loop.is_closed() is False
    finally:
        loop.close()
