# 0002 · Modelo de lenguaje para síntesis ejecutiva

- **Fecha:** 2026-09-09
- **Estado:** aceptada
- **Decide:** FO
- **Tarea:** S0.5

## Contexto

La síntesis de dossiers ejecutivos (objetivo OE3 y brecha B1) requiere un modelo de lenguaje capaz de consolidar datos heterogéneos de personas, registros corporativos y noticias en un contrato JSON estricto. La elección del modelo impacta directamente en:
1. **Tasa de conformidad JSON (Riesgo R3):** El modelo debe respetar al 100% el esquema Pydantic sin alucinaciones de campos ni sintaxis Markdown espuria.
2. **Costo operativo por dossier:** Dossier promedio de ~8.000 tokens de entrada (contextos UK/US/EU + PDL + noticias) y ~2.000 tokens de salida.
3. **Latencia de respuesta:** Mantener la generación en <30 segundos para no bloquear el flujo del usuario.

## Alternativas evaluadas

| Criterio | DeepSeek-V3 (`deepseek-chat`) | OpenAI GPT-4o | OpenAI GPT-5.6 Luna / mini |
|---|---|---|---|
| **Costo Entrada (1M tokens)** | $0.14 USD (hit cache $0.014) | $2.50 USD | $0.15 USD (mini) / $3.00 USD |
| **Costo Salida (1M tokens)** | $0.28 USD | $10.00 USD | $0.60 USD (mini) / $12.00 USD |
| **Costo promedio por dossier** | **~$0.0017 USD** | ~$0.040 USD (23x más caro) | ~$0.0024 USD |
| **Conformidad JSON Schema** | Alta con `response_format={"type": "json_object"}` y validación Pydantic | Excelente (`response_format={"type": "json_schema", "strict": true}`) | Excelente con modo estructurado |
| **Latencia promedio** | 12 - 18 s | 8 - 14 s | 6 - 12 s |
| **Calidad de redacción en español** | Excelente y natural | Excelente | Muy buena |
| **Compatibilidad de API** | Protocolo compatible OpenAI | Nativo OpenAI | Nativo OpenAI |

## Decisión

Se adopta **DeepSeek-V3 (`deepseek-chat`) como el modelo principal de producción**.

1. **Eficiencia de costos:** Su costo operativo es inferior a $0.002 USD por dossier, permitiendo sostener el plan Free (10 dossiers al mes) sin incurrir en déficit financiero.
2. **Estrategia para el Riesgo R3 (JSON no conforme):** Se implementa un validador Pydantic en capa de aplicación (`dossier.schemas.dossier_output`) con política de reintento automático (máximo 1 reintento con corrección de error en el prompt) en caso de fallo sintáctico.
3. **Fallback configurable:** Se mantiene en `dossier.llm.client` la capacidad de configurar `OPENAI_API_KEY` con `GPT-4o-mini` como proveedor de contingencia si la latencia o disponibilidad de DeepSeek lo amerita.

## Consecuencias

- **Ataduras:** La capa de síntesis de S4.2 se optimiza para los prompts y directivas de formato de DeepSeek.
- **Fuera de alcance:** No se utilizarán modelos de razonamiento lento (`deepseek-reasoner` / `o1`) en el pipeline interactivo debido a que superan los 60 segundos de latencia comprometidos en el objetivo de producto.
