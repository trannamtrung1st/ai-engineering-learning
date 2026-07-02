---
name: HESD Attendance
description: Neobrutalism visual identity for the HESD Workshop Digital Attendance System — bold, legible at distance, honest about validation steps.
format: sharded
entry_point: true
status: final
updated: 2026-07-02
sections:
  - 1-brand-and-style.md
  - 2-colors.md
  - 3-typography.md
  - 4-layout-and-spacing.md
  - 5-elevation-and-depth.md
  - 6-shapes.md
  - 7-components.md
  - 8-dos-and-donts.md
colors:
  brand: '#FFDB33'
  brand-strong: '#FFCC00'
  brand-soft: '#FFF3C4'
  neutral-primary: '#FFFFFF'
  neutral-secondary: '#F5F5F0'
  neutral-tertiary: '#EBEBEB'
  neutral-primary-dark: '#1A1A1A'
  neutral-secondary-dark: '#242424'
  heading: '#000000'
  heading-dark: '#F5F5F5'
  body: '#5A5A5A'
  body-dark: '#A0A0A0'
  border-default: '#000000'
  border-default-dark: '#3A3A3A'
  success: '#16A34A'
  danger: '#E63946'
  warning: '#F59E0B'
  disabled: '#F5F5F5'
  disabled-dark: '#242424'
typography:
  display:
    fontFamily: 'Archivo Black'
    fontSize: 64px
    fontWeight: '900'
    lineHeight: '1'
    letterSpacing: '-1px'
  display-mobile:
    fontFamily: 'Archivo Black'
    fontSize: 36px
    fontWeight: '900'
    lineHeight: '1'
    letterSpacing: '-0.5px'
  h2:
    fontFamily: 'Archivo Black'
    fontSize: 48px
    fontWeight: '800'
    lineHeight: '1.1'
  h3:
    fontFamily: 'Archivo Black'
    fontSize: 30px
    fontWeight: '700'
    lineHeight: '1.15'
  body:
    fontFamily: 'Space Grotesk'
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.7'
  body-large:
    fontFamily: 'Space Grotesk'
    fontSize: 20px
    fontWeight: '400'
    lineHeight: '1.7'
  label:
    fontFamily: 'Space Grotesk'
    fontSize: 14px
    fontWeight: '600'
    lineHeight: '1.4'
  button:
    fontFamily: 'Space Grotesk'
    fontSize: 16px
    fontWeight: '600'
    lineHeight: '1'
  caption:
    fontFamily: 'Space Grotesk'
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1.4'
  qr-countdown:
    fontFamily: 'Archivo Black'
    fontSize: 48px
    fontWeight: '900'
    lineHeight: '1'
rounded:
  default: 0px
  sm: 0px
  full: 9999px
spacing:
  '1': 8px
  '2': 16px
  '3': 24px
  '4': 48px
  '5': 64px
  '6': 96px
  container-max: 1152px
  container-padding: 24px
components:
  button-primary:
    background: '{colors.brand}'
    foreground: '{colors.heading}'
    border: '2px solid {colors.border-default}'
    shadow: '3px 3px 0 0 {colors.border-default}'
    radius: '{rounded.default}'
  button-danger:
    background: '{colors.danger}'
    foreground: '#FFFFFF'
    border: '2px solid {colors.border-default}'
    shadow: '3px 3px 0 0 {colors.border-default}'
    radius: '{rounded.default}'
  card:
    background: '{colors.neutral-primary}'
    border: '2px solid {colors.border-default}'
    shadow: '4px 4px 0 0 {colors.border-default}'
    radius: '{rounded.default}'
  input:
    background: '{colors.neutral-primary}'
    border: '2px solid {colors.border-default}'
    focus-border: '3px solid {colors.border-default}'
    shadow: '2px 2px 0 0 {colors.border-default}'
    radius: '{rounded.default}'
  status-present:
    background: '{colors.success}'
    foreground: '#FFFFFF'
  status-absent:
    background: '{colors.neutral-tertiary}'
    foreground: '{colors.heading}'
  status-failed:
    background: '{colors.danger}'
    foreground: '#FFFFFF'
  status-override:
    background: '{colors.warning}'
    foreground: '{colors.heading}'
  qr-display-frame:
    background: '{colors.neutral-primary}'
    border: '3px solid {colors.border-default}'
    shadow: '10px 10px 0 1px {colors.border-default}'
    radius: '{rounded.default}'
---

# DESIGN: HESD Attendance

> **Sharded DESIGN spine.** Tokens live in this file's YAML frontmatter. Load section files for prose rationale. Behavioral rules live in `../experience/`.

## Sections

| Section | File | Load when |
|---------|------|-----------|
| 1. Brand & Style | [1-brand-and-style.md](./1-brand-and-style.md) | Aesthetic posture, inheritance |
| 2. Colors | [2-colors.md](./2-colors.md) | Palette usage rules |
| 3. Typography | [3-typography.md](./3-typography.md) | Type scale, hierarchy |
| 4. Layout & Spacing | [4-layout-and-spacing.md](./4-layout-and-spacing.md) | Grid, margins, breakpoints |
| 5. Elevation & Depth | [5-elevation-and-depth.md](./5-elevation-and-depth.md) | Shadows, lift |
| 6. Shapes | [6-shapes.md](./6-shapes.md) | Radius rules |
| 7. Components | [7-components.md](./7-components.md) | Visual component specs |
| 8. Do's and Don'ts | [8-dos-and-donts.md](./8-dos-and-donts.md) | Hard visual rules |
