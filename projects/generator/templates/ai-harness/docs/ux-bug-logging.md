# UX Bug Logging — Browser Test Agent

Ad-hoc UI/UX defects discovered during browser verification that are **not** already covered by predefined `TC-*` test cases.

## Purpose

The browser test agent exercises generated `layer: browser` cases and acceptance tags. Beyond that checklist, it performs a **UX audit pass** using [ui-ux-testing skill](../skills/ui-ux-testing/SKILL.md) and logs structured bugs with `UX-*` IDs.

## Bug ID format

```
UX-<slice-id>-<NNN>
```

Examples: `UX-web-auth-login-001`, `UX-web-participant-browse-002`

## Severity and gate impact

Aligned with [11-testing-plan.md](../../docs/technical/11-testing-plan.md) §12:

| Severity | Blocks `BROWSER_TEST_PASS` |
| --- | --- |
| P0 | Yes |
| P1 | Yes |
| P2 | No (logged only) |
| P3 | No (logged only) |

## Artifacts

| Artifact | Path |
| --- | --- |
| UX bugs JSON | `ai-harness/generated/runs/ux-bugs/<slice-id>/<run-id>.json` |
| Screenshots | `ai-harness/generated/runs/screenshots/<slice-id>/browser-test/` |
| Run summary | `ai-harness/generated/runs/<run-id>-browser-test.json` → `uxBugs` array |

Schema: [ux-bugs.schema.json](../schemas/ux-bugs.schema.json)

## JSON structure

```json
{
  "sliceId": "<slice-id>",
  "runId": "20250630T120000Z",
  "generatedAt": "2025-06-30T12:00:00Z",
  "bugs": [
    {
      "id": "UX-<slice-id>-001",
      "severity": "P1",
      "title": "Primary submit button below 44px touch target",
      "page": "/register",
      "screenshot": "ai-harness/generated/runs/screenshots/<slice-id>/browser-test/20250630T120000Z-register-submit.png",
      "repro": ["Navigate to /register", "Inspect submit control dimensions"],
      "expected": "Touch targets ≥ 44×44 px per quality bar",
      "actual": "Submit button measures 36×40 px",
      "relatedTags": ["NFR-18", "AC-03"]
    }
  ]
}
```

## Markdown output (in `*-browser-test.txt`)

```
UX-<slice-id>-001: P1 — Primary submit button below 44px touch target — screenshot: .../20250630T120000Z-register-submit.png
```

## Feedback to implementer

On `BROWSER_TEST_FAIL` (including UX P0/P1 blockers):

1. Harness appends to `ai-harness/state/guardrails.md`
2. Next implementer prompt includes prior browser test failures with UX bug summaries
3. Implementer fixes UX blockers same as `TC-*: FAIL` blockers

## Deduplication

Do **not** log a `UX-*` bug when the same issue is already reported as `TC-*: FAIL` in the current run.
