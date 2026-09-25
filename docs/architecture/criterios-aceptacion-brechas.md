# Criterios de aceptación por brecha priorizada

- **Fecha:** 2026-09-09
- **Estado:** acordado
- **Responsable:** EQ (Equipo)
- **Tarea:** S0.13

---

## B1 · Síntesis en Markdown sin contrato JSON validado

- **CA-B1.1 (Validación de contrato):**
  - *Dado* el término de la síntesis del dossier por el LLM, *cuando* se serializa el resultado, *entonces* debe conformar estrictamente el modelo Pydantic `DossierExecutivePayload`. Si el JSON contiene claves faltantes o tipos incorrectos, se dispara una rutina de auto-reparación antes de persistir.
- **CA-B1.2 (Trazabilidad por afirmación):**
  - *Dado* cualquier dato estructurado (cargo, alerta, registro corporativo, noticia), *cuando* se inspecciona la entidad, *entonces* debe contener un objeto `source` no nulo con `source_type`, `source_name`, `url` y `retrieved_at`.
- **CA-B1.3 (Persistencia dual segura):**
  - *Dado* el guardado en PostgreSQL (`dossier_data`), *cuando* se inserta el nuevo JSON, *entonces* la clave `"billing"` debe estar presente en el nivel superior del JSONB con valor `'charged'` o `'none'`, asegurando que el trigger de descuento de créditos en la base de datos funcione sin alteración.
- **CA-B1.4 (Renderizado frontend sin parser Markdown como único medio):**
  - *Dado* un dossier generado bajo el contrato v2.0, *cuando* el usuario abre el detalle en el dashboard, *entonces* la interfaz renderiza componentes nativos React (tarjetas de alertas, línea de tiempo de cargos, tabla de registros corporativos) leyendo los campos del JSON sin requerir parsing de texto plano Markdown.

---

## B2 · Sin agente de registros corporativos europeos

- **CA-B2.1 (Consulta Francia):**
  - *Dado* un participante o empresa con sede en Francia (SIREN/SIRET o razón social válida), *cuando* el agente europeo ejecuta la búsqueda contra la API Recherche d'entreprises, *entonces* retorna un `CorporateRegistryRecord` con jurisdicción `"FR"`, razón social oficial, estado de actividad y directores.
- **CA-B2.2 (Consulta Alemania):**
  - *Dado* una empresa con registro mercantil en Alemania, *cuando* el agente europeo ejecuta la búsqueda contra el conector de Handelsregister, *entonces* retorna un `CorporateRegistryRecord` con jurisdicción `"DE"`, número HRB/HRA y tribunal de registro.
- **CA-B2.3 (Empresa inexistente):**
  - *Dado* un término de búsqueda que no produce coincidencias en los registros europeos, *cuando* el agente finaliza, *entonces* devuelve `None` sin arrojar excepción no controlada, y el orquestador registra la fuente como consultada sin hallazgos.
- **CA-B2.4 (Tolerancia a fallos):**
  - *Dado* un error HTTP 500 o timeout de 10 segundos en la API europea, *cuando* el orquestador LangGraph procesa la respuesta, *entonces* añade `'agent_corporate_eu'` a la lista `agents_failed` y el dossier final se genera normalmente con los datos de las demás fuentes.

---

## B3 · Sin agente de noticias

- **CA-B3.1 (Extracción de noticias reales):**
  - *Dado* un participante y su empresa, *cuando* el agente de noticias consulta GDELT / NewsAPI, *entonces* recupera artículos de prensa de los últimos 30 días con titular, medio emisor, fecha de publicación ISO y URL verificable.
- **CA-B3.2 (Filtro estricto de homónimos):**
  - *Dado* un artículo periodístico devuelto por la API que menciona el nombre de la persona pero ninguna referencia a su organización, cargo o sector, *cuando* se aplica el filtro de homónimos (S3.3), *entonces* el artículo es descartado y no se incluye en el dossier.
- **CA-B3.3 (Cero alucinaciones de prensa):**
  - *Dado* un dossier generado, *cuando* no existen noticias comprobadas en las fuentes externas, *entonces* la sección `press_mentions` es una lista vacía `[]`, prohibiendo que el LLM invente eventos noticiosos en el resumen.

---

## B4 · Estados por sondeo, no en tiempo real

- **CA-B4.1 (Transmisión Server-Sent Events):**
  - *Dado* un cliente autenticado conectado a `GET /dossiers/{id}/stream`, *cuando* inicia la generación, *entonces* recibe frames `text/event-stream` con eventos individuales (`agent_progress`) conforme cada agente (UK, US, EU, Noticias) comienza y finaliza su tarea.
- **CA-B4.2 (Latencia de notificación):**
  - *Dado* el cambio de estado de un nodo en LangGraph, *cuando* se emite el evento, *entonces* el cliente lo recibe en menos de 500 ms, eliminando la ventana ciega de 3 segundos del sondeo por intervalo.
- **CA-B4.3 (Reconexión automática):**
  - *Dado* un corte transitorio de red de hasta 30 segundos, *cuando* la conexión se restablece, *entonces* el cliente frontend reanuda la escucha enviando `Last-Event-ID` y sincroniza el estado sin recargar la página completa.

---

## B5 · Entrega por correo inexistente

- **CA-B5.1 (Despacho automático pre-reunión):**
  - *Dado* un dossier corporativo generado para una reunión agendada, *cuando* restan 20 minutos para el inicio del evento y la integración tiene `auto_send_email = True`, *entonces* el servicio de correo despacha un resumen ejecutivo al organizador.
- **CA-B5.2 (Registro en base de datos):**
  - *Dado* el envío exitoso del correo, *cuando* finaliza la llamada SMTP / Microsoft Graph, *entonces* se actualizan en PostgreSQL las columnas `email_sent = True`, `email_sent_at = NOW()` y `email_recipients = [...]`.
- **CA-B5.3 (Manejo de fallo de entrega):**
  - *Dado* un error de autenticación SMTP o rechazo del servidor receptor, *cuando* el worker procesa el envío, *entonces* registra el error en los logs, marca `email_sent = False` y no corrompe el estado del dossier ni cancela el evento de calendario.
