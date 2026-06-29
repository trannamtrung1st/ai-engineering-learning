# We Check — Design Tokens

CSS design token specification for **We Check** — **Campus Pulse v2** visual identity. Tokens are the single source of visual truth for Tailwind theme extension and component styling.

**Related documents:** [Design system basics](./03-design-system-basics.md) · [Design overview §5 Campus Pulse](./01-design-overview.md) · [UI framework](./02-ui-framework-tech-stack.md) · [Production quality bar](./00-production-ui-quality-bar.md) · [Frontend design skill](../../ai-harness/skills/frontend-design/SKILL.md)

---

## 1. Token

Design tokens are implemented as **CSS custom properties** on `:root` in `apps/web/src/styles/tokens.css`, imported by `globals.css`. Tailwind `theme.extend` maps utility classes to these variables so components reference semantics, not raw hex values.

---

## 2. Implementation File Structure

```
apps/web/src/styles/
  tokens.css      # :root variable definitions
  globals.css     # base resets, font imports, imports tokens.css
tailwind.config.ts  # maps colors, spacing, radius, shadow to var()
```

**Rule:** No hard-coded `#RRGGBB` in `components/` except inside `tokens.css`.

---

## 3. Color Tokens

### 3.1 Brand indigo (identity)

| Token | Value | Tailwind key | Use |
| --- | --- | --- | --- |
| `--color-brand-50` | `#eef2ff` | `brand-50` | Subtle brand wash |
| `--color-brand-100` | `#e0e7ff` | `brand-100` | Auth panel tint |
| `--color-brand-500` | `#4f6b9a` | `brand-500` | Secondary brand accent |
| `--color-brand-700` | `#1b2a4a` | `brand-700` | Nav stripe, auth panel, display headings |
| `--color-brand-900` | `#0f1729` | `brand-900` | Deep brand text on light surfaces |

### 3.2 Action primary (CTAs)

| Token | Value | Tailwind key |
| --- | --- | --- |
| `--color-primary-50` | `#eff6ff` | `primary-50` |
| `--color-primary-100` | `#dbeafe` | `primary-100` |
| `--color-primary-500` | `#3b82f6` | `primary-500` |
| `--color-primary-600` | `#2563eb` | `primary-600` |
| `--color-primary-700` | `#1d4ed8` | `primary-700` |
| `--color-primary-foreground` | `#ffffff` | `primary-foreground` |

Primary actions: “Điểm danh”, “Mở buổi học”, “Lưu”. Distinct from brand indigo — action blue for interactive emphasis.

### 3.3 Surfaces and text

| Token | Value | Use |
| --- | --- | --- |
| `--color-surface-default` | `#f4f1ec` | Warm stone page background |
| `--color-surface-raised` | `#ffffff` | Cards, modals, elevated panels |
| `--color-surface-muted` | `#ebe6df` | Secondary sections, table zebra |
| `--color-surface-inverse` | `#0f172a` | QR presentation background |
| `--color-text-primary` | `#1b2a4a` | Body text (brand-tinted) |
| `--color-text-secondary` | `#5c667a` | Captions, hints |
| `--color-text-inverse` | `#ffffff` | Text on inverse/brand surfaces |
| `--color-text-disabled` | `#94a3b8` | Disabled controls |
| `--color-border-default` | `#e2ddd4` | Dividers, inputs (warm neutral) |
| `--color-border-strong` | `#c9c2b8` | Table headers, emphasis borders |

### 3.4 Semantic feedback

| Token | Value | Contrast on white | Use |
| --- | --- | --- | --- |
| `--color-success-500` | `#059669` | 4.5:1+ | `Present`, success toast, outcome icon |
| `--color-success-50` | `#ecfdf5` | — | Success outcome wash |
| `--color-warning-500` | `#d97706` | 4.5:1+ | `Pending`, countdown warning |
| `--color-warning-50` | `#fffbeb` | — | Warning outcome wash |
| `--color-danger-500` | `#dc2626` | 4.5:1+ | `Absent`, errors |
| `--color-danger-50` | `#fef2f2` | — | Error outcome wash |
| `--color-info-500` | `#0284c7` | 4.5:1+ | `Excused`, info tips |
| `--color-info-50` | `#f0f9ff` | — | Info alert background |

### 3.5 QR presentation mode

Unchanged — max contrast for projection ([NFR-20](../brds/07-non-functional-risk.md)):

| Token | Value | Notes |
| --- | --- | --- |
| `--color-qr-bg` | `#000000` | Full-screen QR background |
| `--color-qr-fg` | `#ffffff` | QR modules (inverted generation) |
| `--color-qr-countdown` | `#ffffff` | Timer text on black |
| `--color-qr-accent` | `#22c55e` | > 10 s remaining |
| `--color-qr-warning` | `#facc15` | ≤ 10 s remaining |

### 3.6 Focus ring

| Token | Value |
| --- | --- |
| `--focus-ring-color` | `#3b82f6` |
| `--focus-ring-width` | `2px` |
| `--focus-ring-offset` | `2px` |

---

## 4. Typography Tokens

| Token | Value |
| --- | --- |
| `--font-display` | `"Plus Jakarta Sans", system-ui, -apple-system, sans-serif` |
| `--font-sans` | `"Be Vietnam Pro", system-ui, -apple-system, "Segoe UI", sans-serif` |
| `--font-mono` | `ui-monospace, "Cascadia Code", "Segoe UI Mono", monospace` |
| `--text-display-size` | `1.75rem` |
| `--text-display-line` | `2.25rem` |
| `--text-h1-size` | `1.5rem` |
| `--text-h1-line` | `2rem` |
| `--text-h2-size` | `1.25rem` |
| `--text-h2-line` | `1.75rem` |
| `--text-body-size` | `1rem` |
| `--text-body-line` | `1.5rem` |
| `--text-small-size` | `0.875rem` |
| `--text-small-line` | `1.25rem` |
| `--font-weight-normal` | `400` |
| `--font-weight-medium` | `500` |
| `--font-weight-semibold` | `600` |
| `--font-weight-bold` | `700` |

**Usage:** Apply `font-display` (Tailwind utility or `font-family: var(--font-display)`) to h1, h2, display, outcome headlines, stat card numbers. Body and labels use `font-sans`.

---

## 5. Spacing Tokens

| Token | Value |
| --- | --- |
| `--space-0` | `0` |
| `--space-1` | `0.25rem` |
| `--space-2` | `0.5rem` |
| `--space-3` | `0.75rem` |
| `--space-4` | `1rem` |
| `--space-5` | `1.25rem` |
| `--space-6` | `1.5rem` |
| `--space-8` | `2rem` |
| `--space-10` | `2.5rem` |
| `--space-12` | `3rem` |

Tailwind spacing scale aliases `1` → `--space-1`, etc.

---

## 6. Radius Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--radius-sm` | `0.375rem` (6 px) | Inputs, small chips |
| `--radius-md` | `0.625rem` (10 px) | Cards, buttons |
| `--radius-lg` | `0.875rem` (14 px) | Modals, outcome panels |
| `--radius-full` | `9999px` | Avatars, pills, nav active indicator |

---

## 7. Shadow Tokens

| Token | Value |
| --- | --- |
| `--shadow-sm` | `0 1px 3px 0 rgb(27 42 74 / 0.06), 0 1px 2px -1px rgb(27 42 74 / 0.06)` |
| `--shadow-md` | `0 4px 12px -2px rgb(27 42 74 / 0.08), 0 2px 6px -2px rgb(27 42 74 / 0.05)` |
| `--shadow-lg` | `0 12px 24px -4px rgb(27 42 74 / 0.12), 0 4px 8px -4px rgb(27 42 74 / 0.06)` |
| `--shadow-brand` | `0 8px 24px -4px rgb(27 42 74 / 0.2)` |

Shadows use brand-tinted rgba for warmth — not pure black.

---

## 8. Z-Index Tokens

| Token | Value | Layer |
| --- | --- | --- |
| `--z-dropdown` | `50` | Menus |
| `--z-sticky` | `100` | Sticky table header |
| `--z-modal` | `200` | Dialogs |
| `--z-toast` | `300` | Toasts |
| `--z-qr-overlay` | `150` | Scanner viewfinder overlay |

---

## 9. Size Tokens (Touch Targets)

| Token | Value | Use |
| --- | --- | --- |
| `--size-touch-min` | `44px` | Minimum tap target ([00-production-ui-quality-bar.md](./00-production-ui-quality-bar.md)) |
| `--size-icon-sm` | `20px` | Inline icons |
| `--size-icon-md` | `24px` | Button icons, outcome panel icons |
| `--size-icon-lg` | `32px` | Outcome panel hero icon |
| `--size-qr-min` | `min(80vw, 400px)` | Student scan frame |
| `--size-qr-projector` | `min(60vh, 60vw)` | Instructor display |

---

## 10. Motion Tokens

| Token | Value |
| --- | --- |
| `--duration-fast` | `100ms` |
| `--duration-normal` | `200ms` |
| `--duration-slow` | `400ms` |
| `--ease-default` | `cubic-bezier(0.4, 0, 0.2, 1)` |
| `--ease-out` | `cubic-bezier(0, 0, 0.2, 1)` |
| `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` |

---

## 11. Example `:root` Block

```css
:root {
  --color-brand-700: #1b2a4a;
  --color-primary-500: #3b82f6;
  --color-primary-600: #2563eb;
  --color-primary-foreground: #ffffff;
  --color-surface-default: #f4f1ec;
  --color-surface-raised: #ffffff;
  --color-text-primary: #1b2a4a;
  --color-success-500: #059669;
  --color-success-50: #ecfdf5;
  --color-danger-500: #dc2626;
  --font-display: "Plus Jakarta Sans", system-ui, sans-serif;
  --font-sans: "Be Vietnam Pro", system-ui, sans-serif;
  --radius-md: 0.625rem;
  --space-4: 1rem;
  --focus-ring-color: #3b82f6;
  --size-touch-min: 44px;
  --shadow-md: 0 4px 12px -2px rgb(27 42 74 / 0.08);
}
```

Full set includes all rows in sections 3–10. Implement in `web-visual-refresh-v2` slice.

---

## 12. Attendance Status Token Mapping

| `AttendanceStatus` | Background | Text | Border |
| --- | --- | --- | --- |
| `Pending` | `--color-warning-50` | `--color-warning-500` | `--color-warning-500` |
| `Present` | `--color-success-50` | `--color-success-500` | `--color-success-500` |
| `Absent` | `--color-danger-50` | `--color-danger-500` | `--color-danger-500` |
| `Excused` | `--color-info-50` | `--color-info-500` | `--color-info-500` |
| `Rejected` | `--color-danger-50` | `--color-danger-500` | `--color-danger-500` |

Used by `StatusBadge` component ([05-common-ui-components.md](./05-common-ui-components.md)).

---

## 13. Check-In Outcome Token Mapping

| Outcome | Wash | Icon color | Icon (Lucide) |
| --- | --- | --- | --- |
| `Success` | `--color-success-50` | `--color-success-500` | `CheckCircle2` |
| `ExpiredQr` | `--color-warning-50` | `--color-warning-500` | `Clock` |
| `OutOfRadius` | `--color-warning-50` | `--color-warning-500` | `MapPinOff` |
| `DuplicateCheckIn` | `--color-info-50` | `--color-info-500` | `History` |
| `GpsDisabled` | `--color-danger-50` | `--color-danger-500` | `LocateOff` |
| `SpoofSuspected` | `--color-danger-50` | `--color-danger-500` | `ShieldAlert` |
| `SessionNotActive` | `--color-warning-50` | `--color-warning-500` | `CalendarX` |

Spec: [07-event-specific-components.md](./07-event-specific-components.md) §2.5.

---

## 14. Future Consideration

- Export tokens to JSON for Figma Tokens plugin.
- Dark mode overrides under `[data-theme="dark"]`.
- High-contrast institution theme preset for accessibility audits.
- Self-hosted font files for offline campus networks.
