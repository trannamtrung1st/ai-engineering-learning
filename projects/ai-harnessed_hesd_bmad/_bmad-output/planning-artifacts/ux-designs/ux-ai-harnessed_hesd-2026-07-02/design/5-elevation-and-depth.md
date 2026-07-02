# Elevation & Depth

Hard offset shadows only — no blur. Inherits `docs/ui-ux/design-system/shadows.md`.

| Level | Token | Use |
|---|---|---|
| Controls | shadow-sm (`3px 3px`) | Buttons, inputs |
| Cards / tables | shadow-md (`4px 4px`) | Cards, attendance table container |
| QR Display | shadow-xl (`10px 10px`) | Projected QR frame |
| Modals | shadow-xl | Manual Override dialog, CSV import results |

Interactive lift: hover steps up one shadow level (-1px translate); active press steps down (+2px translate, shadow-2xs). Transitions 100ms.
