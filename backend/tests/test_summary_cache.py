"""UX-KPI-01 · caché del resumen: vencimiento, una consulta en vuelo, invalidación y errores."""
from __future__ import annotations

import threading
import uuid

from dossier.services.summary_cache import (
    TTL_ERROR_SEGUNDOS,
    TTL_SEGUNDOS,
    SummaryCache,
)


class _Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _clave():
    return (uuid.uuid4(), uuid.uuid4())


def test_el_valor_se_reutiliza_hasta_vencer():
    reloj, cache, k, llamadas = _Reloj(), None, _clave(), []
    cache = SummaryCache(reloj)

    def calc():
        llamadas.append(1)
        return {"n": len(llamadas)}, False

    assert cache.get_or_compute(k, calc) == {"n": 1}
    reloj.t += TTL_SEGUNDOS - 1
    assert cache.get_or_compute(k, calc) == {"n": 1}
    reloj.t += 2
    assert cache.get_or_compute(k, calc) == {"n": 2}


def test_los_errores_vencen_antes_que_los_exitos():
    reloj, k = _Reloj(), _clave()
    cache = SummaryCache(reloj)
    n = []
    cache.get_or_compute(k, lambda: (n.append(1) or "falla", True))
    reloj.t += TTL_ERROR_SEGUNDOS + 1
    cache.get_or_compute(k, lambda: (n.append(1) or "ok", False))
    assert len(n) == 2 and TTL_ERROR_SEGUNDOS < TTL_SEGUNDOS


def test_claves_de_usuarios_u_organizaciones_distintas_no_comparten_valor():
    cache = SummaryCache()
    u1, u2, o1, o2 = (uuid.uuid4() for _ in range(4))
    assert cache.get_or_compute((u1, o1), lambda: ("a", False)) == "a"
    assert cache.get_or_compute((u2, o1), lambda: ("b", False)) == "b"
    assert cache.get_or_compute((u1, o2), lambda: ("c", False)) == "c"
    assert cache.get_or_compute((u1, o1), lambda: ("x", False)) == "a"


def test_invalidar_descarta_todas_las_organizaciones_del_usuario_y_solo_las_suyas():
    cache = SummaryCache()
    u1, u2, o1, o2 = (uuid.uuid4() for _ in range(4))
    for k in ((u1, o1), (u1, o2), (u2, o1)):
        cache.get_or_compute(k, lambda: ("viejo", False))
    cache.invalidate(u1)
    assert cache.get_or_compute((u1, o1), lambda: ("nuevo", False)) == "nuevo"
    assert cache.get_or_compute((u1, o2), lambda: ("nuevo", False)) == "nuevo"
    assert cache.get_or_compute((u2, o1), lambda: ("x", False)) == "viejo"


def test_un_calculo_en_vuelo_invalidado_no_se_guarda():
    cache, k = SummaryCache(), _clave()

    def calc():
        cache.invalidate(k[0])  # llega un cambio mientras se calcula
        return "leido-antes-del-cambio", False

    assert cache.get_or_compute(k, calc) == "leido-antes-del-cambio"
    assert cache.get_or_compute(k, lambda: ("fresco", False)) == "fresco"


def test_consultas_simultaneas_de_la_misma_clave_calculan_una_sola_vez():
    cache, k, cuenta = SummaryCache(), _clave(), []
    salida = threading.Event()

    def calc():
        cuenta.append(1)
        salida.wait(2)
        return "v", False

    resultados = []
    hilos = [threading.Thread(target=lambda: resultados.append(cache.get_or_compute(k, calc))) for _ in range(12)]
    for h in hilos:
        h.start()
    salida.set()
    for h in hilos:
        h.join(5)
    assert resultados == ["v"] * 12 and len(cuenta) == 1


def test_expire_errors_solo_quita_errores():
    cache, ok, mal = SummaryCache(), _clave(), _clave()
    cache.get_or_compute(ok, lambda: ("ok", False))
    cache.get_or_compute(mal, lambda: ("mal", True))
    cache.expire_errors()
    assert cache.get_or_compute(ok, lambda: ("otro", False)) == "ok"
    assert cache.get_or_compute(mal, lambda: ("reintento", False)) == "reintento"
