# Planes de ejecución

Un plan de ejecución es el desglose de **una** tarea que resultó más grande de lo que su tarjeta
sugería. No todas las tareas necesitan uno.

```
active/       en curso
completed/    cerrados, se conservan como evidencia
```

## Cuándo escribir uno

- La tarea toca más de cinco archivos o cruza backend y frontend.
- Va a ocupar más de una sesión.
- Tiene un orden de pasos que, si se altera, rompe algo.
- Hay que coordinar a dos personas.

Si nada de eso aplica, la tarjeta de Trello y `feature_list.json` bastan. Un plan de ejecución
para una tarea de dos horas es burocracia.

Candidatas previsibles: **S1.1** (Alembic sobre un esquema existente), **S4.3** (migración del
contrato de `dossier_data`), **S5.1**–**S5.2** (sondeo a canal en tiempo real).

## Formato

`active/SN.N-titulo-corto.md`:

```markdown
# SN.N · Título

- **Responsable:** FO | DG | FD
- **Rama:** feat/SN.N-...
- **Estado:** en curso | pausado | completado

## Objetivo

Una frase. Qué debe ser cierto al terminar.

## Criterio de aceptación

El de la tarjeta, copiado literal. Si diverge, gana la tarjeta.

## Pasos

- [ ] 1. ...
- [ ] 2. ...

## Archivos que se tocan

Lista, para que otro sepa qué no tocar en paralelo.

## Riesgos

Qué puede salir mal y qué se hace si sale mal.

## Registro

Notas durante la ejecución: qué se descubrió, qué se descartó y por qué.
```

## Al terminar

1. Mueve el archivo a `completed/`
2. Marca los pasos cumplidos
3. Resume lo aprendido en la sección Registro
4. Lleva a `.harness/progress.md` solo lo que sirva a otra tarea

El plan completado es evidencia: sirve al informe final y a quien continúe el sistema después
del proyecto.
