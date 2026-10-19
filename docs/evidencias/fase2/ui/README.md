# Evidencias de interfaz · Fase 2

Capturas pedidas por el docente: el calendario visual y los indicadores conectados a datos.
Son capturas reales de la aplicación corriendo, sin retoques. Solo se recortaron al tamaño de la
ventana del navegador.

> **Ambiente local de pruebas, datos ficticios, proveedores simulados.** Ninguna captura muestra
> datos de personas o empresas reales, cuentas reales ni credenciales.

## Cómo se obtuvieron

| | |
|---|---|
| **Fecha** | 2026-10-19 |
| **Código** | `main` en `9f6c692` (merge del PR #24), sin cambios locales |
| **Backend** | API FastAPI real del repositorio, con el worker de generación en el mismo proceso, en `127.0.0.1:8030` |
| **Base de datos** | Postgres local, base desechable `dossier_evid_ui_test`, creada con `alembic upgrade head` y borrada al terminar. No se tocó `dossier_local` |
| **Frontend** | `next dev` del repositorio en `localhost:3040`, con `NEXT_PUBLIC_API_URL=http://127.0.0.1:8030` |
| **Navegador** | Chrome, controlado con Chrome DevTools MCP, a 1440 × 900 px |
| **Entorno** | Limpio. No se usó `backend/.env`: se definió solo `DATABASE_URL`, un `JWT_SECRET` de prueba y `CORS_ORIGINS`. Sin claves de PDL, DeepSeek, Companies House, SEC ni prensa, y sin OAuth real |

**Proveedores simulados.** Un lanzador fuera del repositorio importó la aplicación y reemplazó los
proveedores externos dentro del proceso. Después levantó uvicorn. Además, bloqueó toda conexión de
red que no fuera local.

- **Google Calendar y Microsoft Graph:** se reemplazó `requests` en `google_calendar_api` y
  `graph_calendar`. El parseo, la paginación, los filtros y la lectura por intervalo son el código
  real.
- **Calendario ficticio:** 19 eventos entre el 5 de octubre y el 10 de noviembre de 2026.
  - Reuniones con siete empresas inventadas, como «Andina Logística Ficticia SpA» o «Pacífico
    Energía Demo SA».
  - Asistentes con correos `@example.com`.
  - Reuniones internas y un feriado de día completo, que el resumen excluye.
- **Investigación:** PDL, DeepSeek, Companies House, SEC, Europa y prensa se simularon con pausas de
  3 a 7 s, para ver el avance. Se siguió la receta de `backend/scripts/generar_fixtures_progreso.py`.
  - Companies House falla a propósito para «Andina Logística Ficticia», así se ve un resultado
    parcial.
  - Los perfiles de PDL apuntan a `https://perfiles.example.com/...`.

**Usuario y datos.** El usuario se creó por `/register` con datos ficticios:
`analista.demo@consultora-demo.example.org`, empresa «Consultora Demo Ficticia». Después se ajustó
por SQL en la base de prueba:

- Plan `pro`, con 12 créditos al principio, para que aparezca el aviso de saldo insuficiente. Más
  tarde se subió a 40.
- Integraciones de Google y Outlook con un token ficticio.
- Zona horaria `America/Santiago`.

Los dossiers de las capturas se generaron desde la propia interfaz.

## Capturas

Todas son de hoy (2026-10-19) y del SHA `9f6c692`.

| Archivo | Qué muestra | Ruta de la app |
|---|---|---|
| [`01-resumen-indicadores-saldo-insuficiente.png`](01-resumen-indicadores-saldo-insuficiente.png) | Las cuatro tarjetas con datos reales del calendario simulado y de la base: 6 reuniones por preparar, cobertura 0 % (0 de 6), 26 créditos para preparar y 12 disponibles. Aparece el aviso «Supera tu saldo disponible» | `/dashboard` |
| [`02-calendario-mes.png`](02-calendario-mes.png) | Calendario visual, vista **Mes**, con Google (verde) y Outlook (azul), el feriado de día completo y «+1 más» en el día cargado | `/dashboard/automation` |
| [`03-calendario-semana.png`](03-calendario-semana.png) | Vista **Semana**: reuniones solapadas lado a lado y fila «Todo el día» | `/dashboard/automation` |
| [`04-calendario-dia.png`](04-calendario-dia.png) | Vista **Día** del 19 de octubre | `/dashboard/automation` |
| [`05-calendario-filtro-outlook.png`](05-calendario-filtro-outlook.png) | **Filtro por proveedor** «Outlook»: solo quedan las reuniones de Microsoft | `/dashboard/automation` |
| [`06-calendario-intervalo-noviembre.png`](06-calendario-intervalo-noviembre.png) | **Consulta por intervalo**. Al pasar a noviembre se piden solo los eventos de ese intervalo; las peticiones están en la sección siguiente | `/dashboard/automation` |
| [`07-reunion-avance-en-curso.png`](07-reunion-avance-en-curso.png) | Detalle de la reunión «Kick-off con Andina Logística Ficticia» **durante** la generación, con el panel «Avance y resultados» (S5.4). Reino Unido falló, el resto terminó y hay vista previa provisional del resumen. El aviso flotante muestra a Ana Prueba con «Buscar el perfil en PDL · En curso» | `/dashboard/automation` → reunión |
| [`08-reunion-resultado-parcial.png`](08-reunion-resultado-parcial.png) | La misma reunión **al terminar**: «Disponible con información parcial · Sin completar: Reino Unido», con las etapas de cada asistente | `/dashboard/automation` → reunión |
| [`09-reunion-dossier-listo.png`](09-reunion-dossier-listo.png) | Otra reunión, «Presentación a Pacífico Energía Demo», terminada sin fallos: «Dossier listo» y los dossiers guardados | `/dashboard/automation` → reunión |
| [`10-resumen-tras-generar.png`](10-resumen-tras-generar.png) | El resumen después de generar desde el calendario y subir el saldo: 2 por preparar, cobertura 50 % (2 de 4), 8 créditos para preparar y 35 disponibles, sin aviso. Muestra que los indicadores siguen a los datos | `/dashboard` |
| [`11-personas-etapas-y-resultado.png`](11-personas-etapas-y-resultado.png) | Personas, modalidad Registros PDL, para «Gabriela Ensayo». Se ven las etapas reales con su estado y motivo, el perfil encontrado, el informe y «Dossier listo» | `/dashboard/person-research` |
| [`12-dossier-corporativo-detalle.png`](12-dossier-corporativo-detalle.png) | Detalle de un dossier corporativo generado desde la reunión con Pacífico Energía Demo | `/dashboard/dossiers/{id}` |
| [`13-dossier-persona-detalle.png`](13-dossier-persona-detalle.png) | Detalle del dossier de persona de Gabriela Ensayo: avisos del informe y el informe generado | `/dashboard/dossiers/{id}` |
| [`14-resumen-ingles.png`](14-resumen-ingles.png) | El mismo resumen en **inglés**, con los mismos valores que la captura 10 salvo el saldo, que bajó por las investigaciones de Personas | `/dashboard` |
| [`15-calendario-semana-ingles.png`](15-calendario-semana-ingles.png) | Calendario en inglés. La semana empieza en domingo y las horas van en formato de 12 h | `/dashboard/automation` |
| [`16-resumen-tema-claro.png`](16-resumen-tema-claro.png) | Resumen en **tema claro**; las capturas 01 a 15 están en tema oscuro | `/dashboard` |
| [`17-calendario-mes-tema-claro.png`](17-calendario-mes-tema-claro.png) | Calendario, vista Mes, en tema claro | `/dashboard/automation` |

### Consultas por intervalo registradas

Peticiones que hizo el navegador a la API durante las capturas 02 a 06, leídas del registro de red
de DevTools. Cada vista pide solo su intervalo, con `desde` y `hasta` en RFC 3339 con offset, a los
dos proveedores:

```
Semana:  GET /calendario/eventos-google?desde=2026-10-19T00:00:00-03:00&hasta=2026-10-26T00:00:00-03:00   200
         GET /calendario/eventos-outlook?desde=2026-10-19T00:00:00-03:00&hasta=2026-10-26T00:00:00-03:00  200
Octubre: GET /calendario/eventos-google?desde=2026-09-28T00:00:00-03:00&hasta=2026-11-09T00:00:00-03:00   200
         GET /calendario/eventos-outlook?desde=2026-09-28T00:00:00-03:00&hasta=2026-11-09T00:00:00-03:00  200
Noviembre: GET /calendario/eventos-google?desde=2026-10-26T00:00:00-03:00&hasta=2026-12-07T00:00:00-03:00 200
           GET /calendario/eventos-outlook?desde=2026-10-26T00:00:00-03:00&hasta=2026-12-07T00:00:00-03:00 200
```

## Capturas previas que se citan, sin copiarlas

Las tomó DG en la demostración de S5.4 (2026-10-16), también con proveedores simulados. Están en
[`specs/reports/S5.4-evidencia/`](../../../../specs/reports/S5.4-evidencia/) y completan lo que aquí
no quedó:

- `01-personas-pdl-recuperado-plan-b-oscuro.jpg` y `02-personas-pdl-informe-fallido-con-perfiles-oscuro.jpg`:
  Personas con resultado parcial (perfiles antes del informe, plan B e informe fallido).
- `07-personas-cancelada-oscuro.jpg` y `11-personas-corte-de-conexion-claro.jpg`: cancelación y
  corte de conexión.
- `09-personas-movil-claro-armazon-existente.jpg`: vista a 375 px con el armazón anterior.

## Lo que no se pudo mostrar o hay que leer con cuidado

- **Sin OAuth real.** La conexión con Google y Outlook no se hizo con cuentas reales. Las
  integraciones se insertaron en la base con un token ficticio. Por eso el bloque «Calendarios» del
  resumen sale sin botones: el estado de conexión se ve en el calendario («Google ✓ Outlook ✓»).
- **No hay captura a 375 px.** En `main` el armazón del dashboard todavía no se adapta al móvil. La
  corrección está en el PR #22 (BUG-2026-10-19-03), sin mezclar. Una captura móvil solo repetiría
  el defecto conocido; está documentado en la captura 09 de S5.4.
- **Personas en curso.** Con los proveedores simulados, la investigación de Personas terminó antes
  de poder fotografiar un estado intermedio limpio. La captura 11 muestra el resultado final con
  todas las etapas. El estado parcial de Personas está en las capturas 01 y 02 de S5.4.
- **La primera reunión generada quedó en el pasado.** «Kick-off con Andina Logística Ficticia» era
  a las 17:00 del 19 de octubre. Cuando se tomó la captura 10 ya había pasado, así que salió de los
  «próximos 7 días». Por eso el total de reuniones baja de 6 a 4 entre las capturas 01 y 10.
- **Botón «N» abajo a la izquierda.** Es el indicador de Next.js Dev Tools que pinta `next dev`. No
  forma parte de la aplicación y no aparece en un build de producción.
- **Defectos conocidos que aparecen en la demo**, todos sin mezclar al tomar las capturas:
  - El detalle de la reunión dice «No se detecta contacto en la descripción» aunque esta use
    «Contacto 1:» (capturas 07 a 09). Lo corrige el PR #21 (BUG-2026-10-19-04).
  - En las reuniones con varios asistentes, PDL se consultó para el segundo asistente con el correo
    del primero. Beto Ficticio y Félix Simulado recibieron el perfil de Ana Prueba y de Diego
    Ejemplo. El contenido de esos dossiers no aparece en ninguna captura; se comprobó en la base de
    prueba. Lo corrige el PR #17 (BUG-2026-10-19-02).
- **Observado, sin investigar.** El aviso flotante de la generación rotula la reunión con otra hora
  («19/10/2026 20:00» para una reunión de las 17:00 en Santiago). Parece la hora en UTC.
- **Artefacto del simulador, no de la aplicación.** El dossier «Elena Muestra», que solo aparece
  por su nombre en «Actividad reciente» (capturas 14 y 16), recibió un informe simulado de otra
  persona. La causa fue un error del lanzador, que se corrigió antes de la captura 11.
