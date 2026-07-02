# Foundation

| Dimension | Decision |
|---|---|
| Form factor | **Multi-surface:** Admin web + Instructor web (desktop/tablet, shared codebase); Student **mobile web** (phone, no native app) |
| UI system | Neobrutalism module at `docs/ui-ux/design-system/` — `../design/index.md` owns product-layer tokens and usage rules |
| Primary locale | **Vietnamese** for Student + Instructor UI copy; `[ASSUMPTION]` **English** for Admin UI |
| Stakes | Internal program tool — not regulated, not consumer-scale growth |
| Realtime | `[ASSUMPTION]` Polling ~3s on Instructor dashboard with live indicator; target ≤5s visibility per NFR |

`../design/index.md` is the visual identity reference. This spine owns IA, behavior, states, and journeys.
