---
name: HESD Workshop Digital Attendance System
type: architecture-spine
purpose: build-substrate
altitude: initiative
paradigm: split-stack-monorepo
scope: Full MVP — mobile-web attendance, admin/instructor/student surfaces, check-in validation, realtime dashboard, audit, CSV export
status: final
created: '2026-07-02'
updated: '2026-07-02'
format: sharded
entry_point: true
binds: [CAP-1, CAP-2, CAP-3, CAP-4, CAP-5, CAP-6, CAP-7, CAP-8, CAP-9, CAP-10]
sections:
  - 1-design-paradigm.md
  - 2-ad-foundation.md
  - 3-ad-check-in.md
  - 4-ad-auth-security.md
  - 5-ad-realtime-audit.md
  - 6-ad-deployment.md
  - 7-conventions.md
  - 8-stack.md
  - 9-structural-seed.md
  - 10-capability-map.md
  - 11-deferred.md
sources:
  - ../../../specs/spec-hesd-workshop-attendance/SPEC.md
  - ../../../planning-artifacts/prds/prd-ai-harnessed_hesd-2026-07-02/prd/index.md
  - ../../../planning-artifacts/ux-designs/ux-ai-harnessed_hesd-2026-07-02/index.md
  - ../../../../project-context.md
companions:
  - ../implementation/index.md
---

# Architecture Spine — HESD Workshop Digital Attendance System

> **Sharded spine.** Read this index first, then load only the section files you need. For check-in work start with `3-ad-check-in.md`. For scaffolding start with `implementation/2-cold-start.md`.

## Sections

| Section | File | Load when |
|---------|------|-----------|
| 1. Design Paradigm | [1-design-paradigm.md](./1-design-paradigm.md) | Layer model, dependency direction |
| 2. Foundation ADs | [2-ad-foundation.md](./2-ad-foundation.md) | AD-1–3, AD-15: split monorepo, starters, API mutation path |
| 3. Check-in ADs | [3-ad-check-in.md](./3-ad-check-in.md) | AD-4–6, AD-10: QR, validation, GPS |
| 4. Auth & Security ADs | [4-ad-auth-security.md](./4-ad-auth-security.md) | AD-7, AD-9, AD-13: roles, provisioning, data access |
| 5. Realtime & Audit ADs | [5-ad-realtime-audit.md](./5-ad-realtime-audit.md) | AD-8, AD-11 |
| 6. Deployment ADs | [6-ad-deployment.md](./6-ad-deployment.md) | AD-12, AD-14: compose local/integration + production envelope |
| 7. Conventions | [7-conventions.md](./7-conventions.md) | Naming, errors, dates, CSV, UI |
| 8. Stack | [8-stack.md](./8-stack.md) | Pinned versions |
| 9. Structural Seed | [9-structural-seed.md](./9-structural-seed.md) | Topology, ERD, source tree, sequences |
| 10. Capability Map | [10-capability-map.md](./10-capability-map.md) | CAP → module routing |
| 11. Deferred | [11-deferred.md](./11-deferred.md) | Intentionally postponed decisions |
