# Attendly — Design Tokens

**Product:** Attendly  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [DESIGN.md](./DESIGN.md) · [03-design-system-basics.md](./03-design-system-basics.md) · [05-common-ui-components.md](./05-common-ui-components.md)

## 0. Token to CSS variable mapping table

| Token category | Token name | CSS variable | Value / source |
| --- | --- | --- | --- |
| Brand color | `color.brand.primary` | `--color-brand-primary` | `#FFDB33` |
| Border default | `border.default` | `--border-default` | `2px solid #000000` |
| Radius base | `radius.base` | `--radius-base` | `0px` |
| Shadow xs | `shadow.xs` | `--shadow-xs` | hard offset, no blur |
| Shadow sm | `shadow.sm` | `--shadow-sm` | hard offset, no blur |
| Shadow md | `shadow.md` | `--shadow-md` | hard offset, no blur |
| Shadow lg | `shadow.lg` | `--shadow-lg` | hard offset, no blur |
| Heading font | `font.heading.family` | `--font-heading-family` | `Archivo Black, sans-serif` |
| Body font | `font.body.family` | `--font-body-family` | `Space Grotesk, sans-serif` |
| Success background | `color.success.soft` | `--color-success-soft` | from `design-system/colors.md` |
| Danger background | `color.danger.soft` | `--color-danger-soft` | from `design-system/colors.md` |
| Warning background | `color.warning.soft` | `--color-warning-soft` | from `design-system/colors.md` |
| Neutral soft | `color.neutral.primarySoft` | `--color-neutral-primary-soft` | from `design-system/colors.md` |

## 1. Purpose

Define the canonical design token set and mapping rules for Attendly implementation.

## 2. Token governance

### 2.1 Governance requirements

- `BR-TOK-01`: `DESIGN.md` and `design-system/` remain the semantic source of tokens.
- `BR-TOK-02`: This document maps those semantics to implementation variables.
- `BR-TOK-03`: Tokens can be extended, but existing semantics must not be silently repurposed.

### 2.2 Naming conventions

- Color tokens: `color.<family>.<role>`
- Typography tokens: `font.<scope>.<property>`
- Space tokens: `space.<scale>`
- Radius tokens: `radius.<size>`
- Shadow tokens: `shadow.<size>`
- Border tokens: `border.<role>`

## 3. Color tokens

| Token | Intent | Typical usage |
| --- | --- | --- |
| `color.brand.primary` | Primary brand emphasis | Primary CTA, highlight states |
| `color.brand.soft` | Soft brand context | Informational banners |
| `color.success.soft` | Positive status background | Present/success alerts |
| `color.success.strongText` | Positive emphasis text | Success labels and counts |
| `color.warning.soft` | Caution state background | Late status and warnings |
| `color.danger.soft` | Error/deny background | Rejection and destructive feedback |
| `color.neutral.primarySoft` | Structural neutral surface | Cards/panels |
| `color.neutral.secondarySoft` | Secondary controls | Trigger/background variants |

## 4. Typography tokens

| Token | Value | Usage |
| --- | --- | --- |
| `font.heading.family` | `Archivo Black, sans-serif` | Page and section headings |
| `font.body.family` | `Space Grotesk, sans-serif` | Body content and forms |
| `font.size.xs` | 12px | Meta labels and compact badges |
| `font.size.sm` | 14px | Default body and control text |
| `font.size.md` | 16px | Prominent body and alert titles |
| `font.size.lg` | 20px | Section headers |
| `font.weight.regular` | 400 | Standard content |
| `font.weight.semibold` | 600 | Action labels and statuses |
| `font.weight.black` | 900 | Major headings |

## 5. Spacing and layout tokens

| Token | Suggested value | Usage |
| --- | --- | --- |
| `space.1` | 4px | Tight icon and micro gaps |
| `space.2` | 8px | Compact control spacing |
| `space.3` | 12px | Standard small gaps |
| `space.4` | 16px | Common block spacing |
| `space.5` | 20px | Panel and card padding |
| `space.6` | 24px | Section spacing |
| `space.8` | 32px | Large layout spacing |

## 6. Border, radius, and shadow tokens

### 6.1 Borders and radius

| Token | Value | Usage |
| --- | --- | --- |
| `border.default` | `2px solid #000000` | Default component boundary |
| `border.subtle` | `2px solid` semantic subtle color | Variant alerts/badges |
| `radius.base` | `0px` | Default Neobrutalist geometry |
| `radius.pill` | `9999px` | Badge pills and optional circular avatars |

### 6.2 Shadows

| Token | Usage |
| --- | --- |
| `shadow.xs` | Small elevation on compact controls |
| `shadow.sm` | Default card/control elevation |
| `shadow.md` | Emphasized panels |
| `shadow.lg` | High-priority overlays |

All shadows are hard offset without blur.

## 7. Component token contracts

| Component | Required token contracts | Source module |
| --- | --- | --- |
| Alert | semantic bg + border + text tokens | `design-system/alerts.md` |
| Badge | status semantic tokens + optional pill radius | `design-system/badges.md` |
| Avatar | size and radius contract | `design-system/avatars.md` |
| Accordion | surface and border hierarchy tokens | `design-system/accordion.md` |
| Table | row, header, status, and border contracts | `design-system/tables.md` |

## 8. Implementation guidance

### 8.1 CSS variable example

```css
:root {
  --color-brand-primary: #ffdb33;
  --border-default: 2px solid #000000;
  --radius-base: 0px;
  --font-heading-family: "Archivo Black", sans-serif;
  --font-body-family: "Space Grotesk", sans-serif;
}
```

### 8.2 Do and do-not rules

- `FR-TOK-01`: Do use semantic variables in components.
- `FR-TOK-02`: Do keep token aliasing consistent across route bundles.
- `FR-TOK-03`: Do not hardcode alternate borders/radius/shadows outside approved tokens.

## 9. Traceability

| Token decision | Requirement alignment |
| --- | --- |
| Strong status semantics | `FR-22`, `BR-23`, `AC-18` |
| High-contrast session visuals | `FR-14`, `NFR-15` |
| Mobile readable typography | `FR-16`, `NFR-14` |
| Consistent admin listing surfaces | `FR-28`, `AC-UI-07` |

## 10. Future consideration

- Dark theme token layer with preserved semantic mapping.
- Data-viz token extension for charting-intensive future modules.
