---
name: web-design-best-practices
description: "Web design best practices: dark theme, shadcn/ui, Tailwind v4, responsive, accessibility (WCAG), performance."
version: 1.0.0
author: Felipe Orellana
license: MIT
metadata:
  hermes:
    tags: [design, dark-theme, tailwind, shadcn, accessibility, WCAG, responsive, UX]
    projects: [motoforall]
---

# Web Design Best Practices

## Dark Theme (MotoForAll style)

### Colores:
```css
/* Base */
--background: #0A0A0B;
--foreground: #FAFAFA;

/* Primary (azul) */
--primary: #2563EB;
--primary-foreground: #FFFFFF;

/* Accent (naranja) */
--accent: #EA580C;
--accent-foreground: #FFFFFF;

/* Card */
--card: #111113;
--card-foreground: #FAFAFA;

/* Border */
--border: #27272A;
--input: #27272A;
--ring: #2563EB;

/* Muted */
--muted: #18181B;
--muted-foreground: #71717A;
```

### Dark theme rules:
- Fondo `#0A0A0B` o más oscuro, NO puro negro
- Texto `#FAFAFA` para máxima legibilidad
- Bordes sutiles `#27272A`
- Sombras suaves en vez de bordes para elevación
- Evitar blanco puro `#FFFFFF` en texto largo

## Tailwind CSS v4

### Configuración del tema:
```css
@theme {
  --color-primary: #2563EB;
  --color-accent: #EA580C;
  --color-background: #0A0A0B;
  --color-foreground: #FAFAFA;
  --radius-lg: 0.5rem;
  --radius-md: 0.375rem;
  --radius-sm: 0.25rem;
}
```

### Pattern responsive:
```tsx
// Mobile first
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
// xs: 1 col, md: 2 cols, lg: 4 cols
```

### Clases útiles:
```
text-primary, bg-primary, border-primary
text-accent, bg-accent
rounded-lg, rounded-md, rounded-sm
gap-4, gap-6, gap-8
p-4, p-6, p-8
space-y-4, space-y-6
```

## shadcn/ui + base-ui (NO Radix)

### Problema: asChild NO funciona igual

```tsx
// ❌ BAD - crash por hydration
<Button asChild><Link href="...">Texto</Link></Button>

// ✅ GOOD - usar elementos nativos
<DropdownMenuTrigger className="p-2 rounded hover:bg-zinc-800">
  <Icon />
</DropdownMenuTrigger>

// ✅ GOOD - Link envuelve contenido
<DropdownMenuItem><Link href="...">Texto</Link></DropdownMenuItem>
```

### Select onValueChange:
```tsx
// ❌ BAD
onValueChange={setValue}

// ✅ GOOD
onValueChange={(v) => setValue(v || "")}
```

### Componentes base-ui disponibles:
- Dialog, DialogContent, DialogHeader, DialogTitle
- Sheet, SheetContent, SheetHeader
- DropdownMenu, DropdownMenuTrigger, DropdownMenuContent
- Select, SelectTrigger, SelectContent, SelectItem
- Accordion (si instalado)

## Accesibilidad (WCAG 2.1 AA)

### Reglas obligatorias:

1. **Contraste mínimo 4.5:1** para texto normal
   - `#71717A` sobre `#0A0A0B` = 7.6:1 ✓
   - `#52525B` sobre `#0A0A0B` = 4.8:1 ✓

2. **Focus visible** siempre:
   ```css
   :focus-visible {
     outline: 2px solid var(--ring);
     outline-offset: 2px;
   }
   ```

3. **Alt text** en imágenes:
   ```tsx
   <img alt="Cubierta Dunlop GT601 120/70-17 para moto" />
   ```

4. **ARIA labels** donde no hay texto visible:
   ```tsx
   <button aria-label="Cerrar carrito">
     <XIcon />
   </button>
   ```

5. **Skip to main content**:
   ```tsx
   <a href="#main-content" className="sr-only focus:not-sr-only">
     Saltar al contenido principal
   </a>
   ```

6. **Keyboard navigation**:
   - Tab = siguiente elemento
   - Shift+Tab = elemento anterior
   - Enter = activar
   - Escape = cerrar modal/dropdown

### Chequeo rápido:
```
- ¿Puedes navegar toda la página solo con Tab?
- ¿Los modales se cierran con Escape?
- ¿Los dropdowns se cierran al hacer click afuera?
- ¿Las imágenes tienen alt descriptivo?
- ¿Los formularios tienen labels asociados?
```

## Responsive Breakpoints

```css
/* Mobile: 0-639px */
/* Tablet: 640-1023px */
/* Desktop: 1024-1279px */
/* Wide: 1280px+ */
```

### Sidebar/Layout Overflow — Pitfall

**Problema:** Sidebar con `position: fixed` + `min-h-screen` o `height: 100vh` se corta en notebooks (1366x768) porque la barra de título del navegador reduce el viewport disponible. El contenido principal scrollea pero el sidebar queda flotando con fondo blanco debajo.

**Aplica a:** cualquier proyecto React/Vue con sidebar fijo — NO es exclusivo de Next.js.

**Solución — sidebar scrollable internamente:**

```jsx
// ❌ BAD — se corta en low-res
<nav className="fixed inset-y-0 min-h-screen overflow-y-auto">

// ✅ GOOD — se adapta a barras móviles y scrollea si excede viewport
<nav
  style={{ height: '100dvh' }}
  className="fixed inset-y-0 overflow-y-auto"
>
```

**Claves:**
- `100dvh` = dynamic viewport height (descarta la barra de direcciones en móviles)
- `overflow-y-auto` = scrolleo interno solo cuando el contenido excede la altura
- `position: fixed` se mantiene para que el sidebar quede anclado visualmente
- Funciona con `flex` wrapper en desktop: `flex h-screen > flex-1 overflow-y-auto main`

**Bug real encontrado (Podoclinic, 2026-04):** El sidebar tenía `min-h-screen` y `position: fixed` — en 1366x768 los items inferiores quedaban detrás del viewport. Fix: `style={{ height: '100dvh' }}` + `overflow-y-auto`.

**Si el sidebar tiene `position: sticky`**, usar `max-height: 100vh` en vez de `height: 100dvh`:

```css
.sidebar-sticky {
  position: sticky;
  top: 0;
  max-height: 100vh;
  overflow-y: auto;
}
```

.grid-cols-1         /* mobile */
.md\:grid-cols-2     /* tablet+ */
.lg\:grid-cols-4     /* desktop+ */
```

### Patrones comunes:
```
Mobile: stack vertical, full width, font-size 14-16px
Tablet: 2 columnas, padding 24-32px
Desktop: 4+ columnas, max-width 1280px centrado
```

## Marquee Component (CSS @keyframes, no `<marquee>` tag)

Patrón para crear un auto-scrolling horizontal strip usando CSS animations, NUNCA el tag `<marquee>` (obsoleto y no accesible).

### Técnica base:

```css
@keyframes marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}

.marquee-track {
  display: flex;
  width: max-content;
  animation: marquee 25s linear infinite;
}

.marquee-track:hover {
  animation-play-state: paused;
  /* O ralentizar con WAAPI: track.getAnimations()[0].playbackRate = 0.416 */
}

@media (prefers-reduced-motion: reduce) {
  .marquee-track {
    animation: none;
  }
}
```

### Requisitos técnicos:

1. **Contenido duplicado exactamente una vez** — el track debe tener el contenido original + copia idéntica para que el loop sea perfecto
2. **Máscaras de borde** para desvanecer los extremos:
   ```css
   .marquee-container {
     mask-image: linear-gradient(to right, transparent, black 5%, black 95%, transparent);
     -webkit-mask-image: linear-gradient(to right, transparent, black 5%, black 95%, transparent);
   }
   ```
3. **Pausa al hover**: `animation-play-state: paused` (o ralentizar con WAAPI `playbackRate`)
4. **Fallback prefers-reduced-motion**: detener animación
5. **NO** usar `<marquee>` tag
6. **NO** animar `left`/`width` (solo `transform: translateX`)

### Variante inclinada (skew):

Para efecto cinético, inclinar SOLO el contenido interno, no el contenedor (para que las máscaras sigan rectas):

```tsx
<div className="marquee-container"> {/* mask aplicada aquí */}
  <div className="marquee-track" style={{ transform: 'skewY(-3deg)' }}>
    {content}
    {content /* duplicado exacto */}
  </div>
</div>
```

### React component pattern:

```tsx
'use client'
export function Marquee({ items }: { items: { text: string; icon?: LucideIcon; highlight?: boolean }[] }) {
  const trackRef = useRef<HTMLDivElement>(null);
  
  const handleMouseEnter = () => {
    if (trackRef.current) {
      const animations = trackRef.current.getAnimations();
      for (const anim of animations) anim.playbackRate = 0.416; // ralentizar 2.4x
    }
  };

  const content = items.map((item, i) => (
    <span key={i} className={item.highlight ? 'text-primary' : ''}>
      {item.icon && <item.icon className="inline size-5" />}
      {item.text}
      <span className="mx-4 text-primary">•</span>
    </span>
  ));

  return (
    <div className="marquee-container [mask-image:linear-gradient(to_right,transparent,black_5%,black_95%,transparent)]">
      <div ref={trackRef} className="flex w-max animate-marquee" onMouseEnter={handleMouseEnter}>
        {content}{content}
      </div>
    </div>
  );
}
```

### Anti-patrones:
- ❌ `<marquee>` tag (obsoleto)
- ❌ `left`/`width` animation (main thread, jank)
- ❌ Duplicar contenido más de una vez
- ❌ No ignorar prefers-reduced-motion

### Imágenes:
```tsx
// Siempre especificar dimensions
<img width={400} height={300} />

// Usar next/image para optimización
import Image from 'next/image';

// WebP cuando sea posible
// Lazy loading para below-the-fold
<img loading="lazy" />
```

### Fuentes:
```tsx
// Solo lo que usas
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" />
```

### CSS:
- Tailwind = atomic, zero runtime
- Evitar CSS custom masivo
- Usar variables CSS para theming

### JS:
```tsx
// Client components solo cuando necesario
"use client"  // solo si hay estado/interacciones

// Dynamic import para heavy components
const HeavyComponent = dynamic(() => import('./Heavy'))
```

## UX Patterns Chile

### Checkout Chileno:
- RUT como identificador principal
- Región/Comuna en vez de Estado/Ciudad
- Teléfono: +56 9 XXXX XXXX
- Email con validación estricta

### Formato dinero:
```tsx
// CLP sin decimales
new Intl.NumberFormat('es-CL', {
  style: 'currency',
  currency: 'CLP',
  minimumFractionDigits: 0
}).format(45000)
// "$45.000"
```

### Formato fecha:
```tsx
new Intl.DateTimeFormat('es-CL', {
  year: 'numeric',
  month: 'long',
  day: 'numeric'
}).format(new Date())
// "29 de abril de 2026"
```
