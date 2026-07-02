# Buttons

> Dependencies: `colors.md`, `radius.md`, `shadows.md`

## Core Specs (every button except ghost and disabled)

- **Radius:** {{RADIUS_DEFAULT}} (base) or 9999px for pills
- **Border:** {{BORDER_STYLE}} 
- **Shadow:** shadow-sm ({{SHADOW_STYLE}}: `3px 3px 0 0`)
- **Hover shadow shift:** On hover, translate the button -1px up and -1px left and increase shadow to shadow-md (`4px 4px 0 0`) for a "lifted" feel
- **Active press:** On active/click, translate 2px right and 2px down and reduce shadow to shadow-2xs (`1px 1px 0 0`) for a "pressed" feel
- **Font weight:** 600 (semibold)
- **Font:** {{BODY_FONT}}
- **Box sizing:** border-box
- **Transition:** all 100ms

## Sizes

| Size           | Font size | Horizontal padding | Vertical padding |
| -------------- | --------- | ------------------ | ---------------- |
| Extra small    | 12px      | 12px               | 6px              |
| Small          | 14px      | 12px               | 8px              |
| Base (default) | 14px      | 16px               | 10px             |
| Large          | 16px      | 20px               | 12px             |
| Extra large    | 16px      | 24px               | 14px             |

## Variants

### Brand
- **Background:** brand token ({{PRIMARY_COLOR}})
- **Border:** {{BORDER_STYLE}}
- **Text:** black
- **Hover:** brand-strong background, lifted shadow
- **Focus ring:** 4px, brand-medium color
- **Shadow:** shadow-sm

### Secondary
- **Background:** neutral-secondary-medium
- **Border:** {{BORDER_STYLE}}
- **Text:** heading color
- **Hover:** neutral-tertiary-medium background, lifted shadow
- **Focus ring:** 4px, neutral-tertiary color
- **Shadow:** shadow-sm

### Tertiary
- **Background:** neutral-primary-soft
- **Border:** {{BORDER_STYLE}}
- **Text:** heading color
- **Hover:** neutral-secondary-medium background, lifted shadow
- **Focus ring:** 4px, neutral-tertiary-soft color
- **Shadow:** shadow-sm

### Success
- **Background:** success token
- **Border:** {{BORDER_STYLE}}
- **Text:** white
- **Hover:** success-strong background, lifted shadow
- **Focus ring:** 4px, success-medium color
- **Shadow:** shadow-sm

### Danger
- **Background:** danger token (#E63946)
- **Border:** {{BORDER_STYLE}}
- **Text:** white
- **Hover:** danger-strong background, lifted shadow
- **Focus ring:** 4px, danger-medium color
- **Shadow:** shadow-sm

### Warning
- **Background:** warning token
- **Border:** {{BORDER_STYLE}}
- **Text:** black
- **Hover:** warning-strong background, lifted shadow
- **Focus ring:** 4px, warning-medium color
- **Shadow:** shadow-sm

### Dark
- **Background:** dark token (#000000)
- **Border:** {{BORDER_STYLE}}
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
