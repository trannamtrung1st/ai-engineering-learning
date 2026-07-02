---
title: HESD Workshop Digital Attendance System
status: final
created: 2026-07-02
updated: 2026-07-02
format: sharded
entry_point: true
spec_ref: ../../specs/spec-hesd-workshop-attendance/SPEC.md
prd_ref: ../../prds/prd-ai-harnessed_hesd-2026-07-02/prd/index.md
ux_ref: ../../ux-designs/ux-ai-harnessed_hesd-2026-07-02/index.md
spines:
  - spine/index.md
  - implementation/index.md
---

# Architecture: HESD Workshop Digital Attendance System

> **Sharded architecture.** Read this index first, then load only the section files you need. Invariants in `spine/`; build order and agent routing in `implementation/`.

## Spines

| Spine | Index | Load when |
|-------|-------|-----------|
| **SPINE** (what must not diverge) | [spine/index.md](./spine/index.md) | AD lookup, stack, entity model, capability map |
| **IMPLEMENTATION** (how to build) | [implementation/index.md](./implementation/index.md) | Cold start, build phases, API surface, domain modules |

## Quick routing

| Task | Start here |
|------|------------|
| Orient / paradigm | `spine/1-design-paradigm.md` |
| Check-in rules (AD-4–6, AD-10) | `spine/3-ad-check-in.md` |
| Auth + roles (AD-7, AD-9) | `spine/4-ad-auth-security.md` |
| Realtime + audit (AD-8, AD-11) | `spine/5-ad-realtime-audit.md` |
| Stack + versions | `spine/8-stack.md` |
| DB schema / source tree | `spine/9-structural-seed.md` |
| CAP → module map | `spine/10-capability-map.md` |
| Agent cold start | `implementation/2-cold-start.md` |
| Build order (phases 1–10) | `implementation/3-build-order.md` |
| Domain module list | `implementation/5-domain-modules.md` |
| API routes | `implementation/6-api-surface.md` |
| PRD cross-ref | [PRD index](../../prds/prd-ai-harnessed_hesd-2026-07-02/prd/index.md) |
| UX cross-ref | [UX index](../../ux-designs/ux-ai-harnessed_hesd-2026-07-02/index.md) |

## Sources

- `_bmad-output/specs/spec-hesd-workshop-attendance/SPEC.md`
- `_bmad-output/planning-artifacts/prds/prd-ai-harnessed_hesd-2026-07-02/`
- `_bmad-output/planning-artifacts/ux-designs/ux-ai-harnessed_hesd-2026-07-02/`
- `_bmad-output/project-context.md`
