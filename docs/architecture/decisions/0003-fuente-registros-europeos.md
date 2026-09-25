# 0003 · Fuente de registros corporativos europeos

- **Fecha:** 2026-09-09
- **Estado:** aceptada
- **Decide:** FO
- **Tarea:** S0.6 (Brecha B2, Riesgo R2)

## Contexto

El sistema actual cubre únicamente el Reino Unido (`companies_house`) y Estados Unidos (`sec_edgar`). La brecha **B2** exige incorporar cobertura de registros corporativos para Europa continental. 

El riesgo **R2** identificó que la cobertura, costo y licencias varían enormemente por jurisdicción en la UE, existiendo fuentes comerciales costosas (OpenCorporates, North Data) y registros oficiales fragmentados por estado miembro. El compromiso del Sprint 0 es seleccionar fuentes verificables que permitan arrancar el cliente HTTP en Sprint 1 (S1.8) y el agente en Sprint 2 (S2.1) sin depender de aprobaciones comerciales externas.

## Alternativas evaluadas

| Proveedor / Fuente | Cobertura | Costo y Cuotas | Licencia / Acceso | Factibilidad Técnica |
|---|---|---|---|---|
| **OpenCorporates API** | Global (múltiples países UE) | Plan básico restringido (50 req/día); planes comerciales >$500/mes | Requiere suscripción comercial para producción | Excelente (API REST unificada) |
| **North Data API** | Excelente en DACH (Alemania, Austria, Suiza) y Francia | Costo por consulta (~€0.10 - €0.50/consulta); sin tier gratuito ilimitado | Comercial B2B | Muy buena (JSON estructurado) |
| **BRIS (Business Registers Interconnection System - UE)** | Toda la Unión Europea | Gratuito para búsqueda básica, de pago para certificados oficiales | Orientado a portal web e-Justice; no ofrece API REST pública abierta sencilla | Compleja (sin endpoint JSON estándar abierto) |
| **API Recherche d'entreprises (data.gouv.fr - Francia)** | 100% empresas francesas (SIREN/SIRET) | Gratuita (Open Data oficial del gobierno francés) | Licencia Abierta (Etalab 2.0); sin coste | Inmediata (REST JSON de alta velocidad, sin necesidad de API key obligatoria) |
| **Gemeinsames Registerportal (Alemania / OffeneRegister)** | 100% empresas registradas en Alemania (Handelsregister) | Gratuita | Open Data | Muy buena (JSON estructurado con razón social, HRB/HRA y directores) |

## Decisión

Se adopta un **enfoque por etapas con fuentes oficiales Open Data de Europa Continental**:

1. **Alcance Firme MVP (Sprint 1 y 2 · S1.8, S2.1-S2.7):**
   - **Francia:** Cliente oficial contra la **API Recherche d'entreprises** del gobierno francés (`https://recherche-entreprises.api.gouv.fr/search`). Provee razón social, número de registro (SIREN/SIRET), estado mercantil (activo/cesado), domicilio y directores (`dirigeants`).
   - **Alemania:** Conector estandarizado para **Handelsregister** a través de la API pública estructurada de registros corporativos alemanes (`OffeneRegister` / Handelsregister API).
2. **Normalización Común (S1.9):**
   - Ambas fuentes se normalizan al esquema unificado `RegistroCorporativo` interoperable con Companies House (UK) y SEC EDGAR (US).
3. **Manejo de Jurisdicciones No Cubiertas:**
   - Para países europeos fuera de Francia y Alemania, el orquestador registrará explícitamente `agents_skipped` con la indicación `"Jurisdicción no disponible en fase actual"`, sin interrumpir la generación del dossier corporativo.

## Consecuencias

- **Mitigación de R2:** No se depende de tarjetas de crédito corporativas ni de contratos de API empresariales para completar el Capstone.
- **Implementación inmediata:** En S1.8 se desarrollará el cliente HTTP en `backend/src/dossier/eu_registry/` testeado con respuestas simuladas (`respuesta_fija`) según la política de pruebas.
