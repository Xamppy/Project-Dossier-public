# 0008 · Indicadores de Resumen: «Créditos para preparar» en lugar de puntualidad histórica

- **Fecha:** 2026-10-04 (reemplaza la versión del 2026-10-03, nunca integrada en `main`)
- **Estado:** aceptada por el usuario; pendiente de la revisión del segundo integrante
- **Decide:** usuario (enmienda de alcance) · implementa DG (agente)
- **Tarea:** UX-KPI-01

## Contexto

La primera implementación de UX-KPI-01 tenía como tercera tarjeta «Reuniones preparadas a
tiempo»: el porcentaje de reuniones de los últimos 30 días cuyos dossiers el usuario pidió a mano
y terminaron antes del inicio. Para sostenerla hacía falta una tabla de hechos que sobreviviera a
la retención de dossiers, una migración con relleno, el registro de cada generación y una regla de
«historial parcial» para lo ya purgado.

Al verlo funcionando, el usuario observó que esa tarjeta no seguía la línea de las demás: tres
miran lo que viene (próximos 7 días y saldo actual) y una miraba hacia atrás, con otro periodo,
otro ámbito (solo manual) y un aviso de historial parcial durante el primer mes.

## Decisión

La tercera tarjeta es **«Créditos para preparar»**: la suma, sobre las reuniones elegibles de los
próximos 7 días que no están preparadas, del costo de cada dossier esperado que falta.

- Costo por rol con las reglas actuales: empresa = créditos de la profundidad por defecto del plan
  (la que usa la generación desde calendario); persona = créditos del módulo de identidad.
- Solo cuenta lo que falta: lo ya generado (completo, vigente y propio) no se cobra de nuevo; un
  fallido sí. Un conjunto esperado vacío no suma.
- Es un máximo: un resultado recuperado de caché puede costar menos. El texto accesible lo dice.
- `billing`: `charged`, `unlimited` (Enterprise, sin bloqueo por saldo) o `disabled`
  (`DOSSIER_CHARGE_CREDITS=0`). Sin cobro el estimado es 0 y la tarjeta explica por qué.
- `exceeds_balance` se calcula con el saldo de cada consulta, fuera de la caché, y la tarjeta lo
  resalta en color de advertencia.

Se **retira la evidencia histórica** (tablas `dossier_generation_facts` y `prep_evidence_meta`,
migración `c5a9e3b7d1f2`, relleno, registro en `persist_calendar_dossiers`, enlace del job manual con
el evento interno, marca de borrado y purga): solo existía para el indicador reemplazado.

## Alternativas consideradas

- **Mantener «Preparadas a tiempo».** Descartada por el usuario: incoherente con el resto.
- **«Próxima reunión sin preparar»** (tiempo hasta la próxima pendiente). Comunica urgencia, pero
  repite lo que ya muestra la sección de calendario de Resumen.
- **Conservar la evidencia sin mostrarla.** Descartada: costo de esquema y mantenimiento sin uso.

## Consecuencias

- Sin cambios de esquema: UX-KPI-01 ya no toca `models.py`, `schema_patches.py`, `Migracion.md` ni
  Alembic. La generación, la automatización y el borrado vuelven a su comportamiento previo, salvo
  la invalidación de la caché del resumen.
- Las cuatro tarjetas comparten periodo, reuniones y estados; un fallo de calendario deja las tres
  primeras en guion con causa y el saldo visible.
- Si en el futuro se quiere medir puntualidad, habrá que retomar el diseño de evidencia: la
  versión retirada está en el historial de la rama (`0871e80`, `99c328c`).
