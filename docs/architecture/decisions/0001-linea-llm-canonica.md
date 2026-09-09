# 0001 · Línea de implementación LLM canónica

- **Fecha:** 2026-09-09
- **Estado:** aceptada
- **Decide:** FO
- **Tarea:** S0.4

## Contexto

En el estado actual del repositorio coexisten tres líneas de código relacionadas con modelos de lenguaje:
1. `backend/src/dossier/llm/client.py`: Cliente canónico de DeepSeek que interactúa vía API compatible con OpenAI (`deepseek-chat`).
2. `backend/src/dossier/gemini/analyze.py`: Shim de compatibilidad que reexporta funciones de `dossier.llm.*`, pero induce a error al mantener en el pipeline (`person_research_pipeline.py:154`) claves como `gemini_analysis_markdown`.
3. `backend/src/dossier/services/openai_dossier.py`: Ruta monolítica legada activada mediante la variable `DOSSIER_LEGACY_OPENAI=1` que llama a OpenAI GPT-3.5 omitiendo el orquestador LangGraph.
4. Nombres confusos en el orquestador: `corporate_dossier_graph.py:113` define `_node_synthesize_gemini` cuando en realidad importa `from dossier.llm.text_generate import generate_text_with_llm` que invoca DeepSeek.

Esta multiplicidad oculta qué proveedor se utiliza realmente, genera deuda técnica y dificulta la implementación de validaciones estrictas de salida.

## Alternativas evaluadas

| Opción | A favor | En contra |
|---|---|---|
| **A. Estandarizar en DeepSeek (vía `dossier.llm.*`)** | Relación coste/rendimiento óptima; soporte de JSON Schema en modo estricto; cliente ya implementado y testeado; no requiere emulaciones. | Dependencia de API DeepSeek externa; se debe limpiar el shim de Gemini y retirar la ruta monolítica OpenAI. |
| **B. Mantener Gemini como motor principal** | Integración nativa multimodal y con Google Search en ciertos endpoints experimentales. | Mayor costo por token en procesamiento masivo; el código de backend ya migró hacia la interfaz OpenAI/DeepSeek en `dossier.llm`. |
| **C. Mantener coexistencia con selector en tiempo de ejecución (DeepSeek/Gemini/OpenAI)** | Flexibilidad teórica de proveedor. | Multiplica la superficie de pruebas; induce a falsos positivos en pipelines; deuda técnica permanente; riesgo de llamadas accidentales sin orquestación. |

## Decisión

Se establece **DeepSeek (a través de `backend/src/dossier/llm/*`) como la única línea de implementación canónica**.

Acciones inmediatas y planificadas:
1. **S0.4:** Formalizar esta decisión y documentar la arquitectura.
2. **S1.6:** Retirar el directorio `backend/src/dossier/gemini/` en Sprint 1. Renombrar las referencias heredadas como `gemini_analysis_markdown` a `llm_analysis_markdown` y `_node_synthesize_gemini` a `_node_synthesize_llm`.
3. **S1.6:** Deprecar y eliminar `DOSSIER_LEGACY_OPENAI` y `services/openai_dossier.py`, consolidando todas las ejecuciones bajo el orquestador LangGraph.

## Consecuencias

- **Positivas:** El mapa conceptual del código se simplifica radicalmente. Toda llamada a modelos de lenguaje pasa por `backend/src/dossier/llm/client.py`. Los logs y métricas reflejan el proveedor verídico.
- **Riesgos y mitigaciones:** Si el servicio de DeepSeek sufriera una degradación prolongada, el fallback se implementará en el cliente unificado `dossier.llm.client` mediante configuración de endpoint compatible con OpenAI, no mediante shims bifurcados en el código.
