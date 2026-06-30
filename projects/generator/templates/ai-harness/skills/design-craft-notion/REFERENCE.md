# Design Craft Reference (stub)

Customize per product. Token values always come from [04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md); visual spec from [DESIGN.md](../../../docs/ui-ux/DESIGN.md) when present.

## Spacing rhythm (DESIGN.md → CSS var)

| DESIGN.md key | Typical px | CSS variable (product) |
| --- | --- | --- |
| `spacing.xs` | 4 | `--spacing-xs` |
| `spacing.sm` | 8 | `--spacing-sm` |
| `spacing.md` | 12 | `--spacing-md` |
| `spacing.lg` | 16 | `--spacing-lg` |
| `spacing.xl` | 24 | `--spacing-xl` |

## Elevation (DESIGN.md levels → CSS)

| Level | Use | CSS variable (product) |
| --- | --- | --- |
| `elevation.card` | Tables, panels | `--shadow-card` |
| `elevation.dropdown` | Menus, popovers | `--shadow-dropdown` |

## Border radius (DESIGN.md → CSS)

| DESIGN.md key | Typical px | CSS variable (product) |
| --- | --- | --- |
| `radius.sm` | 4 | `--radius-sm` |
| `radius.md` | 6 | `--radius-md` |
| `radius.lg` | 8 | `--radius-lg` |
| `radius.full` | 9999 | `--radius-full` |

Replace this stub with product-specific mappings during harness setup.
