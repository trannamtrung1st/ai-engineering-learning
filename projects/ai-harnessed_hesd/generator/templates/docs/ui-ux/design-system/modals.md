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
- Radius: {{RADIUS_DEFAULT}} (base)
- Shadow: shadow-xl ({{SHADOW_STYLE}}: `10px 10px 0 1px`)
- Border: {{BORDER_STYLE}} 
- Padding: 20px

## Anatomy

### Header
- Bottom border: {{BORDER_STYLE}}
- Top corners: 0px
- Title: 20px, bold weight (700), heading color
- Close button: Ghost variant from `buttons.md`, 6px padding

### Body
- Vertical padding: 24px
- Vertical spacing between elements: 24px
- Text: 16px, 1.625 line-height, body color

### Footer
- Top border: {{BORDER_STYLE}}
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
- Content: neutral-primary background, {{RADIUS_DEFAULT}} radius, 2px border, shadow-xl ({{SHADOW_STYLE}})
- Header/Footer separated by 2px border-default borders
- Close button must be present and functional
- Accessibility: `role="dialog"`, implement focus trap in code
- Dark mode automatic via token system
