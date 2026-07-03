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
| 1 | **Primary CTA** | Label readable at arm's length on 320px screenshot; primary foreground on primary background (not washed-out) |
| 2 | **Secondary / outline / ghost** | Text distinguishable from page background; outline border visible |
| 3 | **Disabled buttons** | Visibly disabled (muted surface) but label still legible (≥ **3:1**) |
| 4 | **Button padding** | No cramped labels — comfortable inset per design tokens |
| 5 | **Stacked actions** | Gap between primary and secondary buttons; not touching |
| 6 | **Cards / tables** | Content not flush against edges — adequate internal padding |
| 7 | **Danger actions** | Inverse text on danger background; not same-hue on same-hue |
| 8 | **Outcome / recovery CTAs** | Recovery actions meet primary contrast pair |
| 9 | **Typography hierarchy** | Clear title/body/metadata scale; no clipped headings |
| 10 | **Style signature — borders** | Interactive surfaces match DESIGN.md / `borders.md` profile |
| 11 | **Style signature — elevation** | Cards/buttons use tokenized shadows per `shadows.md` — no accidental default framework elevation |
| 12 | **Outcome accent surfaces** | Success/warning/error/empty/forbidden use distinct alert/badge variants |
| 13 | **Whitespace rhythm** | Sections, cards, and toolbars have token-aligned gaps; content is not cramped |
| 14 | **Listing toolbar** | Search, filters, sort, pagination, and CTA are aligned with documented chrome |
| 15 | **Focus / active nav** | Correct sidebar highlight and visible focus on interactive elements |
| 16 | **Navigation surface + home link** | Every authenticated page shows a persistent nav surface (sidebar or topnav); a home/dashboard link is visible and functional on every route |
| 17 | **Login page neutrality + redirect** | Login page heading and copy contain no role-specific text; after login, user lands on the correct role's home page (not a generic `/` shell or wrong dashboard) |
| 18 | **Back-to-home reachable** | Every page (including detail views, modals, outcome pages) provides at least one clickable path back to home: nav logo, breadcrumb first segment, or explicit home nav item — no browser-back-only dead ends |
| 19 | **No forbidden nav items** | Nav chrome (sidebar, topnav, breadcrumbs, inline links) contains zero links to routes the current role cannot access; no forbidden items rendered as disabled — they must be absent entirely |
| 20 | **Access-denied page** | Navigating directly to a forbidden route renders a styled access-denied page (not a crash, blank, or login redirect); the page uses the product's alert/outcome surface, explains the restriction in plain language, and includes a home link |

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
