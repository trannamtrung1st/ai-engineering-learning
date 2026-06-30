# UI Visual Verification — Browser Screenshot Checklist

Structured visual QA for **frontend** and **test** slices. Run before `SLICE_DONE`. Screenshots are the **primary** evidence for contrast and padding; accessibility snapshots are for interaction debugging only.

**Authoritative specs:** [04-design-tokens.md](../../docs/ui-ux/04-design-tokens.md) §3.2.1 (button contrast pairs), §5.1 (control spacing) · [05-common-ui-components.md](../../docs/ui-ux/05-common-ui-components.md) §2.1 · [00-production-ui-quality-bar.md](../../docs/ui-ux/00-production-ui-quality-bar.md)

---

## When to run

- Every `frontend` or `test` backlog slice
- After any change to `Button`, form actions, cards, tables, or outcome panels
- Before signaling `SLICE_DONE` — re-run after fixes

---

## How to capture

1. Start preview: `npm run aih:preview:verify` (stack at `http://localhost:3007`)
2. Use **Playwright MCP** or **cursor-ide-browser** `browser_take_screenshot`
3. Save to `ai-harness/generated/runs/screenshots/<slice-id>/implementer/`
4. Filename: `<UTC-timestamp>-<route-slug>-<viewport>.png` (e.g. `20250630T120000Z-login-320w.png`)

### Required viewports

| Viewport | Size | Routes |
| --- | --- | --- |
| Student mobile | **320×568** | All student routes (`/check-in`, `/history`, `/login` on mobile) |
| Desktop | **1280×720** | Instructor, admin, auth desktop layouts |

Capture **both** viewports for every route you created or modified in the slice.

---

## Per-route checklist

Open each screenshot and verify. Any **FAIL** → fix code → re-screenshot before `SLICE_DONE`.

| # | Check | PASS criteria |
| --- | --- | --- |
| 1 | **Primary CTA** | Label readable at arm's length on 320px screenshot; `--color-primary-foreground` on `--color-primary-600` (not washed-out blue) |
| 2 | **Secondary / outline / ghost** | Text distinguishable from `--color-surface-default` page background; outline border visible |
| 3 | **Disabled buttons** | Visibly disabled (muted surface) but label still legible (≥ **3:1**) |
| 4 | **Button padding** | No cramped labels — `md` buttons have comfortable inset (min `--space-3` vertical, `--space-4` horizontal) |
| 5 | **Stacked actions** | Gap between primary and secondary buttons (`--space-3`); not touching |
| 6 | **Cards / tables** | Content not flush against edges — at least `--space-4` internal padding |
| 7 | **Danger actions** | White/inverse text on `--color-danger-500`; not red-on-red |
| 8 | **Outcome CTAs** | Check-in outcome panel recovery button meets primary contrast pair |

---

## What not to use for visual craft

| Tool | Use for |
| --- | --- |
| `browser_take_screenshot` / Playwright screenshot | **Contrast, padding, layout, typography** |
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
- [frontend-design skill](../skills/frontend-design/SKILL.md) — Notion craft and tester FAIL criteria
