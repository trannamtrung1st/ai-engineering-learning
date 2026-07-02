---
title: HESD Attendance Implementation Guide
type: implementation-guide
status: final
created: '2026-07-02'
updated: '2026-07-02'
format: sharded
entry_point: true
spine_ref: ../spine/index.md
sections:
  - 1-agent-loading-order.md
  - 2-cold-start.md
  - 3-build-order.md
  - 4-implementation-rules.md
  - 5-domain-modules.md
  - 6-api-surface.md
  - 7-testing-focus.md
  - 8-assumptions.md
---

# Implementation Guide — HESD Workshop Digital Attendance System

> **Sharded implementation guide.** Agent entry point for build order and module map. Load `spine/index.md` for invariants (AD-1…AD-13).

## Sections

| Section | File | Load when |
|---------|------|-----------|
| 1. Agent Loading Order | [1-agent-loading-order.md](./1-agent-loading-order.md) | First step before any code |
| 2. Cold Start | [2-cold-start.md](./2-cold-start.md) | Scaffold repo (once) |
| 3. Build Order | [3-build-order.md](./3-build-order.md) | Phases 1–10 |
| 4. Implementation Rules | [4-implementation-rules.md](./4-implementation-rules.md) | Non-negotiable constraints |
| 5. Domain Modules | [5-domain-modules.md](./5-domain-modules.md) | Module responsibilities |
| 6. API Surface | [6-api-surface.md](./6-api-surface.md) | Route handlers + actions |
| 7. Testing Focus | [7-testing-focus.md](./7-testing-focus.md) | Priority test scenarios |
| 8. Assumptions | [8-assumptions.md](./8-assumptions.md) | Open `[ASSUMPTION]` tags |
