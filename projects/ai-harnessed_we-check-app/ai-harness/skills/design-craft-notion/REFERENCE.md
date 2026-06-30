# Notion Design Reference (trimmed)

Source: [VoltAgent/awesome-design-md `notion/DESIGN.md`](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/notion/DESIGN.md)

**We Check maps DESIGN.md tokens to CSS variables in [04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md).**

## Spacing rhythm (DESIGN.md → CSS var)

| DESIGN.md | px | CSS variable |
| --- | --- | --- |
| `spacing.xxs` | 4 | `--space-1` |
| `spacing.xs` | 8 | `--space-2` |
| `spacing.sm` | 12 | `--space-3` |
| `spacing.md` | 16 | `--space-4` |
| `spacing.lg` | 20 | `--space-5` |
| `spacing.xl` | 24 | `--space-6` |
| `spacing.xxl` | 32 | `--space-8` |

Section gaps between page header and toolbar: `--space-6` (24 px). Between toolbar and table: `--space-4` (16 px).

## Elevation (DESIGN.md levels → CSS)

| Level | Notion shadow | CSS token |
| --- | --- | --- |
| 0 (flat) | hairline border only | `--color-border-default` |
| 1 (subtle) | `rgba(15,15,15,0.04) 0px 1px 2px` | `--shadow-sm` |
| 2 (card) | `rgba(15,15,15,0.08) 0px 4px 12px` | `--shadow-md` |
| 4 (modal) | `rgba(15,15,15,0.16) 0px 16px 48px -8px` | `--shadow-lg` |

## Border radius (DESIGN.md → CSS)

| DESIGN.md | px | CSS variable |
| --- | --- | --- |
| `rounded.xs` | 4 | `--radius-xs` |
| `rounded.sm` | 6 | `--radius-sm` |
| `rounded.md` | 8 | `--radius-md` |
| `rounded.lg` | 12 | `--radius-lg` |

Nav active pill: `--radius-md`. Cards: `--radius-lg`. Buttons: `--radius-md` (rectangular, not pills).

## Typography density (Inter)

| Role | DESIGN.md token | CSS |
| --- | --- | --- |
| Page title | `heading-3` 28 px | `text-h1` / `text-display` |
| Section label | `body-sm-medium` 14 px | `text-label` |
| Table body | `body-sm` 14 px | `text-small` |
| Body | `body-md` 16 px | `text-body` |
| Caption / meta | `caption` 13 px | `text-small`, `--color-text-muted` |

## Sidebar density notes

- Icon size 16–18 px inline with label
- Group label: uppercase micro caption optional for admin settings group only
- Scrollable nav region; fixed header with product name

## Filter toolbar notes

- Search input height matches button height (min 36 px desktop, 44 px mobile student routes)
- Filter chips: pill `--radius-full` with `--color-surface-muted` background when inactive
- Active filter chip: `--color-primary-50` background
