# Top Down Planning — specification index

Authoritative requirements for resilient resume and session recovery live in the
repository proposal:

- [`temp/top-down-planning-resilient-resume-improvements.md`](../../../temp/top-down-planning-resilient-resume-improvements.md)

This package implements Track A (proposal §19 Phases 1–5). Use the documents below
for operator and engineering traceability; they do not replace the proposal.

| Document | Purpose |
| --- | --- |
| [README](../README.md) | Quickstart, architecture layers, CLI overview |
| [resume-batch-checklist.md](resume-batch-checklist.md) | §6.1 coordinated schema/digest batch deployment |
| [implementation-plan-crosswalk.md](implementation-plan-crosswalk.md) | §19 step → plan item mapping |
| [test-matrix-ownership.md](test-matrix-ownership.md) | §21 named-test ownership table |
| `tdp agent readme` | Agent protocol (`AGENT_README_TEXT`) |
| `tdp agent schema` | Request/config JSON Schema |

Verification: proposal §20 acceptance criteria, §21 test matrix, §2 design decisions
(`tests/unit/test_design_decisions.py`), and integration tests under `tests/integration/`.
