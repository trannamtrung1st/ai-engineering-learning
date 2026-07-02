---
title: ai-harnessed_hesd Epic Breakdown
status: final
created: 2026-07-02
updated: 2026-07-02
format: sharded
entry_point: true
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - _bmad-output/project-context.md
  - _bmad-output/specs/spec-hesd-workshop-attendance/SPEC.md
  - _bmad-output/planning-artifacts/prds/prd-ai-harnessed_hesd-2026-07-02/prd/index.md
  - _bmad-output/planning-artifacts/architecture/architecture-ai-harnessed_hesd-2026-07-02/index.md
  - _bmad-output/planning-artifacts/ux-designs/ux-ai-harnessed_hesd-2026-07-02/DESIGN.md
  - _bmad-output/planning-artifacts/ux-designs/ux-ai-harnessed_hesd-2026-07-02/EXPERIENCE.md
  - docs/ui-ux/design-system/
sections:
  - 0-overview.md
  - 1-requirements-inventory.md
  - 2-epic-list.md
  - epic-1-platform-foundation-secure-access.md
  - epic-2-admin-account-roster-management.md
  - epic-3-instructor-session-setup-live-qr-display.md
  - epic-4-student-mobile-check-in.md
  - epic-5-instructor-live-monitoring-overrides-export.md
  - epic-6-admin-audit-investigation.md
---

# ai-harnessed_hesd — Epic Breakdown

> **Sharded epics document.** Read this index first, then load only the section files you need. For sprint planning start with `2-epic-list.md` and the epic file for the story you are implementing.

## Sections

| Section | File | Load when |
|---------|------|-----------|
| Overview | [0-overview.md](./0-overview.md) | Orienting to the breakdown |
| Requirements inventory | [1-requirements-inventory.md](./1-requirements-inventory.md) | FR/NFR/UX-DR lookup, coverage map |
| Epic list (summary) | [2-epic-list.md](./2-epic-list.md) | Sprint planning, epic scope |
| Epic 1 — Platform Foundation | [epic-1-platform-foundation-secure-access.md](./epic-1-platform-foundation-secure-access.md) | Stories 1.1–1.5 |
| Epic 2 — Admin Accounts & Rosters | [epic-2-admin-account-roster-management.md](./epic-2-admin-account-roster-management.md) | Stories 2.1–2.6 |
| Epic 3 — Instructor Sessions & QR | [epic-3-instructor-session-setup-live-qr-display.md](./epic-3-instructor-session-setup-live-qr-display.md) | Stories 3.1–3.5 |
| Epic 4 — Student Check-In | [epic-4-student-mobile-check-in.md](./epic-4-student-mobile-check-in.md) | Stories 4.1–4.3 |
| Epic 5 — Live Monitoring & Export | [epic-5-instructor-live-monitoring-overrides-export.md](./epic-5-instructor-live-monitoring-overrides-export.md) | Stories 5.1–5.3 |
| Epic 6 — Admin Audit | [epic-6-admin-audit-investigation.md](./epic-6-admin-audit-investigation.md) | Story 6.1 |

## Quick stats

- **6 epics**, **23 stories**
- All FR1–FR18 covered (see `1-requirements-inventory.md` → FR Coverage Map)
- Implementation order: Epic 1 → 2 → 3 → 4 → 5; Epic 6 after Epic 4 (audit data)
