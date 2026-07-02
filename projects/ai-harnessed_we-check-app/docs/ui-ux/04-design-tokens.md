# We Check — Design Tokens

CSS design token specification for **We Check** — **Notion workspace system** visual identity. Values are mapped from [DESIGN.md](./DESIGN.md) (vendored Notion spec). Tokens are the implementation layer for Tailwind theme extension and component styling.

**Related documents:** [DESIGN.md](./DESIGN.md) · [Design system basics](./03-design-system-basics.md) · [Design overview §5](./01-design-overview.md) · [UI framework](./02-ui-framework-tech-stack.md) · [Production quality bar](./00-production-ui-quality-bar.md) · [Frontend design skill](../../ai-harness/skills/frontend-design/SKILL.md)

---

## 0. DESIGN.md → CSS Variable Mapping

We Check keeps semantic CSS var names; values come from DESIGN.md `colors.*` tokens.

| DESIGN.md token | Hex | CSS variable |
| --- | --- | --- |
| `colors.primary` | `#5645d4` | `--color-primary-600` |
| `colors.primary-pressed` | `#4534b3` | `--color-primary-700` |
| `colors.primary-deep` | `#3a2a99` | `--color-primary-500` |
| `colors.on-primary` | `#ffffff` | `--color-primary-foreground` |
| `colors.brand-navy` | `#0a1530` | `--color-brand-700` |
| `colors.brand-navy-deep` | `#070f24` | `--color-brand-900` |
| `colors.brand-navy-mid` | `#1a2a52` | `--color-brand-500` |
| `colors.card-tint-lavender` | `#e6e0f5` | `--color-primary-50` |
| `colors.link-blue` | `#0075de` | `--color-link` |
| `colors.canvas` | `#ffffff` | `--color-surface-raised` |
| `colors.surface` | `#f6f5f4` | `--color-surface-default` |
| `colors.surface-soft` | `#fafaf9` | `--color-surface-muted` |
| `colors.hairline` | `#e5e3df` | `--color-border-default` |
| `colors.hairline-strong` | `#c8c4be` | `--color-border-strong` |
| `colors.charcoal` | `#37352f` | `--color-text-primary` |
| `colors.slate` | `#5d5b54` | `--color-text-secondary` |
| `colors.steel` | `#787671` | `--color-text-muted` |
| `colors.muted` | `#bbb8b1` | `--color-text-disabled` |
| `colors.on-dark` | `#ffffff` | `--color-text-inverse` |
| `colors.semantic-success` | `#1aae39` | `--color-success-500` |
| `colors.semantic-warning` | `#dd5b00` | `--color-warning-500` |
| `colors.semantic-error` | `#e03131` | `--color-danger-500` |
| `colors.card-tint-mint` | `#d9f3e1` | `--color-success-50` |
| `colors.card-tint-peach` | `#ffe8d4` | `--color-warning-50` |
| `colors.card-tint-rose` | `#fde0ec` | `--color-danger-50` |
| `colors.card-tint-sky` | `#dcecfa` | `--color-info-50` |
| `colors.link-blue` | `#0075de` | `--color-info-500` |

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

### 3.1 Brand navy (identity)

| Token | Value | Tailwind key | Use |
| --- | --- | --- | --- |
| `--color-brand-500` | `#1a2a52` | `brand-500` | Mid navy accent |
| `--color-brand-700` | `#0a1530` | `brand-700` | Auth hero band, sidebar accent |
| `--color-brand-900` | `#070f24` | `brand-900` | Deep navy on dark surfaces |

### 3.2 Action primary (CTAs)

| Token | Value | Tailwind key |
| --- | --- | --- |
| `--color-primary-50` | `#e6e0f5` | `primary-50` |
| `--color-primary-500` | `#3a2a99` | `primary-500` |
| `--color-primary-600` | `#5645d4` | `primary-600` |
| `--color-primary-700` | `#4534b3` | `primary-700` |
| `--color-primary-foreground` | `#ffffff` | `primary-foreground` |

Primary actions: “Điểm danh”, “Mở buổi học”, “Lưu”. Notion purple (`colors.primary`) — signature CTA color.

#### 3.2.1 Button contrast pairs

Authoritative foreground/background pairings for `Button` variants. Implementers must use these token pairs — not ad-hoc opacity or lighter shades that weaken contrast.

| Pair | Foreground token | Background token | Min ratio |
| --- | --- | --- | --- |
| Primary label | `--color-primary-foreground` | `--color-primary-600` | **4.5:1** |
| Primary hover | `--color-primary-foreground` | `--color-primary-700` | **4.5:1** |
| Secondary label | `--color-text-primary` | `--color-surface-raised` | **4.5:1** |
| Outline label | `--color-primary-600` | `--color-surface-default` | **4.5:1** |
| Ghost label | `--color-text-primary` | transparent over `--color-surface-default` | **4.5:1** |
| Danger label | `--color-text-inverse` (`#ffffff`) | `--color-danger-500` | **4.5:1** |
| Disabled label | `--color-text-disabled` | `--color-surface-muted` | **≥ 3:1** (UI component) |

Default filled primary buttons use `--color-primary-600` (`#5645d4` on `#ffffff` text — passes 4.5:1).

### 3.3 Surfaces and text

| Token | Value | Use |
| --- | --- | --- |
| `--color-surface-default` | `#f6f5f4` | Warm gray page background (`colors.surface`) |
| `--color-surface-raised` | `#ffffff` | Cards, modals, elevated panels (`colors.canvas`) |
| `--color-surface-muted` | `#fafaf9` | Secondary sections, table hover (`colors.surface-soft`) |
| `--color-surface-inverse` | `#0a1530` | Dark chrome accents |
| `--color-text-primary` | `#37352f` | Body text (`colors.charcoal`) |
| `--color-text-secondary` | `#5d5b54` | Captions, hints (`colors.slate`) |
| `--color-text-muted` | `#787671` | Table metadata (`colors.steel`) |
| `--color-text-inverse` | `#ffffff` | Text on navy/brand surfaces |
| `--color-text-disabled` | `#bbb8b1` | Disabled controls (`colors.muted`) |
| `--color-border-default` | `#e5e3df` | Dividers, inputs (`colors.hairline`) |
| `--color-border-strong` | `#c8c4be` | Table headers, input focus border (`colors.hairline-strong`) |
| `--color-link` | `#0075de` | Inline links (`colors.link-blue`) |

### 3.4 Semantic feedback

| Token | Value | Contrast on white | Use |
| --- | --- | --- | --- |
| `--color-success-500` | `#1aae39` | 4.5:1+ | `Present`, success toast, outcome icon |
| `--color-success-50` | `#d9f3e1` | — | Success wash (`card-tint-mint`) |
| `--color-warning-500` | `#dd5b00` | 4.5:1+ | `Pending`, countdown warning |
| `--color-warning-50` | `#ffe8d4` | — | Warning wash (`card-tint-peach`) |
| `--color-danger-500` | `#e03131` | 4.5:1+ | `Absent`, errors |
| `--color-danger-50` | `#fde0ec` | — | Error wash (`card-tint-rose`) |
| `--color-info-500` | `#0075de` | 4.5:1+ | `Excused`, info tips |
| `--color-info-50` | `#dcecfa` | — | Info wash (`card-tint-sky`) |

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
| `--focus-ring-color` | `#5645d4` |
| `--focus-ring-width` | `2px` |
| `--focus-ring-offset` | `2px` |

---

## 4. Typography Tokens

Notion Sans is proprietary; We Check uses **Inter** (public equivalent with Vietnamese subset).

| Token | Value |
| --- | --- |
| `--font-display` | `"Inter", system-ui, -apple-system, "Segoe UI", sans-serif` |
| `--font-sans` | `"Inter", system-ui, -apple-system, "Segoe UI", sans-serif` |
| `--font-mono` | `ui-monospace, "Cascadia Code", "Segoe UI Mono", monospace` |
| `--text-display-size` | `1.75rem` |
| `--text-display-line` | `2.25rem` |
| `--text-h1-size` | `1.5rem` |
| `--text-h1-line` | `2rem` |
| `--text-h2-size` | `1.25rem` |
| `--text-h2-line` | `1.75rem` |
| `--text-body-size` | `1rem` |
| `--text-body-line` | `1.55rem` |
| `--text-small-size` | `0.875rem` |
| `--text-small-line` | `1.25rem` |
| `--font-weight-normal` | `400` |
| `--font-weight-medium` | `500` |
| `--font-weight-semibold` | `600` |
| `--font-weight-bold` | `700` |

**Usage:** Inter for all UI surfaces. Load via Google Fonts with `vietnamese` subset and `font-display: swap`. Be Vietnam Pro is an optional fallback only if browser QA shows diacritic rendering issues.

Scale aligns with DESIGN.md `body-md` (16 px), `body-sm` (14 px), `heading-3` (28 px) for display contexts.

---

## 5. Spacing Tokens

| Token | Value | DESIGN.md |
| --- | --- | --- |
| `--space-0` | `0` | — |
| `--space-1` | `0.25rem` (4 px) | `spacing.xxs` |
| `--space-2` | `0.5rem` (8 px) | `spacing.xs` |
| `--space-3` | `0.75rem` (12 px) | `spacing.sm` |
| `--space-4` | `1rem` (16 px) | `spacing.md` |
| `--space-5` | `1.25rem` (20 px) | `spacing.lg` |
| `--space-6` | `1.5rem` (24 px) | `spacing.xl` |
| `--space-8` | `2rem` (32 px) | `spacing.xxl` |
| `--space-10` | `2.5rem` (40 px) | `spacing.xxxl` |
| `--space-12` | `3rem` (48 px) | `spacing.section-sm` |

Tailwind spacing scale aliases `1` → `--space-1`, etc.

### 5.1 Spacing for controls

| Control | Horizontal padding | Vertical / height | Notes |
| --- | --- | --- | --- |
| Button `md` (default) | `--space-4` | min-height `--size-touch-min` (44 px) | Required on student routes; DESIGN.md `button-md` 10px 18px minimum |
| Button `sm` | `--space-3` | `--space-2` vertical inset | Dense tables only |
| Button `lg` | `--space-5` | `--space-4` vertical inset | Hero CTAs, outcome panels |
| Card content | `--space-4` | — | Default card body |
| Card content (emphasis) | `--space-6` | — | Outcome panels, auth forms |
| Stacked form actions | gap `--space-3` | — | Between primary and secondary buttons |

Content must not sit flush against card or panel edges — use at least `--space-4` internal padding.

---

## 6. Radius Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--radius-xs` | `0.25rem` (4 px) | Small chips (`rounded.xs`) |
| `--radius-sm` | `0.375rem` (6 px) | Badge tags (`rounded.sm`) |
| `--radius-md` | `0.5rem` (8 px) | Inputs, buttons (`rounded.md`) |
| `--radius-lg` | `0.75rem` (12 px) | Cards, modals (`rounded.lg`) |
| `--radius-full` | `9999px` | Nav pills, filter chips |

---

## 7. Shadow Tokens

Notion elevation levels from DESIGN.md:

| Token | Value | Level |
| --- | --- | --- |
| `--shadow-sm` | `rgba(15, 15, 15, 0.04) 0px 1px 2px 0px` | 1 (subtle) |
| `--shadow-md` | `rgba(15, 15, 15, 0.08) 0px 4px 12px 0px` | 2 (card) |
| `--shadow-lg` | `rgba(15, 15, 15, 0.16) 0px 16px 48px -8px` | 4 (modal) |
| `--shadow-mockup` | `rgba(15, 15, 15, 0.20) 0px 24px 48px -8px` | 3 (auth card emphasis) |

Level 0: no shadow; `--color-border-default` hairline border only.

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
  --color-brand-700: #0a1530;
  --color-primary-600: #5645d4;
  --color-primary-700: #4534b3;
  --color-primary-foreground: #ffffff;
  --color-surface-default: #f6f5f4;
  --color-surface-raised: #ffffff;
  --color-text-primary: #37352f;
  --color-success-500: #1aae39;
  --color-success-50: #d9f3e1;
  --color-danger-500: #e03131;
  --font-display: "Inter", system-ui, sans-serif;
  --font-sans: "Inter", system-ui, sans-serif;
  --radius-md: 0.5rem;
  --space-4: 1rem;
  --focus-ring-color: #5645d4;
  --size-touch-min: 44px;
  --shadow-md: rgba(15, 15, 15, 0.08) 0px 4px 12px 0px;
}
```

Full set includes all rows in sections 3–10. Implement in `web-design-system-shell` slice (first frontend slice).

---

## 12. Attendance Status Token Mapping

Uses Notion `badge-tag-*` pastel pattern:

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
- Self-hosted Inter font files for offline campus networks.
