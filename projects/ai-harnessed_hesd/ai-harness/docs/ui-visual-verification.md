# UI Visual Verification — Browser Screenshot Checklist

Structured visual QA for **frontend** and **test** slices. Run before `SLICE_DONE`. Screenshots are the **primary** evidence for contrast, padding, layout, hierarchy, and aesthetic craft; accessibility snapshots are for interaction debugging only.

Agents must pass both **functional** and **aesthetic** verification. UI that works but looks generic, cramped, or unfinished should be fixed before completion or logged as a `UX-*` craft defect by the browser tester.

**Authoritative specs:** [DESIGN.md](../../docs/ui-ux/DESIGN.md) · [design-system/](../../docs/ui-ux/design-system/) · [04-design-tokens.md](../../docs/ui-ux/04-design-tokens.md) · [05-common-ui-components.md](../../docs/ui-ux/05-common-ui-components.md) · [00-production-ui-quality-bar.md](../../docs/ui-ux/00-production-ui-quality-bar.md)

---

## When to run

- Every `frontend` or `test` backlog slice
- After any change to `Button`, form actions, cards, tables, or outcome panels
- Before signaling `SLICE_DONE` — re-run after fixes

---

## How to capture

1. Start preview: `npm run aih:preview:verify` (stack at `http://localhost:3007` by default)
2. Use **Playwright MCP** or **cursor-ide-browser** `browser_take_screenshot`
3. Save to `ai-harness/generated/runs/screenshots/<slice-id>/implementer/`
4. Filename: `<UTC-timestamp>-<route-slug>-<viewport>.png` (e.g. `20250630T120000Z-login-320w.png`)

### Required viewports

| Viewport | Size | When |
| --- | --- | --- |
| Mobile | **320×568** | Mobile-first or narrow layouts |
| Desktop | **1280×720** | Desktop layouts, data tables, wide shells |

Capture **both** viewports for every route you created or modified in the slice when the product serves both form factors.

---

## Per-route checklist

Open each screenshot and verify. Any **FAIL** → fix code → re-screenshot before `SLICE_DONE`.

| # | Check | PASS criteria |
| --- | --- | --- |
| 1 | **Primary CTA** | Label readable at arm's length on 320px screenshot; `#FFDB33` foreground on `#FFDB33` background (not washed-out); Archivo Black font on primary buttons |
| 2 | **Secondary / outline / ghost** | Text distinguishable from page background; 2px solid black outline border visible per Neobrutalism spec |
| 3 | **Disabled buttons** | Visibly disabled (muted surface) but label still legible (≥ **3:1**) |
| 4 | **Button padding** | No cramped labels — comfortable inset per design tokens |
| 5 | **Stacked actions** | Gap between primary and secondary buttons; not touching |
| 6 | **Cards / tables** | Content not flush against edges — adequate internal padding; 2px black border and hard-offset shadow present on card surfaces per Neobrutalism spec |
| 7 | **Danger actions** | Inverse text on danger background; not same-hue on same-hue |
| 8 | **Outcome / recovery CTAs** | Recovery actions meet primary contrast pair; "Về trang chủ" or equivalent recovery link present on error/denied states |
| 9 | **Typography hierarchy** | Clear Archivo Black title / Space Grotesk body / metadata scale; no clipped headings |
| 10 | **Style signature — borders** | All interactive surfaces have 2px solid black border per `borders.md`; no surface missing Neobrutalism border treatment |
| 11 | **Style signature — elevation** | Cards/buttons use hard-offset shadows (no blur) per `shadows.md`; no soft box-shadow or missing elevation |
| 12 | **Outcome accent surfaces** | Attendance statuses (Có mặt / Vắng mặt / Đi muộn / Đang xác minh) use distinct badge/alert variants with different border accents |
| 13 | **Whitespace rhythm** | Sections, cards, and toolbars have token-aligned gaps; content is not cramped |
| 14 | **Listing toolbar** | Search, filters, sort, pagination, and CTA are aligned with documented chrome; TableToolbar present on all collection views |
| 15 | **Focus / active nav** | Correct SidebarNav highlight (neutral-secondary-strong bg, fg-brand-strong text) and visible focus on interactive elements |
| 16 | **Navigation surface + home link** | Every authenticated page shows a persistent nav surface (`StaffLayout` SidebarNav, `AdminLayout`, or `StudentLayout`); a home link (role dashboard or "Trang chủ") is visible and functional on every route |
| 17 | **Login page neutrality + redirect** | Login page (`/login`) heading is generic ("Đăng nhập") with no role-specific text; after login, user lands on the correct role home (Student → `/check-in`, Lecturer → `/lecturer/sessions`, AcademicAdmin → `/admin/terms`, ITAdmin/SystemAuditor → `/audit/logs`) |
| 18 | **Back-to-home reachable** | Every page (including `/lecturer/sessions/{id}`, `/admin/terms/{id}`, `/me/history`, session outcome pages) provides at least one clickable path back to role home: breadcrumb first segment, sidebar home link, or linked product logo — no browser-back-only dead ends |
| 19 | **No forbidden nav items** | Nav chrome (SidebarNav, AdminLayout nav, StudentLayout) contains zero links to routes the current role cannot access; no forbidden items are rendered as disabled — they must be absent entirely from the DOM |
| 20 | **Access-denied surface** | Navigating directly to a forbidden route renders a styled `FeedbackAlert variant="danger"` page with a human-readable vi-VN message and a visible "Về trang chủ" link; not a crash, blank page, or redirect to `/login` |

---

## What not to use for visual craft

| Tool | Use for |
| --- | --- |
| `browser_take_screenshot` / Playwright screenshot | **Contrast, padding, layout, typography, hierarchy, aesthetic craft** |
| Accessibility snapshot | Focus order, ARIA labels, interaction debugging only |
| axe-core / Lighthouse | Out of harness scope — mark browser cases `SKIP not-applicable` |

---

## Evidence

Append to `ai-harness/state/progress.md`:

```
<timestamp> | <slice-id> | browser_verified: <flows> — screenshots: <paths> (320w + desktop)
```

List every screenshot path under the required directory. Browser tester gate re-verifies craft from its own captures in `.../browser-test/`.

---

## Related docs

- [browser-mcp.md](./browser-mcp.md) — Playwright setup, screenshot paths, timeouts
- [visual-design skill](../skills/visual-design/SKILL.md) — visual craft and tester FAIL criteria
