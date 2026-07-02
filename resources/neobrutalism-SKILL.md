# Design System — Agent Instructions

This skill describes the visual design language for all UI output. Every component, layout, and page should follow the design specs in the module files below. These describe *what the design looks like* — you choose how to implement the styles.

**Style:** Neobrutalism — loud, unapologetic UI built on hard offset shadows, thick 2–3px black borders, zero-radius corners, and punchy saturated color.

Every surface snaps into place with physical weight — buttons press down on click, cards lift on hover, and nothing fades softly.

## Before Writing Any Code

1. **Read every module that applies.** For a landing page, read at minimum: `layout.md`, `typography.md`, `colors.md`, `buttons.md`, `cards.md`, `shadows.md`, `radius.md`, `borders.md`. Do NOT write JSX until you have loaded all relevant modules.

## Critical Rules

- **Tokens are AGNOSTIC, NOT Tailwind classes:** The tokens defined in the `.md` files (like `neutral-primary-soft`, `heading`, `border-default`) are agnostic design system tokens, NOT literal Tailwind classes. Do not blindly use classes like `bg-neutral-primary-soft` unless you have explicitly mapped them in the CSS/Tailwind configuration. You must implement the mapping yourself.

- **Cross-reference modules.** A card containing buttons must satisfy both `cards.md` AND `buttons.md`.
- **Dark mode is automatic.** The CSS custom properties resolve differently in light/dark via `@media (prefers-color-scheme: dark)`. Never manually swap colors.
- **Every interactive element needs hover, focus, and disabled states** — defined in the relevant module.
- **Use semantic HTML:** proper heading hierarchy (`h1`→`h6`), `<button>` for actions, `<a>` for navigation, ARIA attributes where needed.
- **Neobrutalism signature:** all components must use hard offset shadows (no blur), thick solid borders, and sharp or minimal radius. No soft/blurred shadows or subtle borders.

## Module Index

### Foundation (read first for any UI work)
- [colors.md](colors.md) — all background, text, and border color tokens
- [typography.md](typography.md) — heading scale, paragraphs, labels, links
- [layout.md](layout.md) — spacing rhythm, containers, animation, visual depth
- [radius.md](radius.md) — border-radius scale
- [shadows.md](shadows.md) — elevation tokens
- [borders.md](borders.md) — border widths and styles

### Components
- [buttons.md](buttons.md) — button variants, sizes, states, hover/press effects
- [button-group.md](button-group.md) — grouped button structure
- [cards.md](cards.md) — card structure, background, interactivity
- [inputs.md](inputs.md) — form controls, labels, states
- [alerts.md](alerts.md) — alert variants
- [badges.md](badges.md) — badge variants, sizes, dismissible chips
- [lists.md](lists.md) — list components
- [avatars.md](avatars.md) — avatar variants, sizes, indicators
- [icon-shapes.md](icon-shapes.md) — icon containers

### Complex Components
- [accordion.md](accordion.md) — accordion variants
- [dropdown.md](dropdown.md) — dropdown menus
- [modals.md](modals.md) — modal dialogs
- [tabs.md](tabs.md) — tab navigation
- [tables.md](tables.md) — table structure
- [pagination.md](pagination.md) — pagination components
- [sidebars.md](sidebars.md) — sidebar navigation
- [radios-checkboxes-toggle.md](radios-checkboxes-toggle.md) — selection controls
- [tooltips-popovers.md](tooltips-popovers.md) — tooltips and popovers
- [content.md](content.md) — grid system, responsiveness

---

## Source file: `accordion.md`

# Accordion

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Wrapper:** full width, 2px border (border-default color), 0px radius — clips first/last item corners
- **Item separator:** 2px bottom border (border-default) on every item except last

## Trigger (Button)

- **Layout:** flex, space-between, full width
- **Padding:** 20px horizontal, 16px vertical
- **Font:** 14px, semibold weight
- **Text color:** heading
- **Background:** neutral-secondary-soft
- **Hover:** neutral-tertiary-soft background
- **Focus:** outline none, 2px ring in brand color
- **Transition:** colors, 100ms
- **Open state:** neutral-tertiary-soft background

## Panel (Content)

- **Padding:** 20px horizontal, 16px vertical
- **Background:** neutral-primary-soft
- **Top border:** 2px, border-default color
- **Font:** 14px, body color, 1.625 line-height

## Chevron Icon

- Size: 16x16px
- Color: body text color
- Closed: 0deg rotation
- Open: 180deg rotation
- Transition: transform, 150ms

## Variants

### Default (Collapse)
One panel open at a time. Items stacked inside a single shared bordered wrapper.

### Separated Cards
Each item is independent — has its own 2px border, 0px radius, and shadow-sm. 8px bottom margin between items. No shared outer border.

### Always Open
Multiple panels can expand simultaneously. Same styling as Default.

### Flush
No outer border. Trigger and panel have transparent backgrounds. Only bottom border dividers between items. Use inside containers that already provide a background.

## States

| State | Trigger appearance |
|---|---|
| Closed | heading text, neutral-secondary-soft background |
| Open | heading text, neutral-tertiary-soft background |
| Hover | neutral-tertiary-soft background |
| Focus | 2px brand ring, no outline |
| Disabled | fg-disabled text, not-allowed cursor, no hover/focus |

---

## Source file: `alerts.md`

# Alerts

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Padding:** 16px
- **Radius:** 0px (base)
- **Border:** 2px solid
- **Heading:** 16px, semibold weight
- **Body:** 14px, normal weight, 1.6 line-height

## Variants

### Brand
- **Background:** brand-softer
- **Border:** 2px solid border-brand-subtle
- **Text:** fg-brand-strong

### Success
- **Background:** success-soft
- **Border:** 2px solid border-success-subtle
- **Text:** fg-success-strong

### Danger
- **Background:** danger-soft
- **Border:** 2px solid border-danger-subtle
- **Text:** fg-danger-strong

### Warning
- **Background:** warning-soft
- **Border:** 2px solid border-warning-subtle
- **Text:** fg-warning

---

## Source file: `avatars.md`

# Avatars

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Circular shape:** fully rounded (9999px)
- **Rounded square shape:** 0px radius
- **Default size:** 40x40px
- **Image fit:** cover

## Sizes

| Size | Dimensions | Radius |
|---|---|---|
| Extra Small | 18x18px | 0px |
| Small | 24x24px | 0px |
| Base | 32x32px | 0px |
| Large | 44x44px | 0px |
| XL | 56x56px | 0px |
| 2XL | 64x64px | 0px |

## Bordered Avatar

- 4px padding, fully rounded, 2px outline in border-default color
- Alternative: 2px box-shadow ring in border-default color

## Stacked Avatars

- Displayed in a row (flex)
- Each avatar: 40x40px, fully rounded, 2px border in border-buffer color
- Overlap: -16px negative margin on all except first

### Stacked Counter
- Same size as avatars (40x40px), fully rounded
- Background: dark-strong, text: white, 12px font, semibold weight
- Same overlap margin as other avatars

## Avatar with Text

- Flex row, 10px gap between avatar and text
- Avatar: 40x40px, fully rounded, cover fit
- Name: heading color, semibold weight
- Subtitle: 14px, body color

---

## Source file: `badges.md`

# Badges

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Border:** 2px solid
- **Default radius:** 0px
- **Pill radius:** 9999px

## Sizes

| Size | Font size | Horizontal padding | Vertical padding |
|---|---|---|---|
| Default (small) | 12px | 6px | 2px |
| Large | 14px | 8px | 4px |

## Variants

### Brand
- **Background:** brand-softer
- **Border:** 2px solid border-brand-subtle
- **Text:** fg-brand-strong

### Alternative (Neutral Soft)
- **Background:** neutral-primary-soft
- **Border:** 2px solid border-default
- **Text:** heading

### Gray (Neutral Medium)
- **Background:** neutral-secondary-medium
- **Border:** 2px solid border-default
- **Text:** heading

### Danger
- **Background:** danger-soft
- **Border:** 2px solid border-danger-subtle
- **Text:** fg-danger-strong

### Success
- **Background:** success-soft
- **Border:** 2px solid border-success-subtle
- **Text:** fg-success-strong

### Warning
- **Background:** warning-soft
- **Border:** 2px solid border-warning-subtle
- **Text:** fg-warning

### Dark
- **Background:** dark (#000000)
- **Border:** 2px solid transparent
- **Text:** white

## Pill Badges

Use 9999px radius instead of 0px on any variant.

## Badges with Icons

- Icon size (default): 12x12px
- Icon size (large): 14x14px
- Icon spacing: 4px margin next to label

## Icon-only Badge

Square shape — equalize dimensions to 24x24px, no horizontal text padding.

## Dismissible Badges

Badge content + a close button. Close button hover backgrounds per variant:

| Variant | Close button hover background |
|---|---|
| Brand | brand-soft |
| Alternative | neutral-tertiary |
| Gray | neutral-quaternary |
| Danger | danger-medium |
| Success | success-medium |
| Warning | warning-medium |

## Dot / Notification Badge

- Positioned absolutely: -4px top, -4px right
- Size: 12x12px, fully rounded
- 2px border in border-buffer color
- Background: danger

---

## Source file: `borders.md`

# Borders

## Width Scale

| Context | Width |
|---|---|
| Default (inputs, buttons, cards) | 2px |
| Emphasis / focus | 3px |

## Rules

- Use solid borders by default — thick black borders are the neobrutalism signature
- Dashed borders only for special cases like file dropzones
- Components in the same family must use matching border widths
- Never mix 2px and 3px borders within a single component
- Border color defaults to border-default (#000000 in light mode)

## Usage

| Context | Width |
|---|---|
| Inputs / selects / textareas | 2px default; 3px on focus or error |
| Buttons | 2px solid border on all variants |
| Cards / containers | 2px solid border |

---

## Source file: `button-group.md`

# Button Groups

> Dependencies: `buttons.md`, `colors.md`, `radius.md`

## Core Specs

- **Wrapper:** inline-flex, 0px radius, shadow-sm (hard offset)
- **Children overlap:** -2px left margin on all except first button
- **Buttons inside the group must NOT have individual shadows.** Only the wrapper has a shadow.

## Anatomy

### Wrapper
- Display: inline-flex
- Radius: 0px
- Shadow: shadow-sm
- Border: 2px solid border-default

### First Button
- 0px radius on inline-start side only, 0 on inline-end

### Middle Button(s)
- No radius (0 on all corners)

### Last Button
- 0px radius on inline-end side only, 0 on inline-start

### All buttons except first
- -2px left margin to overlap borders

## Rules

- Buttons inside groups follow all styles from `buttons.md` (background, border, focus rings) except individual shadows
- Icon-only buttons: 16x16px icon, match height of text buttons

---

## Source file: `buttons.md`

# Buttons

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Core Specs (every button except ghost and disabled)

- **Radius:** 0px (base) or 9999px for pills
- **Border:** 2px solid border-default (black in light mode)
- **Shadow:** shadow-sm (hard offset: `3px 3px 0 0`)
- **Hover shadow shift:** On hover, translate the button -1px up and -1px left and increase shadow to shadow-md (`4px 4px 0 0`) for a "lifted" feel
- **Active press:** On active/click, translate 2px right and 2px down and reduce shadow to shadow-2xs (`1px 1px 0 0`) for a "pressed" feel
- **Font weight:** 600 (semibold)
- **Font:** Space Grotesk
- **Box sizing:** border-box
- **Transition:** all 100ms

## Sizes

| Size | Font size | Horizontal padding | Vertical padding |
|---|---|---|---|
| Extra small | 12px | 12px | 6px |
| Small | 14px | 12px | 8px |
| Base (default) | 14px | 16px | 10px |
| Large | 16px | 20px | 12px |
| Extra large | 16px | 24px | 14px |

## Variants

### Brand
- **Background:** brand token (#FFDB33)
- **Border:** 2px solid border-default (black)
- **Text:** black
- **Hover:** brand-strong background, lifted shadow
- **Focus ring:** 4px, brand-medium color
- **Shadow:** shadow-sm

### Secondary
- **Background:** neutral-secondary-medium
- **Border:** 2px solid border-default (black)
- **Text:** heading color
- **Hover:** neutral-tertiary-medium background, lifted shadow
- **Focus ring:** 4px, neutral-tertiary color
- **Shadow:** shadow-sm

### Tertiary
- **Background:** neutral-primary-soft
- **Border:** 2px solid border-default (black)
- **Text:** heading color
- **Hover:** neutral-secondary-medium background, lifted shadow
- **Focus ring:** 4px, neutral-tertiary-soft color
- **Shadow:** shadow-sm

### Success
- **Background:** success token
- **Border:** 2px solid border-default (black)
- **Text:** white
- **Hover:** success-strong background, lifted shadow
- **Focus ring:** 4px, success-medium color
- **Shadow:** shadow-sm

### Danger
- **Background:** danger token (#E63946)
- **Border:** 2px solid border-default (black)
- **Text:** white
- **Hover:** danger-strong background, lifted shadow
- **Focus ring:** 4px, danger-medium color
- **Shadow:** shadow-sm

### Warning
- **Background:** warning token
- **Border:** 2px solid border-default (black)
- **Text:** black
- **Hover:** warning-strong background, lifted shadow
- **Focus ring:** 4px, warning-medium color
- **Shadow:** shadow-sm

### Dark
- **Background:** dark token (#000000)
- **Border:** 2px solid border-default
- **Text:** white
- **Hover:** dark-strong background, lifted shadow
- **Focus ring:** 4px, neutral-tertiary color
- **Shadow:** shadow-sm

### Ghost (NO shadow, NO border)
- **Background:** transparent
- **Border:** transparent
- **Text:** heading color
- **Hover:** neutral-secondary-medium background
- **Focus ring:** 4px, neutral-tertiary color
- **No shadow, no border**

### Disabled (NO shadow)
- **Background:** disabled token
- **Border:** 2px solid border-light
- **Text:** fg-disabled color
- **Cursor:** not-allowed
- **No hover, no focus, no shadow**

## Icons in Buttons

- Icon size: 16x16px
- Spacing: 8px gap between icon and label
- Layout: inline-flex, vertically centered

---

## Source file: `cards.md`

# Cards

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `typography.md`

## Core Specs

- **Background:** neutral-primary-soft (#FFFFFF in light)
- **Border:** 2px solid border-default (black in light mode)
- **Radius:** 0px (base)
- **Shadow:** shadow-md (hard offset: `4px 4px 0 0`)

## Card Heading

- Desktop: 20px, semibold weight, heading color
- Mobile: 16px, semibold weight, heading color
- Never skip heading levels — the page hierarchy must logically arrive at the card heading level.

## States

### Static Card (no interactivity)
- Background: neutral-primary-soft
- Border: 2px solid border-default
- Radius: 0px
- Shadow: shadow-md
- No hover styles. Non-interactive cards must NOT have hover background changes.

### Interactive Card (clickable)
- Same base styles as static card
- Hover: translate -2px up and -2px left, shadow increases to shadow-lg (`6px 6px 0 0`)
- Active: translate 2px right and 2px down, shadow reduces to shadow-xs (`2px 2px 0 0`)
- Transition: all 100ms
- Cursor: pointer

## Rules

- Background: neutral-primary-soft
- Border: 2px solid border-default (black)
- Radius: 0px
- Shadow: shadow-md (hard offset)
- Interactive hover: lift effect with increased shadow
- Non-interactive: no hover styles

---

## Source file: `colors.md`

# Color Tokens

## Background Tokens

### Neutral
| Token | Light | Dark |
|---|---|---|
| neutral-primary-soft | #FFFFFF | #1A1A1A |
| neutral-primary | #FFFFFF | #1A1A1A |
| neutral-primary-medium | #FFFFFF | #242424 |
| neutral-primary-strong | #FFFFFF | #3A3A3A |
| neutral-secondary-soft | #F5F5F0 | #1A1A1A |
| neutral-secondary | #F5F5F0 | #1A1A1A |
| neutral-secondary-medium | #F5F5F0 | #242424 |
| neutral-secondary-strong | #F5F5F0 | #3A3A3A |
| neutral-tertiary-soft | #EBEBEB | #1A1A1A |
| neutral-tertiary | #EBEBEB | #242424 |
| neutral-tertiary-medium | #EBEBEB | #3A3A3A |
| neutral-quaternary | #E0E0E0 | #3A3A3A |
| quaternary-medium | #E0E0E0 | #4A4A4A |
| gray | #AEAEAE | #4A4A4A |

### Brand
| Token | Light | Dark |
|---|---|---|
| brand-softer | #FFF9E0 | #332A00 |
| brand-soft | #FFF3C4 | #4D3F00 |
| brand | #FFDB33 | #FFDB33 |
| brand-medium | #FAE583 | #4D3F00 |
| brand-strong | #FFCC00 | #FFE066 |

### Status
| Token | Light | Dark |
|---|---|---|
| success-soft | #ECFDF5 | #052E16 |
| success | #16A34A | #22C55E |
| success-medium | #DCFCE7 | #14532D |
| success-strong | #15803D | #16A34A |
| danger-soft | #FEF2F2 | #450A0A |
| danger | #E63946 | #E63946 |
| danger-medium | #FECACA | #7F1D1D |
| danger-strong | #C41E30 | #EF4444 |
| warning-soft | #FFFBEB | #78350F |
| warning | #F59E0B | #F59E0B |
| warning-medium | #FEF3C7 | #78350F |
| warning-strong | #D97706 | #D97706 |

### Button Glint (CSS custom properties, used for the glint box-shadow effect)
| Variable | Light | Dark |
|---|---|---|
| `--color-1-400` | rgba(255,255,255,0) | rgba(255,255,255,0) |
| `--color-1-700` | rgba(0,0,0,0) | rgba(0,0,0,0) |

### Utility
| Token | Light | Dark |
|---|---|---|
| dark | #000000 | #000000 |
| dark-strong | #000000 | #3A3A3A |
| disabled | #F5F5F5 | #242424 |

### Accent
| Token | Value (same both modes) |
|---|---|
| purple | #8B5CF6 |
| sky | #0EA5E9 |
| teal | #14B8A6 |
| pink | #EC4899 |
| cyan | #06B6D4 |
| fuchsia | #D946EF |
| indigo | #6366F1 |
| orange | #FB923C |

## Text Color Tokens

### Base
| Token | Light | Dark |
|---|---|---|
| white | #FFFFFF | #FFFFFF |
| black | #000000 | #000000 |
| heading | #000000 | #F5F5F5 |
| body | #5A5A5A | #A0A0A0 |
| body-subtle | #6B7280 | #A0A0A0 |

### Brand
| Token | Light | Dark |
|---|---|---|
| fg-brand-subtle | #FAE583 | #5C4B00 |
| fg-brand | #B8860B | #FFDB33 |
| fg-brand-strong | #996600 | #FAE583 |

### Status
| Token | Light | Dark |
|---|---|---|
| fg-success | #16A34A | #22C55E |
| fg-success-strong | #15803D | #4ADE80 |
| fg-danger | #E63946 | #F87171 |
| fg-danger-strong | #C41E30 | #FCA5A5 |
| fg-warning-subtle | #D97706 | #F59E0B |
| fg-warning | #92400E | #FBBF24 |
| fg-disabled | #AEAEAE | #5A5A5A |

### Informational / Accent
| Token | Light | Dark |
|---|---|---|
| fg-yellow | #EAB308 | #FACC15 |
| fg-info | #1E40AF | #93C5FD |
| fg-purple | #7C3AED | #8B5CF6 |
| fg-purple-strong | #6D28D9 | #C4B5FD |
| fg-cyan | #0891B2 | #06B6D4 |
| fg-indigo | #4F46E5 | #6366F1 |
| fg-pink | #DB2777 | #EC4899 |
| fg-lime | #65A30D | #84CC16 |

## Border Color Tokens

| Token | Light | Dark |
|---|---|---|
| border-dark | #000000 | #F5F5F5 |
| border-buffer | #FFFFFF | #1A1A1A |
| border-buffer-medium | #FFFFFF | #242424 |
| border-buffer-strong | #FFFFFF | #3A3A3A |
| border-muted | #E0E0E0 | #242424 |
| border-light-subtle | #D0D0D0 | #242424 |
| border-light | #BFBFBF | #2E2E2E |
| border-light-medium | #BFBFBF | #3A3A3A |
| border-default-subtle | #000000 | #2E2E2E |
| border-default | #000000 | #3A3A3A |
| border-default-medium | #000000 | #3A3A3A |
| border-default-strong | #000000 | #4A4A4A |
| border-success-subtle | #16A34A | #14532D |
| border-success | #15803D | #16A34A |
| border-danger-subtle | #E63946 | #7F1D1D |
| border-danger | #C41E30 | #E63946 |
| border-warning-subtle | #D97706 | #78350F |
| border-warning | #D97706 | #F59E0B |
| border-brand-subtle | #FFCC00 | #5C4B00 |
| border-brand-light | #FFDB33 | #FFDB33 |
| border-brand | #FFCC00 | #FFE066 |
| border-dark-subtle | #000000 | #3A3A3A |
| border-purple | #8B5CF6 | #8B5CF6 |
| border-orange | #FB923C | #FB923C |

## Semantic Usage Rules

- Page/section backgrounds: neutral-primary-soft (default), neutral-secondary-soft (alternating)
- Primary buttons: brand background with black text
- Headings: heading text color (#000000 light / #F5F5F5 dark)
- Body text: body text color
- CTA links: fg-brand text color
- Default borders: border-default (#000000 in light — the signature neobrutalism black outline)
- Status borders match intent: success → border-success, danger → border-danger, warning → border-warning
- Disabled: disabled background + fg-disabled text

## Prohibited

- No raw hex/rgb values in component code — always use design tokens
- No brand text color for long-form paragraphs
- No accent text tokens (fg-purple, etc.) for body copy or navigation
- No brand/accent backgrounds for large layout surfaces (pages, sections) unless it's a hero/campaign area
- No manual light/dark value swapping — let the CSS custom properties handle it
- No soft/blurred shadows — neobrutalism uses hard offset shadows only

---

## Source file: `content.md`

# Content & Grid System

> Dependencies: `layout.md`, `typography.md`

## Containers

| Type | Max width | Horizontal padding |
|---|---|---|
| Standard | 1280px | 16px |
| Internal (reading) | 768px | — (45–75 char line length) |

## Vertical Padding

| Breakpoint | Vertical padding |
|---|---|
| Mobile | 32px |
| Tablet (≥768px) | 48px |
| Desktop (≥1024px) | 64px or 96px for hero/feature sections |

## Grid System

Mobile-first with flexible desktop configurations.

| Context | Gap |
|---|---|
| Standard content/cards | 32px |
| Compact widgets/metadata | 16px |

### Responsive Columns

| Breakpoint | Columns |
|---|---|
| Mobile (default) | 1–2 |
| Small/Tablet (≥640px) | 2–4 |
| Desktop (≥1024px) | 3–12 |

Full support for 6, 7, 8, 9+ column grids where needed.

## Breakpoints

| Name | Width |
|---|---|
| Small | 640px |
| Medium | 768px |
| Large | 1024px |
| Extra large | 1280px |
| 2x Extra large | 1536px |

## Rules

- Always design mobile-first
- Use layout shifts (column → row) to accommodate horizontal space
- Lists: 24px indentation, 8px vertical gap between items
- Body copy: 16px, 1.625 line-height
- All interactive links follow brand underline/hover protocol

---

## Source file: `dropdown.md`

# Dropdown

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `inputs.md`

## Core Specs

### Chevron Icon
- Size: 16x16px
- Spacing: 6px left margin, -2px right margin
- Color: inherits from trigger button

### Menu Container
- Background: neutral-primary-soft
- Border: 2px solid border-default (black in light mode)
- Radius: 0px (base)
- Shadow: shadow-lg (hard offset: `6px 6px 0 0`)
- Z-index: elevated above content

### Menu List
- Padding: 8px
- Font: 14px, body color, medium weight

### Menu Item
- Layout: inline-flex, vertically centered, full width
- Padding: 8px horizontal, 8px vertical
- Radius: 0px (default)
- Hover: neutral-tertiary-medium background, heading text
- Transition: colors, 100ms

## Trigger Sizes

| Size | Font size | Horizontal padding | Vertical padding |
|---|---|---|---|
| Small | 14px | 12px | 8px |
| Base | 14px | 16px | 10px |
| Large | 16px | 20px | 12px |

## Icon-only Trigger

- Padding: 8px
- Min size: 44x44px
- Icon: 20x20px

## Variants

### Default
- Menu width: 176px, items have 0px radius

### With Divider
- Top border (border-default) between child groups, skip first group

### With Header
- Header padding: 16px horizontal, 12px vertical
- Bottom border: 2px solid border-default
- Name: heading color, 14px, semibold weight
- Email: body-subtle color, 14px, truncated

### With Icons
- Icon before label: 16x16px, 8px right margin, body color
- On hover, icon color changes to heading

### With Checkbox / Radio
- Inputs: 16x16px, 0px radius, focus ring in brand-soft
- Helper text: 12px, body-subtle color, 2px top margin

### With Search
- Search input at top of menu following `inputs.md` specs
- Left icon: 12px left padding, input 36px left padding

### Scrollable
- Max height: 192px, vertical scroll overflow

## States

| State | Appearance |
|---|---|
| Focused trigger | no outline, 2px brand ring |
| Hover item | neutral-tertiary-medium background, heading text |
| Active/open item | neutral-tertiary-soft background, heading text |
| Disabled item | fg-disabled text, not-allowed cursor, no pointer events |

---

## Source file: `icon-shapes.md`

# Icon Shapes

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- Box sizing: border-box
- Icon must be perfectly centered (inline-flex, centered both axes)
- Circle: fully rounded (9999px)
- Square: 0px radius (all sizes)

## Sizes

| Size | Container | Icon |
|---|---|---|
| XS | 24x24px | 14x14px |
| SM | 32x32px | 16x16px |
| MD | 40x40px | 20x20px |
| LG | 48x48px | 24x24px |
| XL | 56x56px | 28x28px |

## Color Variants

### Brand
- Shape: circle
- Background: brand-softer
- Icon color: fg-brand-strong

### Gray
- Shape: circle
- Background: neutral-secondary-soft
- Icon color: body

### Danger
- Shape: circle
- Background: danger-soft
- Icon color: fg-danger-strong

### Success
- Shape: circle
- Background: success-soft
- Icon color: fg-success-strong

### Warning
- Shape: circle
- Background: warning-soft
- Icon color: fg-warning

---

## Source file: `inputs.md`

# Inputs

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Display:** block, full width
- **Radius:** 0px (base)
- **Border:** 2px solid border-default (black in light mode)
- **Background:** neutral-primary-soft (#FFFFFF in light)
- **Shadow:** shadow-xs (hard offset: `2px 2px 0 0`)
- **Font:** 14px, heading color, Space Grotesk
- **Padding:** 12px horizontal, 10px vertical
- **Placeholder:** body color
- **Transition:** all properties, 150ms

## Label

- Display: block
- Font: 14px, semibold weight (600), heading color
- Margin bottom: 8px
- Label `htmlFor` must match the input `id`

## States

### Default
- Border: 2px solid border-default (black)
- Background: neutral-primary-soft
- Shadow: shadow-xs

### Hover
- Border: 2px solid border-default-strong

### Focus
- No outline
- Border: 2px solid border-brand
- Shadow: shadow-sm (increased offset)

### Success
- Border: 2px solid border-success
- Focus shadow: shadow-sm with success color

### Error / Danger
- Border: 2px solid border-danger
- Focus shadow: shadow-sm with danger color

### Disabled
- Background: disabled
- Text: fg-disabled
- Border: 2px solid border-light
- Shadow: none
- Cursor: not-allowed

## Input with Icons

- Icon size: 16x16px
- Icon color: body
- Container: relative positioned wrapper
- Start icon: absolutely positioned left, 12px left padding — input gets 36px left padding
- End icon: absolutely positioned right, 12px right padding — input gets 36px right padding
- Icons vertically centered within the wrapper

## Rules

- Every input must have a unique `id`
- Every label must have a matching `htmlFor`
- Padding: 12px horizontal, 10px vertical unless overridden for icon variants
- No arbitrary hex or hardcoded colors

---

## Source file: `layout.md`

# Layout & Spacing

## Spacing Rhythm

Base unit: **8px**. All spacing values should be multiples of 8px.

| Context | Value |
|---|---|
| Section vertical padding | 96px |
| Section header → content | 48px or 64px |
| Heading → paragraph | 16px |
| Container horizontal padding | 24px |
| Flex/grid row gap | 16px |
| Card grid gap | 24px |
| Wide component grid gap | 32px |
| Column layout gap | 48px |

## Container

Standard section container: max-width 1152px, centered, 24px horizontal padding.

Every major section wraps content in this container.

## Content Composition Order

Inside each section, follow this order:
1. Heading (`h1`–`h3`)
2. Leading paragraph
3. Normal paragraph(s)
4. Lists, CTA links, or component grids

## Section Pattern

Each section has:
- 96px vertical padding
- A background color (alternate between neutral-primary-soft and neutral-secondary-soft)
- A centered container (max-width 1152px, 24px horizontal padding)
- A section header area with 48px bottom margin
- Section content below

## Motion & Animation

- Prefer CSS-native: `transition`, `animation`, `@keyframes`. Use Motion library only when CSS cannot achieve the behavior.
- Keep transitions snappy and intentional — neobrutalism favors bold, immediate state changes over slow easing.
- Interactive elements should have quick hover/active transitions (100–150ms) with distinct state changes (e.g., translate on hover to shift the hard shadow).
- Reserve scroll-triggered and hover transitions for moments that reinforce hierarchy or reward attention.

## Backgrounds & Visual Depth

- Default to flat, solid-color backgrounds — avoid gradients and blurred overlays.
- Depth is created through hard offset shadows and thick borders, not transparency or blur.
- Decorative elements should be bold and graphic: geometric shapes, color blocks, thick outlines — not subtle textures or gradients.
- Every decorative element must serve a compositional purpose (depth, separation, or emphasis). No purely ornamental effects competing with content.

## Must

- All sections: consistent 96px vertical padding
- All containers: max-width 1152px, centered, 24px horizontal padding
- Section headers: 48px or 64px bottom margin
- Consistent vertical rhythm, no crowded sections
- Layouts readable and properly spaced on both desktop and mobile

---

## Source file: `lists.md`

# Lists

> Dependencies: `colors.md`

## Core Specs

- Item spacing: 16px vertical gap between list items
- Text: body color

## List Icons

- Size: 20x20px
- Prevent squishing: no shrink
- Spacing: 6px right margin between icon and text
- Active/featured icon: fg-brand color
- Neutral icon: body color

## Inactive / Disabled Items

Strikethrough text with body color decoration on the list item.

## Pattern

Vertical flex list with 16px gap. Each item is a flex row with centered alignment — icon (20x20, no-shrink, 6px right margin) followed by a span of body-colored text.

---

## Source file: `modals.md`

# Modals

> Dependencies: `colors.md`, `radius.md`, `shadows.md`, `buttons.md`, `inputs.md`

## Core Specs

### Overlay (Backdrop)
- Fixed, covers full screen
- Z-index: 40
- Background: black at 50% opacity
- No backdrop blur — keep it flat and bold

### Content Container
- Background: neutral-primary (#FFFFFF in light)
- Radius: 0px (base)
- Shadow: shadow-xl (hard offset: `10px 10px 0 1px`)
- Border: 2px solid border-default (black in light mode)
- Padding: 20px

## Anatomy

### Header
- Bottom border: 2px solid border-default
- Top corners: 0px
- Title: 20px, bold weight (700), heading color
- Close button: Ghost variant from `buttons.md`, 6px padding

### Body
- Vertical padding: 24px
- Vertical spacing between elements: 24px
- Text: 16px, 1.625 line-height, body color

### Footer
- Top border: 2px solid border-default
- Bottom corners: 0px

## Variants

### Default (Information)
Standard header + body + footer with primary/secondary action buttons.

### Pop-up (Confirmation)
Centered text, prominent icon, reduced padding:
- Body: 24px padding, text centered
- Icon: centered, 16px bottom margin, 48x48px, gray color

### Form Modal
Body contains inputs following `inputs.md`. Vertical spacing between form elements: 16px.

## Rules

- Backdrop covers full screen with fixed positioning, no blur
- Content: neutral-primary background, 0px radius, 2px border, shadow-xl (hard offset)
- Header/Footer separated by 2px border-default borders
- Close button must be present and functional
- Accessibility: `role="dialog"`, implement focus trap in code
- Dark mode automatic via token system

---

## Source file: `pagination.md`

# Pagination

> Dependencies: `colors.md`, `radius.md`

## Container

Font: 14px. Items displayed as flex with -1px overlap for seamless borders.

## Pagination Item

- Layout: flex, centered both axes
- Size: 36x36px (or 40x40px)
- Text: body color, semibold weight
- Background: neutral-secondary-medium
- Border: 2px solid border-default (black in light mode)
- Hover: neutral-tertiary-medium background, heading text
- Focus: no outline
- Overlap: -2px left margin

## Previous / Next Buttons

- Horizontal padding: 12px, height: 36px
- First item: 0px radius on inline-start side
- Last item: 0px radius on inline-end side

## Active Page Item

- Text: fg-brand color
- Background: neutral-tertiary-medium
- Hover text: fg-brand (stays same)

## Rules

- Display as flex with -2px child overlap for seamless borders
- Items: neutral-secondary-medium background, 2px border-default border, body text
- Active: fg-brand text, neutral-tertiary-medium background
- First item: sharp start, Last item: sharp end
- All items need hover and focus states

---

## Source file: `radios-checkboxes-toggle.md`

# Radios, Checkboxes & Toggles

> Dependencies: `colors.md`, `radius.md`

## Checkbox

- Size: 16x16px
- Radius: 0px
- Border: 2px solid border-default (black in light mode)
- Background: neutral-primary-soft
- Focus ring: 2px, brand-soft

### Disabled
- Border: 2px solid border-light
- Text: fg-disabled

## Radio

- Size: 16x16px
- Radius: fully rounded
- Border: 2px solid border-default (black in light mode)
- Background: neutral-primary-soft
- Focus ring: 2px, brand-soft
- Checked: border-brand, indicator: neutral-primary color

### Disabled
- Border: 2px solid border-light-medium
- Text: fg-disabled

Group all radio items under the same `name` attribute.

## Toggle

### Track
- Fully rounded
- Background: neutral-quaternary
- Border: 2px solid border-default
- Focus-within ring: 2px, brand-soft
- Checked track: brand background
- Disabled track: neutral-tertiary background

### Thumb
- Fully rounded
- Background: white
- Border: 2px solid border-default

### Disabled
- Track: neutral-tertiary background
- Label: fg-disabled text

## Rules

- All selection inputs must have `id` matching label `htmlFor`
- Focus states use the appropriate brand token for each control type
- Disabled states: no hover/focus interaction

---

## Source file: `radius.md`

# Border Radius

> Neobrutalism defaults to sharp corners (0px). Rounded variants exist for specific use cases like pills and avatars.

| Token | Value | Default usage |
|---|---|---|
| base | 0px | Buttons, cards, inputs, modals, sections |
| default | 0px | Badges, tooltips, dropdown items, small controls |
| sm | 0px | Checkboxes, tiny elements |
| full | 9999px | Pills, avatars, toggles, dot indicators |

## Rules

- 0px is the default radius across the product — sharp corners are the neobrutalism signature
- Never use arbitrary radius values outside this scale
- Radius must be consistent within each component family
- Use `full` (9999px) only for explicitly pill-shaped or circular elements (avatars, toggles, pill badges)

---

## Source file: `shadows.md`

# Shadows

> Neobrutalism uses hard offset shadows with no blur. The shadow color matches the border token (black in light mode, dark gray in dark mode).

| Token | CSS value |
|---|---|
| shadow-2xs | `1px 1px 0 0 var(--color-border-default)` |
| shadow-xs | `2px 2px 0 0 var(--color-border-default)` |
| shadow-sm | `3px 3px 0 0 var(--color-border-default)` |
| shadow-md | `4px 4px 0 0 var(--color-border-default)` |
| shadow-lg | `6px 6px 0 0 var(--color-border-default)` |
| shadow-xl | `10px 10px 0 1px var(--color-border-default)` |
| shadow-2xl | `16px 16px 0 1px var(--color-border-default)` |

## Component Mapping

| Component type | Token |
|---|---|
| Subtle separators, tiny UI details | shadow-2xs or shadow-xs |
| Inputs, buttons, small controls, lightweight cards | shadow-xs or shadow-sm |
| Standard cards, popovers, dropdowns | shadow-md |
| Prominent cards, sticky surfaces | shadow-lg |
| Modals, high-priority overlays | shadow-xl |
| Hero overlays, top-level emphasis (sparingly) | shadow-2xl |

## Rules

- Use only these tokens — no custom box-shadow values
- All shadows are hard offset (no blur radius, no spread except xl/2xl)
- Shadow color always uses the border-default token for automatic light/dark handling
- Keep elevation steps intentional; avoid jumping multiple levels
- Components in the same family share the same baseline elevation
- Hover/focus on interactive elevated elements: step up by one level (e.g. shadow-sm → shadow-md)
- Never stack multiple shadow tokens on one element
- Never use shadow-xl/shadow-2xl for dense list items or body containers

---

## Source file: `sidebars.md`

# Sidebars

> Dependencies: `colors.md`, `radius.md`, `typography.md`, `badges.md`, `alerts.md`

## Core Specs

- Background: neutral-primary-soft
- Right border: 2px solid border-default (for left-sidebar); left border for right-sidebar
- Width: 256px

## Anatomy

### Outer Container
Hidden on mobile, visible at small breakpoint. Needs a toggle/trigger for mobile.

### Inner Wrapper
- Full height, vertical scroll overflow
- Padding: 12px horizontal, 16px vertical

### Navigation List
- Vertical spacing: 8px between items
- Font weight: semibold

### Navigation Item
- Layout: flex, vertically centered
- Padding: 8px horizontal, 8px vertical
- Text: heading color
- Radius: 0px (base)
- Hover: neutral-secondary-medium background
- Transition: colors
- Icon: 20x20px, body color, hover → heading color, 75ms transition
- Label: 12px left margin from icon

### Active Item
- Background: neutral-secondary-strong
- Text: fg-brand-strong

### Separator
- 16px top padding, 16px top margin
- Top border: 2px solid border-default
- 8px vertical spacing below

### Bottom CTA / Card
- Padding: 16px
- Top margin: 24px
- Radius: 0px (base)
- Background: brand-softer
- Border: 2px solid border-brand-subtle
- Can also use any alert variant from `alerts.md`

## Rules

- Responsive: hidden on mobile with a trigger mechanism
- Icons: 20x20px, body color (hover: heading color)
- Multi-level menus: indent with 44px left padding
- Spacing follows 8px grid
- Only neutral, brand, or status tokens — no arbitrary colors

---

## Source file: `tables.md`

# Tables

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Wrapper

- Horizontal scroll overflow
- Background: neutral-primary-soft
- Radius: 0px (base)
- Border: 2px solid border-default (black in light mode)
- Shadow: shadow-sm (hard offset: `3px 3px 0 0`)

## Table Element

- Full width, left-aligned text (right-aligned for RTL)
- Font: 14px, body color

## Table Head

- Font: 14px, body color, semibold weight
- Background: neutral-secondary-soft
- Bottom border: 2px solid border-default
- Cell padding: 24px horizontal, 12px vertical

## Table Body

- Row background: neutral-primary
- Row bottom border: 2px solid border-default (omit on last row to avoid doubling with wrapper border)
- Row hover: neutral-secondary-soft background (optional)
- Row header: semibold weight, heading color, no-wrap
- Cell padding: 24px horizontal, 16px vertical

## Rules

- Wrapper must have horizontal scroll overflow for responsive scrolling
- Last row: omit bottom border to avoid doubling with wrapper border
- Row headers: always `scope="row"` for semantic structure
- Hover on rows is optional
- No arbitrary hex codes — use token colors only

---

## Source file: `tabs.md`

# Tabs

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Core Specs

- Typography: 14px, semibold weight, body color
- Transitions: all properties, 100ms

## Variants

### 1. Underline (Default)

**Wrapper:** bottom border, 2px solid border-default

**Tab Item:**
- Padding: 16px horizontal, 16px vertical
- Bottom border: 3px, transparent
- Top corners: 0px radius
- Transition: colors, 100ms

| State | Appearance |
|---|---|
| Active | fg-brand text, border-brand bottom border |
| Inactive | transparent bottom border; hover → heading text, border-default-strong bottom border |
| Disabled | fg-disabled text, not-allowed cursor |

### 2. Pills

**Tab Item:**
- Padding: 16px horizontal, 10px vertical
- Radius: 0px (base)
- Font weight: semibold
- Border: 2px solid border-default
- Transition: all, 100ms

| State | Appearance |
|---|---|
| Active | brand background, black text, shadow-sm (hard offset) |
| Inactive | body text; hover → neutral-secondary-soft background, heading text |
| Disabled | fg-disabled text, not-allowed cursor |

### 3. Full Width

Children overlap with -1px left margin on all except first.

**Tab Item:**
- Full width, centered text
- Padding: 16px horizontal, 16px vertical
- Background: neutral-primary-soft
- Border: 2px solid border-default
- Transition: colors, 100ms
- Hover: neutral-secondary-medium background, heading text

| State | Appearance |
|---|---|
| Active | neutral-secondary-soft background, fg-brand text |
| First item | sharp start (0px) |
| Last item | sharp end (0px) |

## Tabs with Icons

- Icon size: 16x16px or 20x20px
- Spacing: 8px right margin
- Layout: inline-flex, centered
- Icons inherit the text color of the tab state

---

## Source file: `tooltips-popovers.md`

# Tooltips & Popovers

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Tooltips

### Core Specs
- Padding: 12px horizontal, 8px vertical
- Font: 14px, semibold weight
- Radius: 0px (default)
- Shadow: shadow-xs (hard offset: `2px 2px 0 0`)
- Border: 2px solid border-default
- Transition: opacity, 200ms

### Dark (Default)
- Background: dark (#000000)
- Text: white
- Border: 2px solid border-default

### Light
- Background: neutral-primary-medium
- Text: heading color
- Border: 2px solid border-default

## Popovers

### Core Specs
- Background: neutral-primary
- Radius: 0px (base)
- Shadow: shadow-md (hard offset: `4px 4px 0 0`)
- Border: 2px solid border-default
- Transition: opacity, 200ms

### Header / Title
- Padding: 12px horizontal, 8px vertical
- Background: neutral-secondary-soft
- Bottom border: 2px solid border-default
- Font: 14px, semibold weight, heading color

### Body / Content
- Standard: 12px horizontal, 8px vertical padding; 14px, body color
- Rich: 16px padding; 14px, body color

## Arrows

- Size: 8x8px rotated 45deg
- Color must match the background of the tooltip/popover variant
- Arrow must also have matching 2px border on exposed sides

## Rules

- Tooltips: 0px radius, 2px border
- Popovers: 0px radius, 2px border
- Dark tooltips: dark background, white text
- Light tooltips/popovers: semantic neutral background + border tokens
- Arrows match parent background color with matching border

---

## Source file: `typography.md`

# Typography

> Dependencies: `colors.md`

## Core Rules

- **Heading font:** Archivo Black, sans-serif — configured at app level via `--font-head`, never override
- **Body font:** Space Grotesk, sans-serif — configured at app level via `--font-sans`, never override
- **Headings:** bold weight (700–900), heading text color, Archivo Black
- **Body copy:** Space Grotesk, body text color, never use brand color for paragraphs longer than one sentence
- **Semantic HTML:** Use `h1`–`h6` in order, never skip levels

## Heading Scale

### Desktop

| Element | Size | Line-height | Letter-spacing | Margin-bottom |
|---|---|---|---|---|
| `h1` | 64px | 1 | -1px | 24px |
| `h2` | 48px | 1.1 | -0.5px | — |
| `h3` | 36px | 1.15 | — | — |
| `h4` | 30px | 1.2 | — | — |
| `h5` | 24px | 1.3 | — | — |
| `h6` | 20px | 1.25 | — | — |

### Responsive

| Element | Tablet (≥768px) | Mobile (default) |
|---|---|---|
| `h1` | 44px | 36px |
| `h2` | 38px | 30px |
| `h3` | 30px | 24px |
| `h4` | 26px | 22px |
| `h5` | 22px | 20px |
| `h6` | 18px | 18px |

Mobile-first: start with mobile sizes, scale up at tablet and desktop breakpoints.

Never reduce line-height below 1.1 for any heading.

## Paragraphs

### Leading Paragraph
- Size: 20px
- Weight: normal (400)
- Font: Space Grotesk
- Color: body
- Line-height: 1.7
- Max width: ~70 characters

### Normal Paragraph
- Size: 16px
- Weight: normal (400)
- Font: Space Grotesk
- Color: body
- Line-height: 1.7
- Max width: ~65 characters

### Small Supporting Copy
- Size: 14px
- Weight: normal (400)
- Font: Space Grotesk
- Color: body
- Line-height: 1.6
- Use only for helper text, legal text, captions, metadata.

## UI Labels

| Context | Size | Weight |
|---|---|---|
| Button labels | 16px | 600 (semibold) |
| Input labels | 14px or 16px | 600 (semibold) |
| Captions / meta / badges | 12px or 14px | 500 (medium) |

Do not apply paragraph line-height (1.7) to control labels.

## Links

- **Inline links:** Same size as surrounding text, fg-brand color, underline, hover → no underline
- **CTA links:** fg-brand color, semibold weight, underline, hover → no underline

## Emphasis

- `<strong>` for high-priority emphasis in body text
- `<em>` for tone emphasis only, not visual hierarchy
- All-caps only for short labels: uppercase, 0.8px letter-spacing, 12px or 14px

## Dark Mode

Hierarchy stays identical. Only color tokens change (automatic via CSS custom properties). Size, weight, and spacing remain constant.