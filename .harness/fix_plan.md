# Plan de correcciones priorizado

Deuda técnica y riesgos detectados en la auditoría del 07-09-2026, ordenados por lo que
desbloquean. La numeración `S<sprint>.<n>` es la del plan; las entradas sin identificador son
hallazgos que aún no tienen tarea asignada.

Estado detallado y dependencias: `feature_list.json`.

---

## P0 · Bloquean todo lo demás

Sin estos cuatro, la Definición de Terminado no es verificable y ningún sprint posterior puede
demostrar que no introduce regresiones.

| | Qué | Por qué |
|---|---|---|
| **S1.5** | No hay integración continua | No existe `.github/`. Ninguna verificación automática antes de integrar |
| **S1.1** | No hay migraciones versionadas | Sin Alembic. El esquema se aplica desde `db/schema_patches.py` (67 líneas). Los sprints 4 y 6 cambian el esquema |
| **S1.2** | No hay linter ni tipos en el backend | Sin `pyproject.toml`, sin ruff, sin mypy. El objetivo OE2 exige «análisis estático sin errores» y no hay herramienta que lo mida |
| **S1.3** | 21 errores de eslint en el frontend | Medidos el 07-09-2026 en 16 archivos. Nadie los veía porque no hay CI. Detalle abajo |
| **S0.3** | La deuda no está del todo medida | Falta cobertura y auditoría de dependencias. La suite **ya corre**: 49 en verde, 13 en espera de su tarea |

---

## P1 · Seguridad

De los cuatro controles que compromete el objetivo OE8, **solo existe el control de acceso**.

| | Qué | Evidencia |
|---|---|---|
| **S5.8** | Sin limitación de tasa | No hay slowapi ni middleware equivalente. Las coincidencias de `rate_limit` son manejo de errores del proveedor LLM (`llm/common.py:61`) |
| **S4.10** | Sin registro de auditoría | No hay tabla ni servicio. Se tratan datos de personas identificables sin rastro de quién accedió |
| **S6.5** | Retención diverge de la especificación | `ALLOWED_DOSSIER_RETENTION_DAYS = {7,14,30,90}`, 30 por omisión, y admite conservar indefinidamente. La especificación exige 24 horas con borrado verificado |
| **S3.9** | Token de 7 días en `localStorage` | `jwt_tokens.py:41` usa 10080 minutos por omisión. Los tokens de restablecimiento sí usan 15 minutos (`:66`, `:90`) |
| **S3.8** | CORS permisivo | `api/app.py:211-215` con `allow_methods=["*"]` junto a `allow_credentials=True` |

---

## P2 · Ambigüedad estructural

| | Qué | Detalle |
|---|---|---|
| **S0.4** | Línea de implementación sin declarar | Coexisten `llm/client.py` (DeepSeek), `gemini/analyze.py` (shim de compatibilidad) y `services/openai_dossier.py`. El pipeline etiqueta `deepseek_person_analysis` pero lee la clave `gemini_analysis_markdown`. El nombre miente sobre el proveedor |
| **S1.6** | Rutas legadas pendientes de retiro | `security/legacy_routes.py` con `assert_legacy_route_allowed()`. Bien acotadas, pero deben desaparecer |
| **S1.4** | Dependencias sin fijar | `requirements.txt` usa `>=` en 13 de 15 líneas; `requests` va sin versión. Las compilaciones no son reproducibles |

---

## P3 · Cobertura de pruebas

40 funciones de prueba declaradas en 11 archivos, frente a 100 módulos Python.

Lo que hoy tiene prueba: RBAC, créditos, permisos, deduplicación de personas, búsqueda PDL,
etiquetas de reunión, fechas de calendario, claves de internacionalización, rutas legadas.

Lo que no tiene prueba y debería, por orden de riesgo:

1. Aislamiento entre organizaciones sobre los recursos nuevos (**S6.7**)
2. Tolerancia a fallos por agente (**S7.2**)
3. Descuento de créditos en el flujo completo (**S7.3**) — sensible al cambio de `dossier_data` en S4.3
4. El orquestador `corporate_dossier_graph.py`
5. El pipeline `person_research_pipeline.py`

---

## Análisis estático del frontend — medido

`npm run lint` el 07-09-2026: **21 errores y 6 avisos** en 16 archivos. Ninguno introducido por
el trabajo reciente; llevaban ahí sin que nadie los viera porque no existe integración continua.

El más repetido es `react-hooks/set-state-in-effect`: llamar a `setState` dentro del cuerpo de un
`useEffect`, que provoca renderizados en cascada. Aparece en `PreferencesProvider.tsx:100` y en
varios paneles de ajustes.

Archivos afectados:

```
app/dashboard/dossiers/[id]/CorporateDossierDetailView.tsx
app/dashboard/dossiers/folder/[id]/page.tsx
app/dashboard/person-research/page.tsx
app/dashboard/settings/page.tsx
app/register/page.tsx
components/BrandLogo.tsx
components/dashboard/CalendarFormatGuideAnyAction.tsx
components/dashboard/CalendarMeetingFormatGuide.tsx
components/dashboard/CorporateDossierGenerateView.tsx
components/dossier/ShareDossierPanel.tsx
components/settings/BillingPanel.tsx
components/settings/CompanyContextPanel.tsx
components/settings/OrganizationMembersPanel.tsx
components/settings/PendingOrgInvitesPanel.tsx
hooks/useAuthMe.ts
providers/PreferencesProvider.tsx
```

`PreferencesProvider.tsx` merece atención especial: **S5.1 y S5.2 van a reescribir los
proveedores** para consumir el canal de estados progresivos. Conviene corregir sus efectos antes
de esa migración, no después, o se arrastra el problema al código nuevo.

Se corrigen en **S1.3**. Hasta entonces `scripts/qa.py` los reporta como fallo.

---

## Hallazgos sin tarea asignada

Detectados en la auditoría, fuera del alcance firme. Registrarlos en el informe final como
trabajo futuro si no se abordan.

- **[CRÍTICO] Next.js 16.2.6 con 3 CVEs críticas.** Medido con `npm audit` el 2026-09-23 (sesión
  local, S0.3): 3 vulnerabilidades críticas en `next@16.2.6`, variantes de RCE no autenticado y
  bypass del middleware de autorización. No estaba registrado con esta severidad en la auditoría
  del 07-09-2026. Fix disponible sin cambios de API relevantes: `npm install next@16.3.6`. A
  diferencia de **S1.4** (fijar versiones para builds reproducibles, que es sobre *cómo* se
  versiona), esto es sobre *qué* versión corre hoy — conviene resolverlo antes o independiente de
  S1.4, no esperar a que esa tarea se tome.
- **`db/models.py` desincronizado de `db/Migracion.md`.** Detectado al construir **S1.1**
  (migración de línea base de Alembic, 2026-09-23). Los modelos SQLAlchemy en `db/models.py`
  declaran ~10 tablas; el esquema real/documentado en `db/Migracion.md` tiene 19 tablas, 2 vistas
  y 9 triggers/funciones — incluye el mecanismo real de cobro de créditos
  (`fn_debit_credits_on_dossier`, `fn_credit_ledger_after_dossier_insert` sobre `dossiers`), que no
  existe en el ORM en absoluto. Confirmado no solo por lectura del `.md`: `account_service.py`
  hace SQL crudo contra `credit_ledger` y `dossier_alerts` porque no hay modelo ORM para esas
  tablas. Riesgo concreto: la migración de línea base (S1.1) usa `Base.metadata` como
  `target_metadata` en `alembic/env.py` para que futuros `alembic revision --autogenerate`
  comparen contra los modelos — mientras este hallazgo no se corrija, un autogenerate comparará
  contra metadata incompleta y puede proponer *borrar* las ~9 tablas y los 9 triggers reales que
  el ORM no conoce. No tomar `--autogenerate` a ciegas hasta que los modelos se completen.
- **4 pruebas en rojo en `test_credit_policy.py`.** Preexistentes desde antes de S0.3 (medidas
  igual el 07-09-2026 y de nuevo el 23-09-2026, sin cambios): `test_person_research_cost_is_one_credit`,
  `test_assert_sufficient_credits_insufficient_raises_402`,
  `test_calendar_estimate_corporate_plus_two_persons`, `test_calendar_estimate_person_only`.
  No investigadas a fondo todavía — quedaron fuera de **S1.3** a propósito (esa tarea es solo
  análisis estático, no corrección funcional). Sin tarea `S` asignada.
- **`gemini/` como shim.** El README lo declara shim de compatibilidad hacia `llm/`, pero la
  clave `gemini_analysis_markdown` sigue viva en el pipeline. S0.4 debe decidir si el shim se
  retira o se documenta como permanente. Mientras tanto, el nombre confunde a quien lee el código.
- **`dossier_routes.py:91`.** El descuento de créditos ocurre en la base de datos cuando
  `dossier_data->>'billing' != 'none'`, con una advertencia explícita de no duplicarlo en Python.
  S4.3 cambia justamente `dossier_data`: verificar que la condición siga funcionando (cubierto
  por S7.3, pero conviene mirarlo al implementar S4.3, no al final).
- **`db/Migracion.md` prevé configuración de correo** con `provider IN ('gmail','outlook','smtp')`
  y `smtp_password_encrypted`. El diseño existía; la implementación nunca se hizo. S0.8 debería
  revisarlo antes de elegir proveedor.
- **Sin `.env.example` verificado.** El README lo menciona pero no se comprobó su existencia ni
  si está completo. Revisar en S1.7.

---

## Riesgos que condicionan el plan

Registro completo con mitigaciones en el
[Plan de Trabajo Detallado](../docs/documentos-capstone/Plan_de_Trabajo_Detallado_Dossier.pdf),
sección 7, y en la tarjeta de riesgos del tablero.

Los tres que cambian decisiones de calendario:

- **R1 · Receso de fin de año sobre las semanas 16 y 17.** Sprint 6 y arranque del Sprint 7.
  Acordar en **S0.15**. Las tareas de seguridad ya están adelantadas a la semana 15.
- **R2 · Fuente europea.** Dependencia externa de plazo menos controlable. **S0.6 arranca en la
  semana 1**, antes que cualquier otra evaluación.
- **R3 · JSON no conforme del modelo.** La tasa de conformidad es criterio de selección en
  **S0.5**, no un dato que se descubra en el Sprint 4.
