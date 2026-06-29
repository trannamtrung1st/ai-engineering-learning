---
name: frontend-design
description: Distinctive, intentional visual design for We Check UI. Process and craft guidance for implementer and browser tester agents — aesthetic direction, typography, signature moments, and copy that avoid templated defaults.
source: https://github.com/anthropics/skills/tree/main/skills/frontend-design
license: See LICENSE.txt
---

# Frontend Design (We Check Harness)

Adapted from the [Anthropic frontend-design skill](https://raw.githubusercontent.com/anthropics/skills/refs/heads/main/skills/frontend-design/SKILL.md). This skill governs **how** to design; We Check product docs govern **what** values to use.

## Precedence (non-negotiable)

When this skill conflicts with product specs, **product docs win**:

| Topic | Authoritative doc |
| --- | --- |
| Token values, colors, fonts | [docs/ui-ux/04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) |
| Visual direction (Campus Pulse) | [docs/ui-ux/01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) §5 |
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

Draw distinctive choices from this world: session countdown urgency, attendance outcomes as emotional moments, institutional trust without bureaucratic coldness, Vietnamese clarity over clever English.

---

## Design principles

### Hero as thesis

Open each major flow with its most characteristic element: check-in scanner viewfinder, live attendance counts, QR countdown on projection. Avoid generic dashboard patterns (big number + gradient + three stat cards) unless the content truly is a metrics summary.

### Typography carries personality

Use the token-defined pair: **Be Vietnam Pro** (body, vi-VN) + **Plus Jakarta Sans** (display/headings). Set a clear type scale with intentional weight and spacing. Headlines should feel deliberate, not default.

### Structure encodes information

Numbering, eyebrows, dividers, and labels must reflect real structure (session lifecycle order, check-in steps). Do not add decorative `01 / 02 / 03` markers unless order carries meaning.

### Motion serves the subject

Orchestrate one moment per flow: check-in page enter, outcome panel reveal, card hover lift. Respect `prefers-reduced-motion`. Scattered animation reads as AI-generated — prefer one orchestrated beat.

### Match complexity to the vision

Campus Pulse is refined, not maximalist: layered surfaces, soft elevation, one signature moment per critical flow. Precision in spacing and type beats decorative clutter.

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

Campus Pulse direction: deep indigo trust, warm stone surfaces, emerald success, amber urgency — see [01-design-overview.md](../../../docs/ui-ux/01-design-overview.md) §5.

---

## Signature element

**Check-in outcome moment** — full-width status panel with icon, semantic color wash, Vietnamese headline, and single recovery CTA. Every check-in outcome (`Success`, `ExpiredQr`, `OutOfRadius`, etc.) must be visually distinct, not interchangeable alert boxes.

Other signature candidates by slice:

- Auth: split-panel with brand stripe
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

## Implementer checklist

1. Read Campus Pulse direction and [04-design-tokens.md](../../../docs/ui-ux/04-design-tokens.md) before coding
2. Use tokens only — no ad-hoc hex in components
3. Include at least one signature moment when the slice touches check-in, auth, or primary role shell
4. Capture screenshots of every created/modified route
5. **Self-critique each screenshot** against this skill + quality bar — fix generic spacing, undifferentiated states, template-like cards before signaling done
6. Append screenshot paths to `ai-harness/state/progress.md`

---

## Browser tester checklist

Functional PASS is insufficient when UI craft fails:

1. Review screenshots against [00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) **and** this skill
2. **FAIL** when: layout feels generic/template-like; spacing is careless; outcome states look identical; auth/shell lacks Campus Pulse treatment; hard-coded colors visible; English strings on user paths
3. **PASS** when: tokens applied consistently; Vietnamese copy correct; signature moments distinct; role-appropriate chrome present
4. Cite screenshot path as evidence for craft-related PASS or FAIL

---

## Related harness docs

- [browser-mcp.md](../../docs/browser-mcp.md) — Playwright verification runbook
- [00-production-ui-quality-bar.md](../../../docs/ui-ux/00-production-ui-quality-bar.md) — merge gate standards
