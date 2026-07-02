# {{PRODUCT_NAME}} — Design Spec

## 1. Scope

Authoritative visual design specification for **{{PRODUCT_NAME}}** workspace and application UI.

| Dimension | Value |
| --- | --- |
| Product | {{PRODUCT_NAME}} |
| Design style | {{DESIGN_STYLE_NAME}} |
| Primary actors | `{{PRIMARY_ACTOR}}`, `{{SECONDARY_ACTOR}}` |
| Platform | Responsive web; mobile-first where primary flows require it |

**In scope:** authenticated app shells, data tables, forms, listing pages (`TableToolbar`), empty/loading/error states, permission-denied recovery paths.

**Out of scope:** marketing landing pages, pricing tiers, decorative hero patterns unless a route explicitly uses them.

**Implementation:** map design-system tokens to CSS variables in [04-design-tokens.md](./04-design-tokens.md).

**Precedence:** this file → [design-system/](./design-system/) modules → [04-design-tokens.md](./04-design-tokens.md) → [01-design-overview.md](./01-design-overview.md) → harness [visual-design skill](../ai-harness/skills/visual-design/SKILL.md).

Customize this spec during the `uiux-design-md` step — map product routes, domain semantics, and style profile to modules below.

---

## 2. Style profile

**{{DESIGN_STYLE_NAME}}** — product visual direction for {{PRODUCT_NAME}}.

| Token / aspect | Default (customize per product) |
| --- | --- |
| Primary color | `{{PRIMARY_COLOR}}` |
| Border treatment | {{BORDER_STYLE}} |
| Default radius | {{RADIUS_DEFAULT}} |
| Elevation | {{SHADOW_STYLE}} |
| Heading font | {{HEADING_FONT}} |
| Body font | {{BODY_FONT}} |

Principles: accessible contrast (WCAG AA on operational surfaces), semantic outcome colors, honest loading/error states, compact data density on listing routes.

---

## 3. Before writing code

1. **Read every module that applies.** For a typical screen, read at minimum: [layout.md](./design-system/layout.md), [typography.md](./design-system/typography.md), [colors.md](./design-system/colors.md), [buttons.md](./design-system/buttons.md), [cards.md](./design-system/cards.md), [shadows.md](./design-system/shadows.md), [radius.md](./design-system/radius.md), [borders.md](./design-system/borders.md). Do NOT write UI code until relevant modules are loaded.

---

## 4. Critical rules

- **Tokens are agnostic names** — map token names in [04-design-tokens.md](./04-design-tokens.md); do not hardcode raw hex in components.
- **Cross-reference modules** — a card with buttons must satisfy both [cards.md](./design-system/cards.md) and [buttons.md](./design-system/buttons.md).
- **Every interactive element** needs hover, focus, and disabled states per the relevant module.
- **Semantic HTML** — proper heading hierarchy, `<button>` for actions, `<a>` for navigation, ARIA where needed.
- **Style signature** — apply {{DESIGN_STYLE_NAME}} consistently (borders, radius, elevation) per design-system modules.

---

## 5. Module index

### Foundation (read first for any UI work)

- [colors.md](./design-system/colors.md) — background, text, and border color tokens
- [typography.md](./design-system/typography.md) — heading scale, paragraphs, labels, links
- [layout.md](./design-system/layout.md) — spacing rhythm, containers, motion, depth
- [radius.md](./design-system/radius.md) — border-radius scale
- [shadows.md](./design-system/shadows.md) — elevation tokens
- [borders.md](./design-system/borders.md) — border widths and styles

### Components

- [buttons.md](./design-system/buttons.md) — button variants, sizes, states
- [button-group.md](./design-system/button-group.md) — grouped button structure
- [cards.md](./design-system/cards.md) — card structure and interactivity
- [inputs.md](./design-system/inputs.md) — form controls, labels, states
- [alerts.md](./design-system/alerts.md) — alert variants
- [badges.md](./design-system/badges.md) — badge variants and sizes
- [lists.md](./design-system/lists.md) — list components
- [avatars.md](./design-system/avatars.md) — avatar variants
- [icon-shapes.md](./design-system/icon-shapes.md) — icon containers

### Complex components

- [accordion.md](./design-system/accordion.md)
- [dropdown.md](./design-system/dropdown.md)
- [modals.md](./design-system/modals.md)
- [tabs.md](./design-system/tabs.md)
- [tables.md](./design-system/tables.md)
- [pagination.md](./design-system/pagination.md)
- [sidebars.md](./design-system/sidebars.md)
- [radios-checkboxes-toggle.md](./design-system/radios-checkboxes-toggle.md)
- [tooltips-popovers.md](./design-system/tooltips-popovers.md)
- [content.md](./design-system/content.md) — grid system, responsiveness

---

## 6. Domain bridge (customize per product)

Map product-specific behavior to design-system modules during `uiux-design-md` / `uiux-components-pages`:

| Product concern | Authoritative doc | Design-system modules |
| --- | --- | --- |
| Status / outcome semantics | [12-ui-states.md](./12-ui-states.md), BRD state machine | [badges.md](./design-system/badges.md), [alerts.md](./design-system/alerts.md) |
| `TableToolbar` listing contract | [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md) | [tables.md](./design-system/tables.md), [inputs.md](./design-system/inputs.md), [buttons.md](./design-system/buttons.md) |
| App shells and navigation | [06-app-layout-components.md](./06-app-layout-components.md) | [sidebars.md](./design-system/sidebars.md), [layout.md](./design-system/layout.md), [content.md](./design-system/content.md) |
| Forms and validation copy | [08-forms-validation-ux.md](./08-forms-validation-ux.md) | [inputs.md](./design-system/inputs.md), [radios-checkboxes-toggle.md](./design-system/radios-checkboxes-toggle.md) |

---

## 7. Do's and don'ts

### Do

- Apply semantic colors for success, warning, danger, and empty states consistently
- Use `TableToolbar` on every listing route per [14-listing-pages-search-filter-sort.md](./14-listing-pages-search-filter-sort.md)
- Meet [00-production-ui-quality-bar.md](./00-production-ui-quality-bar.md) contrast and touch-target rules
- Use design tokens from [04-design-tokens.md](./04-design-tokens.md) in implementation

### Don't

- Don't use color alone to convey outcome (pair with icon or text)
- Don't use marketing hero bands on operational routes
- Don't use raw hex in component code — always use tokens
- Don't ship generic gray SaaS UI when docs specify differentiated outcomes
