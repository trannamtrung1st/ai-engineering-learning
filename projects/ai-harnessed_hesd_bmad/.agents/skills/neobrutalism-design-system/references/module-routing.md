# Module Routing

Load modules from `{workflow.design_system_path}/` before implementing UI. Read the index at `SKILL.md` in that folder for the full module list.

## Always read first (any UI work)

`layout.md`, `typography.md`, `colors.md`, `borders.md`, `radius.md`, `shadows.md`

## By screen or task

| Task | Modules |
| --- | --- |
| Landing or marketing page | foundations above + `buttons.md`, `cards.md`, `content.md` |
| Auth or check-in form | foundations above + `inputs.md`, `buttons.md`, `alerts.md` |
| Dashboard or admin table | foundations above + `tables.md`, `badges.md`, `tabs.md`, `cards.md`, `buttons.md` |
| QR display or session screen | foundations above + `cards.md`, `badges.md`, `alerts.md`, `buttons.md` |
| Navigation shell | foundations above + `sidebars.md`, `tabs.md`, `buttons.md` |
| Modal or confirmation flow | foundations above + `modals.md`, `buttons.md`, `alerts.md` |
| Filter or settings panel | foundations above + `dropdown.md`, `radios-checkboxes-toggle.md`, `inputs.md` |
| Status or feedback only | foundations above + `alerts.md`, `badges.md`, `tooltips-popovers.md` |
| Data list (non-tabular) | foundations above + `lists.md`, `avatars.md`, `badges.md` |
| Paginated results | foundations above + `tables.md`, `pagination.md` |

## Cross-reference rule

When a component contains another, satisfy both modules. Examples: card with buttons → `cards.md` + `buttons.md`; form with alerts → `inputs.md` + `alerts.md`; table row actions → `tables.md` + `buttons.md`.
