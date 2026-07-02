# Avatars

> Dependencies: `colors.md`, `radius.md`

## Core Specs

- **Circular shape:** fully rounded (9999px)
- **Rounded square shape:** {{RADIUS_DEFAULT}} radius
- **Default size:** 40x40px
- **Image fit:** cover

## Sizes

| Size        | Dimensions | Radius |
| ----------- | ---------- | ------ |
| Extra Small | 18x18px    | {{RADIUS_DEFAULT}}    |
| Small       | 24x24px    | {{RADIUS_DEFAULT}}    |
| Base        | 32x32px    | {{RADIUS_DEFAULT}}    |
| Large       | 44x44px    | {{RADIUS_DEFAULT}}    |
| XL          | 56x56px    | {{RADIUS_DEFAULT}}    |
| 2XL         | 64x64px    | {{RADIUS_DEFAULT}}    |

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
