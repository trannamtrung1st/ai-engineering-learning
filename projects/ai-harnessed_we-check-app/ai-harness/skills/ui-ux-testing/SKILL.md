---
name: ui-ux-testing
description: UI/UX audit skill for the browser test agent — screenshot-driven review for common usability defects beyond predefined TC-* cases. Log UX-* bugs with severity; P0/P1 block the browser gate.
---

# UI/UX Testing Skill

Process guidance for the **browser test agent** when auditing rendered UI beyond the mandatory `TC-*` checklist. Functional PASS on predefined cases is insufficient when UX defects are present.

**Related:** [00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) · [frontend-design skill](../frontend-design/SKILL.md) · [ux-bug-logging.md](../../docs/ux-bug-logging.md)

---

## When to apply

After executing `layer: browser` cases (or during execution when a screenshot reveals an issue), run this checklist on **every distinct page/state** captured. Log defects that are **not** already covered by a failing `TC-*` line.

---

## Defect taxonomy

| Category | Look for | Example UX bug |
| --- | --- | --- |
| **Layout / responsive** | Overflow, clipped content, horizontal scroll on 320px viewport | Submit button below fold on iPhone SE width |
| **Touch / interaction** | Targets &lt; 44×44 px, dead clicks, missing focus ring on desktop | Icon-only nav item 32px wide |
| **Visual hierarchy** | Low contrast (&lt; 4.5:1), identical error/success styling, missing headings | All check-in outcomes use same red alert |
| **Copy / i18n** | English on user paths, raw API text, missing recovery CTA | Button label "Submit" on `/check-in` |
| **Forms** | Missing labels, toast vs inline misuse, validation on blur vs submit | Email error only in console, not UI |
| **Navigation** | Forbidden links in chrome, dead-end pages, broken back | Instructor sees `/admin/users` in sidebar |
| **Loading honesty** | Infinite spinner, layout shift, optimistic success before server | GPS ready copy with spinner still visible |
| **Craft (Notion)** | Generic template UI, flat gray SaaS, undifferentiated cards | Interchangeable white cards, no signature moment |

Cross-reference [frontend-design](../frontend-design/SKILL.md) for craft-specific FAIL criteria.

---

## Bug ID and severity

| Field | Rule |
| --- | --- |
| **ID** | `UX-<slice-id>-NNN` — e.g. `UX-web-student-checkin-003`; increment per slice per run |
| **Severity** | P0–P3 per [11-testing-plan.md](../../../docs/technical/11-testing-plan.md) §12 |
| **Gate** | **P0/P1 → `BROWSER_TEST_FAIL`**; P2/P3 logged but do not block alone |

### Severity guide (UX-specific)

| Severity | UX examples |
| --- | --- |
| **P0** | Auth bypass via UI; data loss on form submit; check-in marked success before server confirms |
| **P1** | Core flow blocked (cannot submit, cannot navigate to required screen); forbidden admin link visible to student |
| **P2** | Should-capability degraded; confusing but recoverable messaging; slow perceived load (&gt; 2s spinner) |
| **P3** | Cosmetic misalignment; minor copy typo; non-blocking spacing issue |

---

## Required bug fields

Each logged bug must include:

1. **title** — one line summary
2. **severity** — P0 | P1 | P2 | P3
3. **page** — URL path (e.g. `/check-in`)
4. **screenshot** — absolute path under `ai-harness/generated/runs/screenshots/<slice-id>/browser-test/`
5. **repro** — numbered steps
6. **expected** — what should happen per docs/quality bar
7. **actual** — what you observed
8. **relatedTags** — optional `AC-*` / `FR-*` / `NFR-*` if applicable

---

## Output formats

### Markdown (in browser test report)

```
UX-web-student-checkin-001: P1 — touch target too small on GPS submit — screenshot: .../20250630T120000Z-check-in-submit.png
```

### JSON artifact

Write `ai-harness/generated/runs/ux-bugs/<slice-id>/<run-id>.json` per [ux-bugs.schema.json](../../schemas/ux-bugs.schema.json).

---

## Browser tester checklist

1. Capture screenshot for each distinct page/state visited during `TC-*` execution
2. Review each screenshot against this taxonomy **and** [00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md)
3. Log `UX-*` bugs for issues **not** already reported as `TC-*: FAIL`
4. Do **not** duplicate: if `TC-AC-07-013: FAIL` already covers the issue, skip a separate UX entry
5. Write UX bugs JSON before emitting final `BROWSER_TEST_PASS` or `BROWSER_TEST_FAIL`
6. P0/P1 UX bugs must appear in the blocker summary before the signal line

---

## Out of scope (mark SKIP, do not log as UX bug)

- Physical device matrix (real iOS/Android hardware) — `SKIP — physical-device`
- axe-core / Lighthouse audits — `SKIP — not-applicable`
- Issues already tracked as `TC-*: FAIL` in the same run
