# 0004 · Proveedor de búsqueda de noticias

- **Fecha:** 2026-09-09
- **Estado:** aceptada
- **Decide:** FO
- **Tarea:** S0.7 (Brecha B3, Riesgo R6)

## Contexto

La brecha **B3** señala que las plantillas de instrucción a los modelos de lenguaje solicitan considerar noticias recientes sin haber proporcionado ningún insumo de prensa al contexto (`person_dossier_locales.py:7`). Cualquier mención periodística actual surge de la memoria del modelo, sin trazabilidad, sin fecha exacta y propensa a alucinaciones sobre personas vivas.

El riesgo **R6** alerta sobre el impacto de homónimos: atribuir noticias de otra persona a un participante de la reunión destruye la credibilidad del producto.

## Alternativas evaluadas

| Proveedor | Cobertura | Cuotas y Costo | Formato y Metadatos | Riesgo de Homónimos |
|---|---|---|---|---|
| **GDELT Project (DOC 2.0 API)** | Global, miles de medios en más de 65 idiomas | Gratuito, sin clave de API obligatoria, sin cuotas mensuales restrictivas | JSON estructurado (`url`, `title`, `seendate`, `domain`, `socialimage`) | Medio (requiere filtrado por contexto y nombre compuesto) |
| **NewsAPI.org** | Medios tradicionales principales (Occidente) | 100 req/día en plan Developer (solo local/no comercial); planes de pago >$449/mes | JSON muy limpio (`source.name`, `author`, `title`, `description`, `url`, `publishedAt`) | Medio-Bajo |
| **Tavily Search API** | Optimizada para agentes de IA | 1.000 búsquedas gratuitas al mes | Provee contexto enriquecido y extracto filtrado | Bajo (búsqueda semántica) |
| **Bing News / Google Search SerpAPI** | Excelente | Planes comerciales con costo por request (~$0.01/req) | Datos completos de prensa | Bajo |

## Decisión

Se define una **arquitectura de proveedor híbrida con GDELT DOC API como estándar y NewsAPI como alternativa**:

1. **Fuente Base (Sin costo operativo):** Se utiliza la API **GDELT DOC 2.0** (`https://api.gdeltproject.org/api/v2/doc/doc`) para consultar artículos periodísticos de los últimos 30 días filtrando por nombre del participante y empresa (`query="Nombre Participante" AND "Empresa"`).
2. **Conector Secundario Configurable:** Se soporta `NEWS_API_KEY` para organizaciones que cuenten con suscripción a **NewsAPI**, utilizándolo si la variable está definida.
3. **Filtro Estricto de Homónimos (S3.3):**
   - Una noticia solo se incorpora al dossier si el texto o titular contiene tanto el nombre de la persona como al menos una entidad relacionada (organización actual, cargo o país).
   - En caso de ambigüedad, la noticia se descarta: un dossier sin noticias es preferible a un dossier con imputaciones falsas.
4. **Trazabilidad (S3.4):** Cada mención de prensa en el contrato JSON final incluirá: titular, medio emisor, URL pública verificable, fecha de publicación original y fecha de consulta.

## Consecuencias

- **Cierre de B3:** El nodo `news_agent` alimentará noticias reales al orquestador LangGraph.
- **Sin costes imprevistos:** GDELT permite pruebas continuas e integración en desarrollo y evaluación académica sin agotar presupuestos.
