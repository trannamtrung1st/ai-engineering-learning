# Tooltips & Popovers

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Tooltips

### Core Specs
- Padding: 12px horizontal, 8px vertical
- Font: 14px, semibold weight
- Radius: {{RADIUS_DEFAULT}} (default)
- Shadow: shadow-xs ({{SHADOW_STYLE}}: `2px 2px 0 0`)
- Border: {{BORDER_STYLE}}
- Transition: opacity, 200ms

### Dark (Default)
- Background: dark (#000000)
- Text: white
- Border: {{BORDER_STYLE}}

### Light
- Background: neutral-primary-medium
- Text: heading color
- Border: {{BORDER_STYLE}}

## Popovers

### Core Specs
- Background: neutral-primary
- Radius: {{RADIUS_DEFAULT}} (base)
- Shadow: shadow-md ({{SHADOW_STYLE}}: `4px 4px 0 0`)
- Border: {{BORDER_STYLE}}
- Transition: opacity, 200ms

### Header / Title
- Padding: 12px horizontal, 8px vertical
- Background: neutral-secondary-soft
- Bottom border: {{BORDER_STYLE}}
- Font: 14px, semibold weight, heading color

### Body / Content
- Standard: 12px horizontal, 8px vertical padding; 14px, body color
- Rich: 16px padding; 14px, body color

## Arrows

- Size: 8x8px rotated 45deg
- Color must match the background of the tooltip/popover variant
- Arrow must also have matching 2px border on exposed sides

## Rules

- Tooltips: {{RADIUS_DEFAULT}} radius, 2px border
- Popovers: {{RADIUS_DEFAULT}} radius, 2px border
- Dark tooltips: dark background, white text
- Light tooltips/popovers: semantic neutral background + border tokens
- Arrows match parent background color with matching border
