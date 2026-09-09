# Las cinco brechas del alcance firme

Evidencia verificada sobre el código el **07-09-2026**. Cada afirmación está anclada a un
archivo y línea.

Las referencias `archivo:línea` envejecen. Si una no coincide, corrígela en el mismo PR en que
lo descubras.

---

## B1 · Síntesis en Markdown sin contrato JSON validado

**Estado:** abierta · **Cierra en:** Sprint 4 · **Tareas:** S0.9, S0.10, S4.1 a S4.7, S5.5

### Qué pasa

La capa de síntesis produce Markdown y lo persiste como tal.

| Dónde | Qué hay |
|---|---|
| `backend/src/dossier/services/person_research_pipeline.py:154` | Lee el resultado desde la clave `gemini_analysis_markdown` |
| `person_research_pipeline.py:190` y `:284` | Persiste con el envoltorio `{"format": "markdown"}` |
| `backend/src/dossier/db/models.py:319` | `dossier_data` es `JSONB` — el contenedor es JSON, el contenido no está validado |
| `backend/src/dossier/schemas/` | **No existe** modelo Pydantic de salida del dossier |
| `frontend/package.json` | Depende de `react-markdown` y `remark-gfm` para renderizar |

El contenedor es JSON pero nada valida su contenido. El frontend confirma el diagnóstico desde
el otro extremo: renderiza Markdown, no datos estructurados.

### Qué falta además

- Entidades para **trayectoria profesional** y **menciones de prensa**. No existen tablas.
- La columna `alerts` existe (`models.py:320`) pero sin entidad ni esquema detrás.
- **Trazabilidad por fuente.** `agents_activated`, `agents_failed` y `data_sources_used`
  (`models.py:322-331`) son arreglos de texto: dan trazabilidad de *agente*, no de *fuente por
  afirmación*. El objetivo OE5 exige lo segundo.

### Detalle que confunde

El pipeline etiqueta el agente como `deepseek_person_analysis` (`:227`, `:254`, `:316`) pero lee
la clave `gemini_analysis_markdown`. El README declara `gemini/` como shim de compatibilidad
hacia `llm/` (DeepSeek). El nombre de la clave sobrevivió al cambio de proveedor. **S0.4** debe
resolverlo.

---

## B2 · Sin agente de registros corporativos europeos

**Estado:** abierta · **Cierra en:** Sprints 1 y 2 · **Tareas:** S0.6, S0.12, S1.8, S1.9, S2.1 a S2.7

### Qué pasa

Solo existen dos jurisdicciones. `backend/src/dossier/graphs/corporate_dossier_graph.py`:

| Línea | Llamada |
|---|---|
| 77 | `build_uk_corporate_context_markdown` |
| 101 | `build_us_corporate_context_markdown` |

No hay módulo, cliente ni credencial para ninguna fuente de Europa continental.

### Por qué es la brecha de mayor riesgo

- No hay nada reutilizable más allá del patrón de los dos agentes existentes
  (`companies_house/`, `sec_edgar/`).
- La cobertura, el costo y las condiciones de licencia **varían por país**.
- Es una dependencia externa con plazos que no controlamos: por eso **S0.6 arranca en la
  semana 1** y vence en la semana 3, antes que cualquier otra evaluación.

### Decisión de alcance

Comprometer por escrito solo los países verificados en el Sprint 0. El resto se registra como
trabajo futuro. Es la mitigación del riesgo R2.

---

## B3 · Sin agente de noticias

**Estado:** abierta · **Cierra en:** Sprint 3 · **Tareas:** S0.7, S3.1 a S3.4

### Qué pasa

La palabra «noticias» aparece **solo dentro de las plantillas de instrucción al modelo**:
`backend/src/dossier/services/person_dossier_locales.py`, líneas 7, 42, 78 y 104, con sus
equivalentes en inglés desde la línea 121.

No hay cliente de NewsAPI, GDELT, Bing News ni SerpAPI. No hay dependencia asociada en
`backend/requirements.txt`.

### La consecuencia real

Se le pide al modelo que considere noticias **sin entregarle ninguna**. Toda mención de prensa
en un dossier actual proviene del conocimiento interno del modelo: sin fuente citable, sin fecha
de publicación, sin fecha de consulta.

Es un problema de calidad, no solo de funcionalidad: son afirmaciones sobre personas
identificables sin respaldo verificable.

### Riesgo asociado

Homónimos y datos incompletos (riesgo R6). El filtro de homónimos (**S3.3**) se prueba **antes**
de integrar el módulo a la síntesis. Un dossier con menciones de otra persona es peor que un
dossier sin prensa.

---

## B4 · Estados por sondeo, no en tiempo real

**Estado:** abierta · **Cierra en:** Sprints 4 y 5 · **Tareas:** S0.11, S4.8, S4.9, S5.1 a S5.4

### Qué pasa

| Dónde | Qué hay |
|---|---|
| `frontend/src/providers/DossierJobsProvider.tsx:285` | `window.setInterval` |
| `frontend/src/providers/NotificationsProvider.tsx:177` | `window.setInterval(() => void poll(), POLL_MS)` |
| backend | **No hay** `StreamingResponse`, ni endpoint `text/event-stream`, ni WebSocket |

### El producto ya lo declara al usuario

Las únicas apariciones de «WebSocket» en el código son cadenas de interfaz que anuncian la
brecha. En `frontend/src/i18n/messages/es.ts`:

- línea 104 — `"phase.4": "Generar dossier (mock WebSocket)"`
- línea 108 — `"phase.8": "WebSocket real y estados en vivo"`

Están traducidas a los cinco idiomas. **S3.7** debe actualizarlas cuando el canal exista.

### Riesgo al migrar

El sondeo es tolerante a cortes de red por naturaleza; un canal persistente no lo es. Por eso
**S5.3** (reconexión con retroceso progresivo) no es opcional: sin ella el cambio empeora la
experiencia.

Orden obligatorio (riesgo R5): migrar `DossierJobsProvider` primero, verificarlo, y solo
entonces `NotificationsProvider`.

---

## B5 · Entrega por correo inexistente

**Estado:** abierta · **Cierra en:** Sprints 5 y 6 · **Tareas:** S0.8, S5.6, S5.7, S6.1 a S6.4

### Qué pasa

El modelo de datos está preparado desde el principio y el comportamiento no existe.

| Dónde | Qué hay |
|---|---|
| `backend/src/dossier/db/models.py:350` | `email_sent` |
| `models.py:351` | `email_sent_at` |
| `models.py:354` | `email_recipients` |
| `models.py:183` | `auto_send_email` en la integración de calendario |
| `models.py:184` | `email_cc_assistant` |
| backend | **No hay** `smtplib`, `aiosmtplib`, ni SDK de Resend, SendGrid, Mailgun, Postmark o SES |
| `backend/requirements.txt` | Sin dependencia de correo |

### El diseño existía

`backend/src/dossier/db/Migracion.md` prevé una tabla de configuración de correo con
`provider IN ('gmail', 'outlook', 'smtp')` (línea 969), `smtp_host`, `smtp_port`,
`smtp_username` y `smtp_password_encrypted` con AES-256 (líneas 976-980).

Se diseñó y nunca se implementó. **S0.8** debería revisar ese diseño antes de elegir proveedor:
puede que la decisión ya esté tomada y solo falte ejecutarla.

---

## Resumen

| | Brecha | Tareas | Sprint | Riesgo asociado |
|---|---|---|---|---|
| **B1** | Síntesis sin contrato JSON | 10 | 4 | R3 (JSON no conforme), R9 (dossiers históricos) |
| **B2** | Sin registros europeos | 10 | 1-2 | R2 (cobertura y licencias) |
| **B3** | Sin agente de noticias | 5 | 3 | R6 (homónimos) |
| **B4** | Sin tiempo real | 7 | 4-5 | R5 (estado del dashboard) |
| **B5** | Sin entrega por correo | 7 | 5-6 | — |

Estado actualizado en vivo:

```bash
python .harness/next.py --status
```
