# Border Radius

> {{DESIGN_STYLE_NAME}} defaults to sharp corners ({{RADIUS_DEFAULT}}). Rounded variants exist for specific use cases like pills and avatars.

| Token   | Value  | Default usage                                    |
| ------- | ------ | ------------------------------------------------ |
| base    | {{RADIUS_DEFAULT}}    | Buttons, cards, inputs, modals, sections         |
| default | {{RADIUS_DEFAULT}}    | Badges, tooltips, dropdown items, small controls |
| sm      | {{RADIUS_DEFAULT}}    | Checkboxes, tiny elements                        |
| full    | 9999px | Pills, avatars, toggles, dot indicators          |

## Rules

- {{RADIUS_DEFAULT}} is the default radius across the product — sharp corners are the {{DESIGN_STYLE_NAME}} signature
- Never use arbitrary radius values outside this scale
- Radius must be consistent within each component family
- Use `full` (9999px) only for explicitly pill-shaped or circular elements (avatars, toggles, pill badges)
