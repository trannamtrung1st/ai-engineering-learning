---
name: ui-ux-testing
description: UI/UX audit skill for the browser test agent — screenshot-driven review for common usability defects beyond predefined TC-* cases. Log UX-* bugs with severity; P0/P1 block the browser gate.
---

# UI/UX Testing Skill

Process guidance for the **browser test agent** when auditing rendered UI beyond the mandatory `TC-*` checklist. Functional PASS on predefined cases is insufficient when UX defects are present.

**Related:** [00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) · [visual-design skill](../visual-design/SKILL.md) · [ui-visual-verification.md](../../docs/ui-visual-verification.md) · [ux-bug-logging.md](../../docs/ux-bug-logging.md)

---

## When to apply

After executing `layer: browser` cases (or during execution when a screenshot reveals an issue), run this checklist on **every distinct page/state** captured. Log defects that are **not** already covered by a failing `TC-*` line.

---

## Defect taxonomy

| Category | Look for | Example UX bug |
| --- | --- | --- |
| **Layout / responsive** | Overflow, clipped content, horizontal scroll on 320px viewport | Submit button below fold on narrow mobile width |
| **Touch / interaction** | Targets &lt; 44×44 px, dead clicks, missing focus ring on desktop | Icon-only nav item 32px wide |
| **Visual hierarchy** | Low contrast (&lt; 4.5:1), identical error/success styling, missing headings | All outcome states use same alert styling |
| **Copy / i18n** | Wrong locale on user paths, raw API text, missing recovery CTA | Generic "Submit" on localized route |
| **Forms** | Missing labels, toast vs inline misuse, validation on blur vs submit | Email error only in console, not UI |
| **Navigation** | Forbidden links in chrome, dead-end pages, broken back | Wrong role sees privileged route in sidebar |
| **Loading honesty** | Infinite spinner, layout shift, optimistic success before server | Success copy with spinner still visible |
| **Craft** | Generic template UI, flat gray SaaS, undifferentiated cards | Interchangeable white cards, no signature moment |
| **Aesthetic / style craft** | Token drift vs DESIGN.md, missing borders/elevation per design-system, wrong fonts | Flat borderless cards, default framework buttons, no outcome differentiation |

Cross-reference [visual-design](../visual-design/SKILL.md) and the [ui-visual-verification checklist](../../docs/ui-visual-verification.md) for craft-specific FAIL criteria.

---

## Bug ID and severity

| Field | Rule |
| --- | --- |
| **ID** | `UX-<slice-id>-NNN` — e.g. `UX-web-auth-login-003`; increment per slice per run |
| **Severity** | P0–P3 per [11-testing-plan.md](../../../docs/technical/11-testing-plan.md) §12 |
| **Gate** | **P0/P1 → `BROWSER_TEST_FAIL`**; P2/P3 logged but do not block alone |

### Severity guide (UX-specific)

| Severity | UX examples |
| --- | --- |
| **P0** | Auth bypass via UI; data loss on form submit; success shown before server confirms |
| **P1** | Core flow blocked (cannot submit, cannot navigate to required screen); forbidden link visible to wrong role; visual hierarchy so poor that the primary flow is hard to understand |
| **P2** | Should-capability degraded; confusing but recoverable messaging; slow perceived load (&gt; 2s spinner); ugly but usable UI such as generic templates, flat gray tables, or missing signature moments |
| **P3** | Cosmetic misalignment; minor copy typo; non-blocking spacing issue |

---

## Required bug fields

Each logged bug must include:

1. **title** — one line summary
2. **severity** — P0 | P1 | P2 | P3
3. **page** — URL path (e.g. `/events`)
4. **screenshot** — absolute path under `ai-harness/generated/runs/screenshots/<slice-id>/browser-test/`
5. **repro** — numbered steps
6. **expected** — what should happen per docs/quality bar
7. **actual** — what you observed
8. **relatedTags** — optional `AC-*` / `FR-*` / `NFR-*` if applicable

---

## Output formats

### Markdown (in browser test report)

```
UX-<slice-id>-001: P1 — touch target too small on submit — screenshot: .../20250630T120000Z-register-submit.png
```

### JSON artifact

Write structured bugs to the path specified in the browser test agent prompt (`ux-bugs.json` per slice run). Schema: [ux-bugs.schema.json](../../schemas/ux-bugs.schema.json).

---

## Related

- [visual-design](../visual-design/SKILL.md) — design-system module obligations and style profile
- [ui-visual-verification.md](../../docs/ui-visual-verification.md) — 15-point screenshot checklist
