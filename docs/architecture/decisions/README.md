# Decisiones técnicas

Una decisión por archivo, numerada: `0001-titulo-corto.md`.

Aquí va toda decisión que **un agente futuro podría revertir por desconocimiento**. Si algo se
decidió en una conversación y no está escrito aquí, para el proyecto no existe: la próxima
sesión lo hará distinto y nadie sabrá por qué.

No hace falta registrar decisiones triviales o reversibles en cinco minutos. Sí: elección de
proveedor, cambio de contrato, protocolo, formato de datos, y todo lo que ate al proyecto a algo
externo.

## Plantilla

```markdown
# NNNN · Título en una línea

- **Fecha:** AAAA-MM-DD
- **Estado:** propuesta | aceptada | reemplazada por NNNN
- **Decide:** FO | DG | FD | equipo
- **Tarea:** SN.N

## Contexto

Qué problema obliga a decidir. Qué restricciones existen.

## Alternativas evaluadas

| Opción | A favor | En contra |
|---|---|---|
| A | | |
| B | | |

Con datos cuando los haya: costo, cobertura, límites, resultados de prueba.

## Decisión

Qué se eligió y por qué.

## Consecuencias

Qué queda atado a esta decisión. Qué habría que rehacer si se revierte. Qué queda fuera de
alcance por haberla tomado.
```

## Decisiones obligatorias del Sprint 0

Sin estas seis escritas, **el Sprint 0 no está cerrado**:

| Archivo previsto | Tarea | Qué decide |
|---|---|---|
| `0001-linea-llm-canonica.md` | S0.4 | DeepSeek, shim de Gemini u OpenAI. Qué módulos se retiran |
| `0002-modelo-de-lenguaje.md` | S0.5 | DeepSeek vs GPT-4o vs GPT-5.6 Luna. Con costo por dossier y tasa de conformidad JSON |
| `0003-fuente-registros-europeos.md` | S0.6 | Proveedor, países cubiertos, costo, licencia |
| `0004-proveedor-noticias.md` | S0.7 | Proveedor, límites, costo |
| `0005-proveedor-correo.md` | S0.8 | Proveedor, y qué se hace con el diseño previo de `Migracion.md` |
| `0006-protocolo-estados-progresivos.md` | S0.11 | SSE o WebSocket. Contrato de eventos y comportamiento ante reconexión |

## Índice

1. [0001 · Línea de implementación LLM canónica](0001-linea-llm-canonica.md) (S0.4)
2. [0002 · Modelo de lenguaje para síntesis ejecutiva](0002-modelo-de-lenguaje.md) (S0.5)
3. [0003 · Fuente de registros corporativos europeos](0003-fuente-registros-europeos.md) (S0.6)
4. [0004 · Proveedor de búsqueda de noticias](0004-proveedor-noticias.md) (S0.7)
5. [0005 · Proveedor de correo transaccional y entrega de dossiers](0005-proveedor-correo.md) (S0.8)
6. [0006 · Protocolo de estados progresivos (SSE vs WebSockets)](0006-protocolo-estados-progresivos.md) (S0.11)
