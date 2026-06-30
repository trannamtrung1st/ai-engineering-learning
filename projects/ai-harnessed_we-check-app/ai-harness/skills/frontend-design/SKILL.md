---
name: frontend-design
description: Distinctive, intentional visual design for We Check UI. Process and craft guidance for implementer and browser tester agents — Notion workspace identity, signature moments, and copy that avoid templated defaults.
source: https://github.com/anthropics/skills/tree/main/skills/frontend-design
license: See LICENSE.txt
---

# Frontend Design (We Check Harness)

Adapted from the [Anthropic frontend-design skill](https://raw.githubusercontent.com/anthropics/skills/refs/heads/main/skills/frontend-design/SKILL.md). This skill governs **identity and signature craft**; workspace density patterns live in [`design-craft-notion`](../design-craft-notion/SKILL.md).

**Division of labor:**

| Skill | Owns |
| --- | --- |
| `frontend-design` (this file) | Notion workspace identity, typography, signature moments, copy tone, anti-template aesthetics |
| `design-craft-notion` | Sidebar density, database toolbars, table rhythm, listing §0 layout |

## Precedence (non-negotiable)

When this skill conflicts with product specs, **product docs win**:

| Topic | Authoritative doc |
| --- | --- |
| Design spec | [docs/ui-ux/DESIGN.md](../../../docs/ui-ux/DESIGN.md) |
| Token values, colors, fonts | [docs/ui-ux/04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) |
| Visual direction | [docs/ui-ux/01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) §5 |
| Quality gate, touch targets, QR contrast | [docs/ui-ux/00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) |
| Vietnamese copy, state labels | [docs/ui-ux/01-ui-ux-foundation.md](../../../docs/ui-ux/01-ui-ux-foundation.md) |
| Component contracts | [docs/ui-ux/05-common-ui-components.md](../../../docs/ui-ux/05-common-ui-components.md), [06-app-layout-components.md](../../../docs/ui-ux/06-app-layout-components.md) |
| Radix primitives, Tailwind | [docs/ui-ux/02-ui-framework-tech-stack.md](../../../docs/ui-ux/02-ui-framework-tech-stack.md) |

Never bypass tokens, accessibility, or business rules for aesthetics.

---

## Ground it in We Check

**Subject:** Timed classroom attendance for Vietnamese university workshops — students under pressure on phones, instructors projecting QR codes, admins auditing rosters at a desk.

**Audience:** Students (320 px mobile), instructors (1024 px+ with projection), training office admins (data-dense tables).

**Page job:** Each screen has one primary job — scan, monitor, export, recover from error. Decoration must serve that job.

Draw distinctive choices from this world: session countdown urgency, attendance outcomes as emotional moments, calm workspace trust, Vietnamese clarity over clever English.

---

## Design principles

### Hero as thesis

Open each major flow with its most characteristic element: check-in scanner viewfinder, live attendance counts, QR countdown on projection. Avoid generic dashboard patterns (big number + gradient + three stat cards) unless the content truly is a metrics summary.

### Typography carries personality

Use **Inter** (Notion Sans equivalent) with Vietnamese subset for all UI. Set a clear type scale with intentional weight and spacing. Headlines should feel deliberate, not default.

### Structure encodes information

Numbering, eyebrows, dividers, and labels must reflect real structure (session lifecycle order, check-in steps). Do not add decorative `01 / 02 / 03` markers unless order carries meaning.

### Motion serves the subject

Orchestrate one moment per flow: check-in page enter, outcome panel reveal, card hover lift. Respect `prefers-reduced-motion`. Scattered animation reads as AI-generated — prefer one orchestrated beat.

### Match complexity to the vision

Notion workspace is refined, not maximalist: warm gray surfaces, hairline borders, one signature moment per critical flow. Precision in spacing and type beats decorative clutter.

---

## Process: plan before build

Work in two passes when creating or reshaping UI:

1. **Plan** — Compact token usage (colors, type, layout rhythm), one signature element for the slice, ASCII wireframe if layout is non-obvious.
2. **Critique** — Before coding, ask: does this read like a generic SaaS template or a choice made for We Check? Revise generic parts.

### Aesthetic clusters to avoid

These appear regardless of subject — do not default to them:

- Warm cream `#F4F1EA` + terracotta accent + high-contrast serif display
- Near-black background + single acid-green or vermilion accent
- Broadsheet layout with hairline rules, zero radius, dense newspaper columns
- Generic Tailwind blue admin dashboard (`#2563eb` primary, flat gray surfaces)
- Old Campus Pulse indigo brand (`#1b2a4a`) and blue CTAs — superseded by Notion purple

Notion direction: navy auth band, purple primary CTA, charcoal text, warm gray surfaces, pastel card-tint outcomes — see [01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) §5.

---

## Signature element

**Check-in outcome moment** — full-width status panel with icon, card-tint pastel wash, Vietnamese headline, and single purple recovery CTA. Every check-in outcome (`Success`, `ExpiredQr`, `OutOfRadius`, etc.) must be visually distinct, not interchangeable alert boxes.

Other signature candidates by slice:

- Auth: split-panel with navy `hero-band-dark` left panel
- Instructor monitor: stat cards with live pulse on active count
- QR tab (non-projection): elevated card with countdown emphasis

Spend boldness in **one** place per slice; keep surrounding chrome quiet.

---

## Copy in design

Words are design material:

- Name things by what people control: “Quét lại”, not “Retry QR validation”
- Active voice on buttons: “Lưu thay đổi”, not “Submit”
- Errors explain what happened and next step — no apologies, no vagueness
- Empty states invite action: “Chưa có buổi học nào” + link to relevant flow

Match vocabulary across button, toast, and heading in the same flow.

---

## Restraint and quality floor

- Responsive down to **320 px** on student routes
- Visible keyboard focus (`--focus-ring-*` tokens)
- Touch targets ≥ **44×44 px** on student surfaces
- QR presentation mode: max contrast black/white — decorative tokens must not weaken [NFR-20](../../../docs/brds/07-non-functional-risk.md)
- `prefers-reduced-motion`: disable non-essential animation

Before `SLICE_DONE`, remove one decorative element if the screen feels busy (Chanel rule).

---

## Contrast and control chrome

Buttons, links, and form actions are the highest-risk contrast surfaces. Use token pairs from [04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) §3.2.1 — never improvise lighter purples or opacity hacks.

| Surface | Rule |
| --- | --- |
| Primary button | `--color-primary-foreground` on `--color-primary-600`; hover `--color-primary-700` |
| Secondary / outline / ghost | Label must read clearly on warm gray `--color-surface-default` |
| Disabled | Muted but legible — ≥ **3:1**; do not fade to illegibility |
| Padding | `md` buttons: `--space-4` horizontal, min `--size-touch-min` height; stacked actions gap `--space-3` |
| Cards / panels | Internal padding ≥ `--space-4`; outcome panels `--space-6` |

Verify in **browser screenshots** at 320px and desktop — not by reading CSS alone. Follow [ui-visual-verification.md](../../docs/ui-visual-verification.md).

---

## Implementer checklist

1. Read [DESIGN.md](../../../docs/ui-ux/DESIGN.md), [01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) §5, and [04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) §3.2.1 and §5.1 before coding
2. Use tokens only — no ad-hoc hex in components
3. Include at least one signature moment when the slice touches check-in, auth, or primary role shell
4. Capture **dual-viewport** screenshots (320×568 + 1280×720) of every created/modified route
5. **Self-critique each screenshot** using [ui-visual-verification.md](../../docs/ui-visual-verification.md) — fix low-contrast buttons, cramped padding, illegible disabled states before signaling done
6. Append screenshot paths and viewports to `ai-harness/state/progress.md`

---

## Browser tester checklist

Functional PASS is insufficient when UI craft fails:

1. Review screenshots against [00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md), [ui-visual-verification.md](../../docs/ui-visual-verification.md), **and** this skill
2. **FAIL** when: layout feels generic/template-like; spacing is careless; outcome states look identical; auth/shell lacks Notion treatment; hard-coded colors visible; English strings on user paths; **low-contrast buttons** (label unreadable on background); **cramped button padding**; **illegible disabled** controls
3. **PASS** when: Notion tokens applied consistently; Vietnamese copy correct; signature moments distinct; role-appropriate chrome present; button contrast and padding meet §3.2.1 / §5.1
4. Cite screenshot path as evidence for craft-related PASS or FAIL

---

## Related harness docs

- [design-craft-notion skill](../design-craft-notion/SKILL.md) — workspace density and listing toolbars
- [browser-mcp.md](../../docs/browser-mcp.md) — Playwright verification runbook
- [ui-visual-verification.md](../../docs/ui-visual-verification.md) — screenshot contrast and padding checklist
- [00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) — merge gate standards
