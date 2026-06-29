# We Check — Design Tokens

CSS design token specification for **We Check**. Tokens are the single source of visual truth for Tailwind theme extension and component styling.

**Related documents:** [Design system basics](./03-design-system-basics.md) · [UI framework](./02-ui-framework-tech-stack.md) · [Production quality bar](./00-production-ui-quality-bar.md) · [12-backend-frontend-tech-stack.md](../technical/12-backend-frontend-tech-stack.md) §4.2

---

## 1. Token

Design tokens are implemented as **CSS custom properties** on `:root` in `apps/web/src/styles/tokens.css`, imported by `globals.css`. Tailwind `theme.extend` maps utility classes to these variables so components reference semantics, not raw hex values.

---

## 2. Implementation File Structure

```
apps/web/src/styles/
  tokens.css      # :root variable definitions
  globals.css     # base resets, imports tokens.css
tailwind.config.ts  # maps colors, spacing, radius, shadow to var()
```

**Rule:** No hard-coded `#RRGGBB` in `components/` except inside `tokens.css`.

---

## 3. Color Tokens

### 3.1 Brand and primary

| Token | Value | Tailwind key |
| --- | --- | --- |
| `--color-primary-50` | `#eff6ff` | `primary-50` |
| `--color-primary-100` | `#dbeafe` | `primary-100` |
| `--color-primary-500` | `#2563eb` | `primary-500` |
| `--color-primary-600` | `#1d4ed8` | `primary-600` |
| `--color-primary-700` | `#1e40af` | `primary-700` |
| `--color-primary-foreground` | `#ffffff` | `primary-foreground` |

Primary actions: buttons “Điểm danh”, “Mở buổi học”, “Lưu”.

### 3.2 Surfaces and text

| Token | Value | Use |
| --- | --- | --- |
| `--color-surface-default` | `#f8fafc` | Page background |
| `--color-surface-raised` | `#ffffff` | Cards, modals |
| `--color-surface-inverse` | `#0f172a` | QR presentation background |
| `--color-text-primary` | `#0f172a` | Body text |
| `--color-text-secondary` | `#475569` | Captions, hints |
| `--color-text-inverse` | `#ffffff` | Text on inverse surface |
| `--color-text-disabled` | `#94a3b8` | Disabled controls |
| `--color-border-default` | `#e2e8f0` | Dividers, inputs |
| `--color-border-strong` | `#cbd5e1` | Table headers |

### 3.3 Semantic feedback

| Token | Value | Contrast on white | Use |
| --- | --- | --- | --- |
| `--color-success-500` | `#16a34a` | 4.5:1+ | `Present`, success toast |
| `--color-success-50` | `#f0fdf4` | — | Success alert background |
| `--color-warning-500` | `#d97706` | 4.5:1+ | `Pending`, countdown warning |
| `--color-warning-50` | `#fffbeb` | — | Warning alert background |
| `--color-danger-500` | `#dc2626` | 4.5:1+ | `Absent`, errors |
| `--color-danger-50` | `#fef2f2` | — | Error alert background |
| `--color-info-500` | `#0284c7` | 4.5:1+ | `Excused`, info tips |
| `--color-info-50` | `#f0f9ff` | — | Info alert background |

### 3.4 QR presentation mode

| Token | Value | Notes |
| --- | --- | --- |
| `--color-qr-bg` | `#000000` | Full-screen QR background |
| `--color-qr-fg` | `#ffffff` | QR modules (inverted generation) |
| `--color-qr-countdown` | `#ffffff` | Timer text on black |
| `--color-qr-accent` | `#22c55e` | > 10 s remaining |
| `--color-qr-warning` | `#facc15` | ≤ 10 s remaining |

Meets [NFR-20](../brds/07-non-functional-risk.md) contrast for countdown on dark background.

### 3.5 Focus ring

| Token | Value |
| --- | --- |
| `--focus-ring-color` | `#2563eb` |
| `--focus-ring-width` | `2px` |
| `--focus-ring-offset` | `2px` |

---

## 4. Typography Tokens

| Token | Value |
| --- | --- |
| `--font-sans` | `system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif` |
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
| `--radius-sm` | `0.25rem` | Inputs, small chips |
| `--radius-md` | `0.5rem` | Cards, buttons |
| `--radius-lg` | `0.75rem` | Modals |
| `--radius-full` | `9999px` | Avatars, pills |

---

## 7. Shadow Tokens

| Token | Value |
| --- | --- |
| `--shadow-sm` | `0 1px 2px 0 rgb(0 0 0 / 0.05)` |
| `--shadow-md` | `0 4px 6px -1px rgb(0 0 0 / 0.1)` |
| `--shadow-lg` | `0 10px 15px -3px rgb(0 0 0 / 0.1)` |

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
| `--size-icon-md` | `24px` | Button icons |
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

---

## 11. Example `:root` Block

```css
:root {
  --color-primary-500: #2563eb;
  --color-primary-600: #1d4ed8;
  --color-primary-foreground: #ffffff;
  --color-surface-default: #f8fafc;
  --color-surface-raised: #ffffff;
  --color-text-primary: #0f172a;
  --color-success-500: #16a34a;
  --color-danger-500: #dc2626;
  --font-sans: system-ui, -apple-system, sans-serif;
  --radius-md: 0.5rem;
  --space-4: 1rem;
  --focus-ring-color: #2563eb;
  --size-touch-min: 44px;
}
```

Full set includes all rows in sections 3–10.

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

## 13. Future Consideration

- Export tokens to JSON for Figma Tokens plugin.
- Dark mode overrides under `[data-theme="dark"]`.
- High-contrast institution theme preset for accessibility audits.
- CSS `@property` for animating token-based transitions.
