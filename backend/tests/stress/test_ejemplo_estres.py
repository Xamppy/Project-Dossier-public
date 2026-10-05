"""Plantilla viva de pruebas de estrés.

Estas pruebas se ejecutan con pytest en cada PR: no hacen falta servidores ni
herramientas aparte. Responden las tres preguntas de la política de pruebas,
sección 4: volumen, concurrencia y degradación.

Copia el patrón que necesites al escribir las pruebas de tu propia tarea. Los
casos de aquí usan `credit_policy` porque es una de las pocas piezas con lógica
pura y estable hoy; cuando existan el agente europeo, el de noticias y el canal
de estados, sus pruebas de estrés siguen exactamente esta forma.

Ver docs/dev/testing-policy.md §4.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from dossier.billing.credit_policy import person_research_credit_cost

# --------------------------------------------------------------------------
# Volumen: ¿qué pasa cuando la entrada es grande?
# --------------------------------------------------------------------------

def test_volumen_calculo_de_costo_no_se_degrada():
    """Diez mil cálculos deben resolverse en tiempo lineal y acotado.

    Si esto empieza a tardar, alguien metió entrada/salida o una consulta a la
    base de datos dentro de una función que debía ser pura.
    """
    inicio = time.perf_counter()
    for _ in range(10_000):
        person_research_credit_cost()
    transcurrido = time.perf_counter() - inicio

    assert transcurrido < 1.0, (
        f"10 000 cálculos tardaron {transcurrido:.2f} s. Se esperaba menos de 1 s. "
        "Probablemente se introdujo entrada/salida en una función pura."
    )


@pytest.mark.parametrize("cantidad", [1, 100, 1_000])
def test_volumen_escala_linealmente(cantidad):
    """El costo por elemento no debe crecer con el tamaño del lote."""
    resultados = [person_research_credit_cost() for _ in range(cantidad)]
    assert len(resultados) == cantidad
    assert len(set(resultados)) == 1, "El mismo insumo debe dar siempre el mismo costo"


# --------------------------------------------------------------------------
# Concurrencia: ¿qué pasa con muchas llamadas a la vez?
# --------------------------------------------------------------------------

def test_concurrencia_resultado_estable_bajo_carga():
    """Veinte hilos en paralelo deben producir un resultado idéntico.

    Esta es la forma que tendrán las pruebas de S7.3 (créditos descontados una
    sola vez) y S6.7 (aislamiento entre organizaciones bajo carga).
    """
    with ThreadPoolExecutor(max_workers=20) as pool:
        resultados = list(pool.map(lambda _: person_research_credit_cost(),
                                   range(200)))

    assert len(resultados) == 200
    assert len(set(resultados)) == 1, (
        "El resultado varió entre hilos. Hay estado compartido mutable donde no debería."
    )


def test_concurrencia_sin_excepciones_en_paralelo():
    """Ningún hilo debe morir con excepción."""
    errores: list[BaseException] = []

    def trabajo(_):
        try:
            person_research_credit_cost()
        except BaseException as exc:  # noqa: BLE001 — queremos capturar todo
            errores.append(exc)

    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(trabajo, range(100)))

    assert not errores, f"{len(errores)} hilo(s) fallaron: {errores[:3]}"


# --------------------------------------------------------------------------
# Degradación: ¿qué pasa cuando el proveedor externo tarda o falla?
# --------------------------------------------------------------------------
#
# Es la pregunta central de este sistema: cinco agentes externos y cualquiera
# puede caerse. El patrón siempre es el mismo:
#
#   1. Sustituye el cliente del proveedor por uno que falla o tarda
#   2. Ejecuta el flujo
#   3. Verifica que el resultado se entrega igual, parcial y marcado
#   4. Verifica que no se cobró por lo que no se entregó
#
# Se activa cuando exista el agente europeo (S2.4) y el canal de estados (S4.9).


@pytest.mark.skip(reason="Se habilita con S2.4 — tolerancia a fallos del agente europeo")
def test_degradacion_fallo_de_un_agente_no_aborta_el_dossier():
    """Si el agente europeo falla, el dossier se entrega igual.

    Criterio de aceptación de S2.4:
      - el dossier llega al usuario
      - `agents_failed` contiene el identificador del agente
      - los módulos que sí respondieron están completos
    """
    raise NotImplementedError


def test_degradacion_proveedor_lento_respeta_el_tiempo_limite(monkeypatch):
    """Un proveedor que tarda no debe colgar la generación completa.

    Implementado con el agente europeo (S2.1): la consulta a cada país corre
    en su propio hilo, así que un proveedor lento no bloquea a los demás ni
    retrasa el resultado combinado más allá de su propia demora. El límite
    duro por request (20 s) ya lo aplica ``eu_registry/client.py``; aquí se
    verifica que el agente no le suma una espera en serie encima.
    """
    import time

    from dossier.eu_registry import agent

    def lenta(q, *, limite=5):
        time.sleep(0.3)
        return [{"siren": "1", "nom_complet": "Lenta SA"}]

    monkeypatch.setattr(agent, "search_france_companies", lenta)
    monkeypatch.setattr(agent, "search_germany_companies", lambda q, *, limite=5: [])

    inicio = time.perf_counter()
    resultado = agent.run_eu_registry_agent("Acme")
    transcurrido = time.perf_counter() - inicio

    assert len(resultado.citas) == 1
    assert transcurrido < 1.0, f"Tardo {transcurrido:.2f}s por un proveedor lento simulado en 0.3s"


@pytest.mark.skip(reason="Se habilita con S5.8 — limitación de tasa")
def test_degradacion_rafaga_de_peticiones_activa_la_limitacion():
    """Superado el umbral, la API responde con el código correspondiente."""
    raise NotImplementedError
