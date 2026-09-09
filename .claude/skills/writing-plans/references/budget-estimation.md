# Budget Estimation Reference

## Chilean Freelance Dev Rate Card (2026)

| Role | Rate (USD/hr) | Rate (CLP/hr) | Notes |
|------|-------------|---------------|-------|
| Junior dev | $12-18 | $12-18k | Simple tasks |
| Mid dev | $18-25 | $18-25k | Standard development |
| Senior dev | $25-40 | $25-40k | Complex/architecture |

## Budget Calculation Formula

```
base_hours × blended_rate = subtotal_dev
subtotal_dev + hosting + gestion = subtotal
descuento = subtotal × 0.10
iva_base = (subtotal - descuento) × 0.19
NETO = subtotal - descuento + iva_base
```

### Simplified (neto given)
```
subtotal = neto / 0.90 / 1.19
```

## Baseline Anchoring (KEY RULE)

**Every estimate starts from a demonstrated baseline, never from theory.**

```
baseline_rate = baseline_cost / baseline_time
new_estimate = baseline_rate × new_time
```

Example from MotoForAll:
- Baseline: $500k / 3 weeks = $167k/week
- New scope: ~30% larger, same velocity → $167k × 4 weeks = $668k
- Final with margins: $700k CLP

## Scope Increase vs Cost Increase Table

| Scope increase | Cost increase | Reason |
|---------------|-------------|--------|
| 30% | ≤40% | Proportional with velocity |
| 50% | 50-60% | Linear-ish |
| 100% (2x) | 120-150% | More coordination overhead |
| 300-400% (5x) | 200-300% | Breaking point — scope should be split |

## When Reuse Exists

**Rule: If ≥70% of code can be reused from a proven repo, divide estimate by 3-4.**

MotoForAll case:
- POS terminal from minimarket-almacen: 70% reusable → 1.5 weeks → 0.5 weeks
- Fiados system: 90% reusable → 1 week → 0.3 weeks

## Planilla Format (CLP)

Units in table = thousands of CLP:
- $15 = $15,000 CLP
- $120 = $120,000 CLP
- $1,562 = $1,562,000 CLP

Rates:
- Análisis y diseño: $15k/hr
- Desarrollo Backend: $20k/hr  
- Desarrollo Frontend: $18k/hr
- Testing: $15k/hr
- Deploy: $18k/hr
- Hosting: $250k (flat)
- Gestión: $300k (flat)
- Discount: 10%
- IVA: 19%
