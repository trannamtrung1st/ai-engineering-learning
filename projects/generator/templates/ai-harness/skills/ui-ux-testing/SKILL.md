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

### Two layers of UI/UX coverage

| Source | Scope | How it runs |
| --- | --- | --- |
| **Common UI/UX suite** (`ai-harness/test-cases/common/ui-ux-suite.json`, `TC-UX-COMMON-*`) | Generic, product-wide checks (nav, home link, access-denied, login neutrality, contrast, responsive, focus, loading, outcome states) | Harness always appends it to the **full** browser phase; run against every screen. P0/P1 FAIL blocks; P2/P3 → advisory `UX-*` |
| **Item-scoped `ui-ux` cases** (TestGen `category: ui-ux`, `ui-*` technique) | UI/UX quality for the specific screens a requirement renders | Bundled per-slice like other `layer: browser` cases |
| **This skill's audit** | Anything neither suite nor item case already caught | Discretionary `UX-*` logging on every captured screen |

Do not duplicate a defect across all three — report it once (prefer the most specific `TC-*` line; otherwise a `UX-*` log).

---

## Defect taxonomy

| Category | Look for | Example UX bug | Min severity |
| --- | --- | --- | --- |
| **Layout / responsive** | Overflow, clipped content, horizontal scroll on 320px viewport | Submit button below fold on narrow mobile width | P2 |
| **Touch / interaction** | Targets &lt; 44×44 px, dead clicks, missing focus ring on desktop | Icon-only nav item 32px wide | P1 |
| **Visual hierarchy** | Low contrast (&lt; 4.5:1), identical error/success styling, missing headings | All outcome states use same alert styling | P2 |
| **Copy / jargon** | Technical IDs, schema field names, requirement codes, internal slugs in visible UI text | Column header reads `item_id`; toast shows `AC-01 passed`; heading says `web-auth-session-pages` | **P1** — leaking internal state into the UI is always a blocking defect |
| **Copy / i18n** | Wrong locale on user paths, raw API text, missing recovery CTA | Generic "Submit" on localized route | P2 |
| **Forms** | Missing labels, toast vs inline misuse, validation on blur vs submit | Email error only in console, not UI | P2 |
| **Entry flow** | Missing or empty home/landing page; login page with role-specific copy or heading; post-login redirect goes to wrong role's home | Login heading reads "Manager Login"; redirect after auth lands on wrong dashboard; home page is blank or loops | **P1** — the entry path is the first thing every user sees |
| **Navigation** | No persistent nav surface on authenticated pages; home link absent; dead-end pages with no escape path; back-to-home unreachable without browser button; forbidden nav item visible to wrong role; forbidden nav item rendered as disabled rather than omitted | Role B sees "Admin Settings" link in sidebar; detail page has no breadcrumb or nav; home link missing from logged-in shell | **P1** for missing home link or forbidden link visible; **P2** for disabled-instead-of-hidden |
| **RBAC — access denied** | Forbidden route renders crash, blank screen, or redirect to login instead of styled access-denied page; access-denied page has no home link | Navigating to `/restricted-area` as an unauthorized user shows blank page or bounces to login with no explanation | **P1** — users must always know why they can't proceed and how to recover |
| **Loading honesty** | Infinite spinner, layout shift, optimistic success before server | Success copy with spinner still visible | P2 |
| **Craft — primary flow** | Generic template UI on a primary flow page that makes it hard to understand what to do; flat gray SaaS with zero visual differentiation; no intentional visual moment on the home page or core action screen | Home page is empty except a heading; primary action button is unstyled default | **P1** when the primary flow is visually indistinguishable or unclear; P2 for secondary views |
| **Craft — secondary** | Undifferentiated cards, identical state styling, missing signature moment on non-critical views | Interchangeable white cards, no elevation difference | P2 |
| **Aesthetic / style craft** | Token drift vs DESIGN.md, missing borders/elevation per design-system, wrong fonts | Flat borderless cards, default framework buttons, no outcome differentiation | P2 |

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
| **P1** | Core flow blocked (cannot submit, cannot navigate to required screen); forbidden nav link visible to wrong role; forbidden route shows no access-denied page; technical identifier (ID, code, field name) visible in user-facing text; login page has role-specific copy; post-login redirect goes to wrong role's home; authenticated page has no nav surface or no home link; home/landing page is empty or missing; primary flow page so visually generic the intended action is unclear |
| **P2** | Should-capability degraded; confusing but recoverable messaging; slow perceived load (&gt; 2s spinner); forbidden nav item rendered as disabled instead of hidden; secondary views with generic template styling or missing signature moments; non-critical dead-end pages |
| **P3** | Cosmetic misalignment; minor copy typo; non-blocking spacing issue |

---

## Required bug fields

Each logged bug must include:

1. **title** — one line summary
2. **severity** — P0 | P1 | P2 | P3
3. **page** — URL path (e.g. `/dashboard`)
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
- [ui-visual-verification.md](../../docs/ui-visual-verification.md) — 20-point screenshot checklist
