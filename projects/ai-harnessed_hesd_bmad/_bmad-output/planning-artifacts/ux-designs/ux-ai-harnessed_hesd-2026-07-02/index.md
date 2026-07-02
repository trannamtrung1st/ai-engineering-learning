---
title: HESD Attendance UX
status: final
created: 2026-07-02
updated: 2026-07-02
format: sharded
entry_point: true
prd_ref: ../../prds/prd-ai-harnessed_hesd-2026-07-02/prd/index.md
design_system_ref: ../../../../docs/ui-ux/design-system/
spines:
  - design/index.md
  - experience/index.md
---

# UX: HESD Workshop Digital Attendance System

> **Sharded UX.** Read this index first, then load only the section files you need. Visual identity in `design/`; behavior and IA in `experience/`.

## Spines

| Spine | Index | Load when |
|-------|-------|-----------|
| **DESIGN** (how it looks) | [design/index.md](./design/index.md) | UI implementation, tokens, components |
| **EXPERIENCE** (how it works) | [experience/index.md](./experience/index.md) | IA, flows, states, accessibility |

## Quick routing

| Task | Start here |
|------|------------|
| Build student check-in UI | `experience/10-flow-uj3-trang-checkin.md` + `design/7-components.md` |
| Build QR Display | `experience/9-flow-uj2-minh-open-session.md` + `design/7-components.md` |
| Build admin CSV import | `experience/8-flow-uj1-linh-provision.md` + `experience/3-component-patterns.md` |
| Build live dashboard | `experience/3-component-patterns.md` + `experience/4-state-patterns.md` |
| Token lookup | `design/index.md` (YAML frontmatter) |
| PRD cross-ref | [PRD index](../../prds/prd-ai-harnessed_hesd-2026-07-02/prd/index.md) |

## Sources

- `_bmad-output/planning-artifacts/prds/prd-ai-harnessed_hesd-2026-07-02/`
- `_bmad-output/project-context.md`
- `raw/initial-idea.md`
- `docs/ui-ux/design-system/`
