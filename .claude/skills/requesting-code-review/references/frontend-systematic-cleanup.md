# Frontend Systematic Cleanup Reference

Batch-scan and fix common code quality issues across the entire `frontend/src` tree.
Run these probes before committing frontend changes, or when starting a cleanup sprint.

## 1. Find All `alert()` — Zero Tolerance

```bash
grep -rn "alert\(" --include="*.tsx" --include="*.jsx" ./frontend/src
```

**Rule:** Replace with `toast.success()` or `toast.error()` from `react-hot-toast`.
Every file that uses toast must have: `import toast from 'react-hot-toast';` or `import { toast } from 'react-hot-toast';`

## 2. Find Debug `console.log` in Pages/Components

```bash
grep -rn "console\.log\|console\.warn\|console\.error" --include="*.tsx" --include="*.jsx" ./frontend/src
```

**Strategy:**
- Page-level `console.log` → remove (debug noise in production)
- API-layer `console.error` that logs `error.response.data`, headers, or full error objects → **remove**, data-leaking
- API-layer `console.error` with only `error.message` → **acceptable** (useful for prod debugging)
- `console.warn` gated behind dev flags (e.g. `if (enableDebug)`) → keep, off by default
- Never log: user data, tokens, RUTs, PII, `error.response.data`, HTTP headers

**Dangerous pattern found (Podoclinic, 2026-04):**
```javascript
// ❌ BAD — leaks full response data and headers
console.error('Error:', error);
console.error('Datos del error:', error.response.data);
console.error('Cabeceras:', error.response.headers);

// ✅ Acceptable — message only
console.error('Error en la petición:', error.message);
```

## 2b. Find Exposed Global Debug Functions

```bash
grep -rn "window\.\w\+\s*=" --include="*.tsx" --include="*.jsx" ./frontend/src
```

**Rule:** No `window.* = function` debug helpers in production code — anyone can call them from the browser console.

**Found (Podoclinic, 2026-04):**
```javascript
// ❌ BAD — anyone can call checkEndpoint() from browser console
window.checkEndpoint = checkEndpoint;

// ✅ Remove entirely — or gate behind process.env.NODE_ENV === 'development'
```

## 2c. Find Undefined Variable References in JSX

```bash
# Variables used as values in JSX but never defined — no runtime crash, wrong UI silently
grep -rn "canAccess" --include="*.tsx" --include="*.jsx" ./frontend/src
```

**Rule:** JSX silently treats undefined variables as strings (`undefined` → renders nothing). No runtime crash — only the wrong UI appears. Check that every variable referenced in JSX is actually destructured/defined in the component.

**Dangerous pattern (Podoclinic, 2026-04):** Component destructures `canAccessInventory` from a hook but uses `canAccessInventario` (typo) in JSX. The lock icon appears for ALL users regardless of plan because `canAccessInventario` is `undefined`.

Fix: grep `canAccess` in JSX and compare against hook destructures — catch typos.

## 3. Find Hardcoded `localhost`

```bash
grep -rn "localhost" --include="*.tsx" --include="*.jsx" ./frontend/src
```

**Rule:** Use dynamic `API_BASE`:
```javascript
const API_BASE = (window.location.origin.replace(/:\d+$/, '')) + (window.location.port ? ':8000' : '') + '/api';
```

## 4. Find Hardcoded Timezone Strings

```bash
grep -rn "America/Santiago\|America\/Buenos_Aires\|timezone" --include="*.tsx" --include="*.jsx" ./frontend/src
```

**Rule:** Use `Intl.DateTimeFormat().resolvedOptions().timeZone` with a sensible fallback:
```javascript
const TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Santiago';
```

## 5. Find Foreign Language Text / Regionalisms

```bash
grep -rn "的\|只知\|软件\|querés\|podés\|tenés" --include="*.tsx" --include="*.jsx" ./frontend/src
```

## 6. Batch Patch Pattern

When fixing across many files simultaneously:

1. Run the grep probe to get all affected files
2. Read all affected files in parallel (use `read_file` with `limit`/`offset` to avoid OOM)
3. Add imports first (toast), then replace calls — in parallel patches
4. Verify with the same grep probe (should return 0)

**Import convention:**
```javascript
// ✅ Default import (used in most files)
import toast from 'react-hot-toast';

// ✅ Named import (used in some files)
import { toast } from 'react-hot-toast';
```

**Toast patterns:**
```javascript
toast.success('Mensaje de éxito');
toast.error('Mensaje de error');
toast.loading('Procesando...', { icon: '⏳' });
toast.dismiss(id); // dismiss a specific toast
```
