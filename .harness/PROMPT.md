# Contexto inicial

Léelo entero antes de tu primera tarea en este repositorio. Son cinco minutos que evitan
reconstruir mal el proyecto.

## Qué es Project Dossier

Un asistente que prepara información antes de una reunión. Se integra con Google Calendar y
Outlook, detecta reuniones externas próximas y genera un dossier sobre los participantes:
identidad, historial corporativo, presencia en medios, alertas de riesgo y hasta tres ideas
para iniciar la conversación. Reúne y contrasta antecedentes profesionales, registros
corporativos oficiales y noticias, y usa agentes especializados más una capa de síntesis con
un modelo de lenguaje.

El objetivo de producto es reducir una preparación de unos 20 minutos a menos de 30 segundos
de esfuerzo activo.

Cliente: **Alloxentric**. Mercado inicial: Reino Unido y Estados Unidos, con expansión prevista
a Europa continental.

## Qué estamos haciendo nosotros

**Esto es un proyecto de continuidad.** El sistema ya existe, funciona y tiene usuarios
potenciales reales. No lo estamos construyendo: estamos cerrando la distancia entre lo que
ofrece hoy y lo que la especificación compromete.

Equipo de tres, 18 semanas, del 07-09-2026 al 10-01-2027.

### Lo que ya funciona y no hay que rehacer

Autenticación JWT con roles · Multiempresa con aislamiento por organización · Calendarios
Google y Microsoft · Generación asíncrona con cola Redis · Investigación de personas (PDL,
Lusha) · Registros corporativos de Reino Unido (Companies House) y Estados Unidos (SEC EDGAR)
orquestados con LangGraph · Créditos y planes · Retención configurable · Dashboard Next.js en
cinco idiomas.

Si algo de esta lista parece que falta, búscalo bien antes de escribirlo de nuevo.

### Las cinco brechas que sí hay que cerrar

**B1 · La síntesis se guarda como Markdown, sin contrato JSON validado.**
`person_research_pipeline.py:190` persiste `{"format": "markdown"}`. No existe modelo Pydantic
de salida del dossier. El frontend depende de `react-markdown`. Faltan entidades para alertas,
trayectoria y prensa, y no hay trazabilidad de fuente por afirmación.

**B2 · No existe agente de registros corporativos europeos.**
`corporate_dossier_graph.py` invoca solo UK (línea 77) y US (línea 101). Es la brecha de mayor
riesgo: no hay nada reutilizable más allá del patrón de los dos agentes existentes, y la
cobertura, el costo y las licencias varían por país.

**B3 · No existe agente de noticias.**
La palabra aparece solo dentro de las plantillas de instrucción al modelo. Se le pide al modelo
que considere noticias sin entregarle ninguna: toda mención de prensa actual carece de fuente
citable y de fecha.

**B4 · El avance se obtiene por sondeo, no en tiempo real.**
`DossierJobsProvider.tsx:285` y `NotificationsProvider.tsx:177` usan `setInterval`. En el
backend no hay SSE ni WebSocket. La propia interfaz lo declara al usuario:
`"phase.8": "WebSocket real y estados en vivo"`.

**B5 · La entrega por correo no existe.**
Las columnas `email_sent`, `email_sent_at` y `email_recipients` existen en el modelo desde el
principio, pero no hay ningún cliente de correo en el backend ni dependencia asociada.

### Lo que también hay que arreglar

La base técnica está menos consolidada de lo que sugiere el porcentaje de avance:

- No hay integración continua. Ninguna.
- No hay migraciones versionadas. El esquema se aplica desde `db/schema_patches.py`.
- No hay linter ni verificación de tipos en el backend.
- 40 pruebas declaradas frente a 100 módulos Python.
- De los cuatro controles de seguridad comprometidos, solo existe el control de acceso: no hay
  limitación de tasa, no hay auditoría, y la retención es de 7 a 90 días cuando la
  especificación exige 24 horas con borrado verificado.
- El token de acceso dura 7 días por omisión y vive en `localStorage`.

Por eso el **Sprint 1 es bloqueante**: sin CI ni migraciones, ningún sprint posterior puede
demostrar que no introduce regresiones.

## Cómo está organizado el trabajo

Sprint 0 de diagnóstico (4 semanas) y siete sprints de dos semanas. 77 tareas con identificador
`S<sprint>.<n>`, responsable único y criterio de aceptación.

| Sprint | Semanas | Foco |
|---|---|---|
| 0 | 1-4 | Diagnóstico, decisiones técnicas, diseño |
| 1 | 5-6 | Consolidación técnica **(bloqueante)** |
| 2 | 7-8 | Agente europeo (B2) |
| 3 | 9-10 | Agente de noticias (B3) + dashboard + seguridad |
| 4 | 11-12 | Contrato JSON (B1) + canal de estados (B4) |
| 5 | 13-14 | Tiempo real en el dashboard (B4) + correo (B5) |
| 6 | 15-16 | Entrega automática (B5) + cierre de seguridad |
| 7 | 17-18 | Validación, documentación, cierre |

Detalle completo por tarea: `.harness/feature_list.json` y el
[Plan de Trabajo Detallado](../docs/documentos-capstone/Plan_de_Trabajo_Detallado_Dossier.pdf).

## Equipo

| | Quién | Frente |
|---|---|---|
| **FO** | Felipe Orellana Álvarez | Backend y agentes |
| **DG** | Darío García Avendaño | Frontend e integraciones de usuario |
| **FD** | Felipe Docmac Bravo | Seguridad y aseguramiento de la calidad |

## Reglas que no se negocian

1. **Evidencia o no está terminado.** Ninguna función se presenta como completa sin
   implementación, validación y documentación. Esto aplica al informe final y a cada tarjeta.
2. **Solo datos autorizados y ambientes de prueba.** El sistema trata datos de personas
   identificables. Nunca datos reales de producción, nunca cobros reales.
3. **Las decisiones técnicas se escriben.** En `docs/architecture/decisions/`, no en un chat.
4. **Una sesión, una tarea.** Y el estado queda en los archivos al terminar.

## Dos fechas críticas

- **Semana 1** — arrancar la evaluación de la fuente europea (S0.6). Es la dependencia externa
  de plazo menos controlable de todo el proyecto.
- **28-12-2026** — congelamiento de funcionalidades. Desde ahí solo correcciones de defectos.

El receso de fin de año cae sobre las semanas 16 y 17. Está registrado como riesgo R1 y debe
acordarse con el docente guía durante el Sprint 0 (S0.15).
