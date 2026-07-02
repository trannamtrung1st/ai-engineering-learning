# Design System — Agent Instructions

This skill describes the visual design language for all UI output. Every component, layout, and page should follow the design specs in the module files below. These describe *what the design looks like* — you choose how to implement the styles.

**Style:** Neobrutalism — loud, unapologetic UI built on hard offset shadows, thick 2–3px black borders, zero-radius corners, and punchy saturated color.

Every surface snaps into place with physical weight — buttons press down on click, cards lift on hover, and nothing fades softly.

## Before Writing Any Code

1. **Read every module that applies.** For a landing page, read at minimum: [layout.md](./design-system/layout.md), [typography.md](./design-system/typography.md), [colors.md](./design-system/colors.md), [buttons.md](./design-system/buttons.md), [cards.md](./design-system/cards.md), [shadows.md](./design-system/shadows.md), [radius.md](./design-system/radius.md), [borders.md](./design-system/borders.md). Do NOT write JSX until you have loaded all relevant modules.

## Critical Rules

- **Tokens are AGNOSTIC, NOT Tailwind classes:** The tokens defined in the `.md` files (like `neutral-primary-soft`, `heading`, `border-default`) are agnostic design system tokens, NOT literal Tailwind classes. Do not blindly use classes like `bg-neutral-primary-soft` unless you have explicitly mapped them in the CSS/Tailwind configuration. You must implement the mapping yourself.

- **Cross-reference modules.** A card containing buttons must satisfy both [cards.md](./design-system/cards.md) AND [buttons.md](./design-system/buttons.md).
- **Dark mode is automatic.** The CSS custom properties resolve differently in light/dark via `@media (prefers-color-scheme: dark)`. Never manually swap colors.
- **Every interactive element needs hover, focus, and disabled states** — defined in the relevant module.
- **Use semantic HTML:** proper heading hierarchy (`h1`→`h6`), `<button>` for actions, `<a>` for navigation, ARIA attributes where needed.
- **Neobrutalism signature:** all components must use hard offset shadows (no blur), thick solid borders, and sharp or minimal radius. No soft/blurred shadows or subtle borders.

## Module Index

### Foundation (read first for any UI work)

- [colors.md](./design-system/colors.md) — all background, text, and border color tokens
- [typography.md](./design-system/typography.md) — heading scale, paragraphs, labels, links
- [layout.md](./design-system/layout.md) — spacing rhythm, containers, animation, visual depth
- [radius.md](./design-system/radius.md) — border-radius scale
- [shadows.md](./design-system/shadows.md) — elevation tokens
- [borders.md](./design-system/borders.md) — border widths and styles

### Components

- [buttons.md](./design-system/buttons.md) — button variants, sizes, states, hover/press effects
- [button-group.md](./design-system/button-group.md) — grouped button structure
- [cards.md](./design-system/cards.md) — card structure, background, interactivity
- [inputs.md](./design-system/inputs.md) — form controls, labels, states
- [alerts.md](./design-system/alerts.md) — alert variants
- [badges.md](./design-system/badges.md) — badge variants, sizes, dismissible chips
- [lists.md](./design-system/lists.md) — list components
- [avatars.md](./design-system/avatars.md) — avatar variants, sizes, indicators
- [icon-shapes.md](./design-system/icon-shapes.md) — icon containers

### Complex Components

- [accordion.md](./design-system/accordion.md) — accordion variants
- [dropdown.md](./design-system/dropdown.md) — dropdown menus
- [modals.md](./design-system/modals.md) — modal dialogs
- [tabs.md](./design-system/tabs.md) — tab navigation
- [tables.md](./design-system/tables.md) — table structure
- [pagination.md](./design-system/pagination.md) — pagination components
- [sidebars.md](./design-system/sidebars.md) — sidebar navigation
- [radios-checkboxes-toggle.md](./design-system/radios-checkboxes-toggle.md) — selection controls
- [tooltips-popovers.md](./design-system/tooltips-popovers.md) — tooltips and popovers
- [content.md](./design-system/content.md) — grid system, responsiveness
