# Top Down Planning — specification index

This package implements resilient run execution (Phases 1–5) and review convergence
(Phase 6): lifecycle/resume, structured session bindings, provider recovery,
active findings views, advisory handoff, owner actions, and convergence observability.

Use the documents below for operator and engineering traceability.

| Document | Purpose |
| --- | --- |
| [README](../README.md) | Quickstart, architecture layers, CLI overview |
| [resume-batch-checklist.md](resume-batch-checklist.md) | Coordinated schema/digest batch deployment |
| [implementation-plan-crosswalk.md](implementation-plan-crosswalk.md) | Implementation step → plan item mapping |
| [test-matrix-ownership.md](test-matrix-ownership.md) | Named-test ownership table |
| `tdp agent readme` | Agent protocol (`AGENT_README_TEXT`) |
| `tdp agent schema` | Request/config JSON Schema |

Verification: design-decision tests (`tests/unit/test_design_decisions.py`),
review/handoff tests, session binding tests, and integration tests under
`tests/integration/`.
