# Tabs

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Core Specs

- Typography: 14px, semibold weight, body color
- Transitions: all properties, 100ms

## Variants

### 1. Underline (Default)

**Wrapper:** bottom border, {{BORDER_STYLE}}

**Tab Item:**
- Padding: 16px horizontal, 16px vertical
- Bottom border: 3px, transparent
- Top corners: {{RADIUS_DEFAULT}} radius
- Transition: colors, 100ms

| State    | Appearance                                                                           |
| -------- | ------------------------------------------------------------------------------------ |
| Active   | fg-brand text, border-brand bottom border                                            |
| Inactive | transparent bottom border; hover → heading text, border-default-strong bottom border |
| Disabled | fg-disabled text, not-allowed cursor                                                 |

### 2. Pills

**Tab Item:**
- Padding: 16px horizontal, 10px vertical
- Radius: {{RADIUS_DEFAULT}} (base)
- Font weight: semibold
- Border: {{BORDER_STYLE}}
- Transition: all, 100ms

| State    | Appearance                                                         |
| -------- | ------------------------------------------------------------------ |
| Active   | brand background, black text, shadow-sm ({{SHADOW_STYLE}})              |
| Inactive | body text; hover → neutral-secondary-soft background, heading text |
| Disabled | fg-disabled text, not-allowed cursor                               |

### 3. Full Width

Children overlap with -1px left margin on all except first.

**Tab Item:**
- Full width, centered text
- Padding: 16px horizontal, 16px vertical
- Background: neutral-primary-soft
- Border: {{BORDER_STYLE}}
- Transition: colors, 100ms
- Hover: neutral-secondary-medium background, heading text

| State      | Appearance                                       |
| ---------- | ------------------------------------------------ |
| Active     | neutral-secondary-soft background, fg-brand text |
| First item | sharp start ({{RADIUS_DEFAULT}})                                |
| Last item  | sharp end ({{RADIUS_DEFAULT}})                                  |

## Tabs with Icons

- Icon size: 16x16px or 20x20px
- Spacing: 8px right margin
- Layout: inline-flex, centered
- Icons inherit the text color of the tab state
