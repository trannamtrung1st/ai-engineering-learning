# {{PRODUCT_NAME}} — Design Spec

## Scope

Authoritative visual design specification for **{{PRODUCT_NAME}}** workspace and application UI.

- **In scope:** authenticated app shells, data tables, forms, listing pages, empty/loading/error states
- **Out of scope:** marketing landing pages, pricing tiers, and decorative hero patterns unless a route explicitly uses them
- **Implementation:** map tokens to CSS variables in [04-design-tokens.md](./04-design-tokens.md) (§0 mapping table)
- **Precedence:** this file > [04-design-tokens.md](./04-design-tokens.md) > [01-design-overview.md](./01-design-overview.md)

---

```yaml
version: default
name: {{PRODUCT_NAME}}-design-system
description: Neutral workspace design system for {{PRODUCT_NAME}} — calm surfaces, accessible contrast, compact data density.

colors:
  primary: "#2563eb"
  primary-pressed: "#1d4ed8"
  primary-deep: "#1e40af"
  on-primary: "#ffffff"
  canvas: "#ffffff"
  surface: "#f8fafc"
  surface-soft: "#f1f5f9"
  surface-elevated: "#ffffff"
  hairline: "#e2e8f0"
  hairline-strong: "#cbd5e1"
  charcoal: "#0f172a"
  slate: "#475569"
  steel: "#64748b"
  muted: "#94a3b8"
  on-dark: "#ffffff"
  link-blue: "#2563eb"
  link-blue-pressed: "#1d4ed8"
  semantic-success: "#16a34a"
  semantic-warning: "#d97706"
  semantic-error: "#dc2626"
  card-tint-mint: "#dcfce7"
  card-tint-peach: "#ffedd5"
  card-tint-rose: "#ffe4e6"
  card-tint-lavender: "#ede9fe"

typography:
  font-family: "Inter, system-ui, sans-serif"
  body-md: "14px/1.5"
  body-sm: "13px/1.45"
  label-md: "12px/1.4 500"
  heading-lg: "24px/1.25 600"
  heading-md: "18px/1.3 600"

spacing:
  xs: 4
  sm: 8
  md: 12
  lg: 16
  xl: 24
  xxl: 32

radius:
  sm: 4
  md: 6
  lg: 8
  full: 9999

elevation:
  card: "0 1px 2px rgba(15, 23, 42, 0.06)"
  dropdown: "0 4px 12px rgba(15, 23, 42, 0.08)"
```
