# Design Tokens

## Token strategy

Use semantic tokens as the source of truth so components reference meaning, not hard-coded values. This allows theme updates and accessibility adjustments without changing component code.

## Color tokens

### Base surfaces and text
- `color.bg.default`
- `color.bg.surface`
- `color.bg.subtle`
- `color.text.primary`
- `color.text.secondary`
- `color.text.inverse`
- `color.border.default`
- `color.border.strong`

### Interactive states
- `color.action.primary.bg`
- `color.action.primary.text`
- `color.action.primary.hover`
- `color.action.secondary.bg`
- `color.action.focus.ring`
- `color.action.disabled.bg`
- `color.action.disabled.text`

### Domain status tokens
- `color.status.registered`
- `color.status.waitlisted`
- `color.status.rejected`
- `color.status.attended`
- `color.status.absent`
- `color.status.eligible`
- `color.status.notEligible`
- `color.status.pending`

Each status color must have an accessible foreground variant and icon/text pairing.

## Typography tokens

- `font.family.base`
- `font.size.xs|sm|md|lg|xl|2xl`
- `font.weight.regular|medium|semibold|bold`
- `line.height.tight|normal|relaxed`
- `letter.spacing.normal|wide`

## Spacing and layout tokens

- `space.1..12` mapped to 4px scale.
- `container.max.reading`
- `container.max.app`
- `gap.section`
- `gap.component`

## Radius and elevation tokens

- `radius.sm|md|lg|xl|pill`
- `shadow.sm|md|lg` (use sparingly; prioritize border + contrast first)

## Motion tokens

- `motion.duration.fast|normal|slow`
- `motion.easing.standard|emphasized|decelerate`

Use reduced motion media query to minimize animation for users who request it.

## Token usage rules

- Components should consume semantic tokens only.
- No hex or pixel literals in feature-level components (except temporary prototypes).
- Domain states must use consistent token mapping across all screens.
- Token changes require visual regression check on participant and organizer critical screens.
