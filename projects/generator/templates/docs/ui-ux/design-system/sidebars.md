# Sidebars

> Dependencies: `colors.md`, `radius.md`, `typography.md`, `badges.md`, `alerts.md`

## Core Specs

- Background: neutral-primary-soft
- Right border: {{BORDER_STYLE}} (for left-sidebar); left border for right-sidebar
- Width: 256px

## Anatomy

### Outer Container
Hidden on mobile, visible at small breakpoint. Needs a toggle/trigger for mobile.

### Inner Wrapper
- Full height, vertical scroll overflow
- Padding: 12px horizontal, 16px vertical

### Navigation List
- First item **must** be a home/dashboard link (linked product name or a "Home" label with a home icon) — always visible, always functional, never conditional on role
- Vertical spacing: 8px between items
- Font weight: semibold

### Navigation Item
- Layout: flex, vertically centered
- Padding: 8px horizontal, 8px vertical
- Text: heading color
- Radius: {{RADIUS_DEFAULT}} (base)
- Hover: neutral-secondary-medium background
- Transition: colors
- Icon: 20x20px, body color, hover → heading color, 75ms transition
- Label: 12px left margin from icon

### Active Item
- Background: neutral-secondary-strong
- Text: fg-brand-strong

### Separator
- 16px top padding, 16px top margin
- Top border: {{BORDER_STYLE}}
- 8px vertical spacing below

### Bottom CTA / Card
- Padding: 16px
- Top margin: 24px
- Radius: {{RADIUS_DEFAULT}} (base)
- Background: brand-softer
- Border: 2px solid border-brand-subtle
- Can also use any alert variant from `alerts.md`

## Rules

- **Home link first:** the top nav item is always a home/dashboard link reachable by every authenticated role — never omit it, never move it below the fold.
- **RBAC gating:** render only the nav items that the current user's role is permitted to access, as defined in `docs/technical/01-roles-permissions.md`. Do **not** render forbidden items as disabled anchor tags — omit them from the DOM entirely. CSS `display:none` or `pointer-events:none` is also forbidden; the item must not be present in the rendered output.
- **No dead ends:** every item in the nav list must link to a real, implemented route. Never add a nav item as a placeholder.
- Responsive: hidden on mobile with a trigger mechanism
- Icons: 20x20px, body color (hover: heading color)
- Multi-level menus: indent with 44px left padding
- Spacing follows 8px grid
- Only neutral, brand, or status tokens — no arbitrary colors
