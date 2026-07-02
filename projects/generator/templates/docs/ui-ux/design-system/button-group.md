# Button Groups

> Dependencies: `buttons.md`, `colors.md`, `radius.md`

## Core Specs

- **Wrapper:** inline-flex, {{RADIUS_DEFAULT}} radius, shadow-sm ({{SHADOW_STYLE}})
- **Children overlap:** -2px left margin on all except first button
- **Buttons inside the group must NOT have individual shadows.** Only the wrapper has a shadow.

## Anatomy

### Wrapper
- Display: inline-flex
- Radius: 0px
- Shadow: shadow-sm
- Border: {{BORDER_STYLE}}

### First Button
- {{RADIUS_DEFAULT}} radius on inline-start side only, 0 on inline-end

### Middle Button(s)
- No radius (0 on all corners)

### Last Button
- {{RADIUS_DEFAULT}} radius on inline-end side only, 0 on inline-start

### All buttons except first
- -2px left margin to overlap borders

## Rules

- Buttons inside groups follow all styles from `buttons.md` (background, border, focus rings) except individual shadows
- Icon-only buttons: 16x16px icon, match height of text buttons
