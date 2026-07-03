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
| **Common UI/UX suite** (`ai-harness/test-cases/common/ui-ux-suite.json`, `TC-UX-COMMON-*`) | Generic, product-wide checks (staff shell + home link, scoped access-denied, login neutrality, contrast, student mobile responsive, focus, loading, listing states) | Harness always appends it to the **full** browser phase; run against every screen. P0/P1 FAIL blocks; P2/P3 → advisory `UX-*` |
| **Item-scoped `ui-ux` cases** (TestGen `category: ui-ux`, `ui-*` technique) | UI/UX quality for the specific screens a requirement renders | Bundled per-slice like other `layer: browser` cases |
| **This skill's audit** | Anything neither suite nor item case already caught | Discretionary `UX-*` logging on every captured screen |

Do not duplicate a defect across all three — report it once (prefer the most specific `TC-*` line; otherwise a `UX-*` log).

---

## Defect taxonomy

| Category | Look for | Example UX bug | Min severity |
| --- | --- | --- | --- |
| **Layout / responsive** | Overflow, clipped content, horizontal scroll on 320px viewport | Check-in submit button below fold on narrow mobile | P2 |
| **Touch / interaction** | Targets &lt; 44×44 px, dead clicks, missing focus ring on desktop | QR scan icon-button 32px wide | P1 |
| **Visual hierarchy** | Low contrast (&lt; 4.5:1), identical error/success styling, missing headings | "Có mặt" and "Vắng mặt" badges use same color and border | P2 |
| **Copy / jargon** | Technical IDs, schema field names, enum literals, requirement codes in visible vi-VN UI text | Column header shows `student_id`; toast reads `PENDING_VERIFICATION`; error says `AC-06 failed` | **P1** — leaking internal state is always a blocking defect |
| **Copy / i18n** | Wrong locale (non-vi-VN text on vi-VN routes), raw API error text, missing recovery CTA | English "Submit" button on Vietnamese check-in form | P2 |
| **Forms** | Missing vi-VN labels, toast vs inline misuse, validation on blur vs submit | Email field error only in console, not shown in UI | P2 |
| **Entry flow** | Missing or empty home/landing page per role; login page heading mentions a role name; post-login redirect goes to wrong role home | Login heading "Đăng nhập Giáo viên"; Lecturer logs in and lands on `/check-in`; home page is blank shell | **P1** — the entry path is the first thing every user sees |
| **Navigation** | No persistent nav surface on authenticated pages; `SidebarNav` home link absent; dead-end detail pages with no breadcrumb or back path; forbidden nav item visible to wrong role; forbidden nav item rendered as disabled instead of omitted | Student sees "Mở phiên học" link in chrome; `/lecturer/sessions/{id}` has no breadcrumb; Lecturer lands on page with no nav surface | **P1** for missing home link or forbidden link visible; **P2** for disabled-instead-of-hidden |
| **RBAC — access denied** | Forbidden route renders crash, blank screen, or redirect to `/login`; access-denied surface has no "Về trang chủ" link; `FeedbackAlert danger` missing Neobrutalism border/shadow treatment | Student navigates to `/reports/attendance`, sees blank page; ITAdmin hits `/admin/terms`, redirected to login with no explanation | **P1** — authenticated users must always know why they can't proceed and how to recover |
| **Loading honesty** | Infinite spinner, layout shift, optimistic success before server confirms (critical for QR check-in) | Check-in success badge shown while spinner still visible | P2 |
| **Craft — primary flow** | Generic template styling on check-in, session open, roster, or report pages; Neobrutalism absent (no 2px border, no hard shadow, no `#FFDB33` primary CTA); home page has no live data surface | Check-in page has default Tailwind button with no border; session list is flat gray cards with no elevation; student home is blank heading | **P1** when Neobrutalism is absent on primary flow or home page; P2 for secondary views |
| **Craft — secondary** | Undifferentiated cards, identical state styling, missing Neobrutalism moment on non-primary views | Audit log rows have no status badge differentiation | P2 |
| **Aesthetic / style craft** | Token drift vs DESIGN.md (wrong `#FFDB33`, wrong radius `0px`, missing hard-offset shadow, wrong Archivo Black / Space Grotesk fonts) | Rounded corners on any surface; soft box-shadow instead of hard offset | P2 |

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
| **P0** | Auth bypass via UI; check-in data loss on form submit; success shown before server confirms QR outcome |
| **P1** | Core flow blocked (cannot submit check-in, cannot open session, cannot navigate to required screen); forbidden nav link visible to wrong role; forbidden route shows no access-denied surface; access-denied surface missing "Về trang chủ" link; technical identifier (`student_id`, `session_uuid`, `AC-01`, raw enum) visible in vi-VN user-facing text; login page has role-specific heading; post-login redirect goes to wrong role home; authenticated page has no nav surface or no home link; home/landing page is empty or redirects to `/showcase`; primary flow page is Neobrutalism-absent (no 2px border, no hard shadow) making the primary action unclear |
| **P2** | Should-capability degraded; confusing but recoverable vi-VN messaging; slow perceived load (&gt; 2s spinner on check-in); forbidden nav item rendered as disabled instead of hidden; secondary view styling generic or flat; non-critical dead-end pages; missing breadcrumb on non-primary deep route |
| **P3** | Cosmetic misalignment; minor vi-VN copy typo; non-blocking spacing issue |

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
- [ui-visual-verification.md](../../docs/ui-visual-verification.md) — 20-point screenshot checklist
