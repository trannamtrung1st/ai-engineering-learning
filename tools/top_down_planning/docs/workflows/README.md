# Workflows

**Docs home:** [Top Down Planning documentation](../README.md)

**Audience:** operators running TDP from first success through day-to-day operations.

These pages are procedures. Command catalogs, install, and recovery runbooks stay in the [operator manual](../manual/README.md). Agent request schemas stay under [runtime agents](../agents/README.md). Vocabulary: [lifecycle terms](../concepts/lifecycle-terms.md).

Host IDE planning modes are not part of these workflows. Production runs use `cursor`. `stub` is test-only.

## Pages

- [First run](first-run.md) — first successful `cursor` run; links to install/setup, then inspect, resume, and interpret the result
- [Lifecycle](lifecycle.md) — input and output goal through acceptance
- [Operations](operations.md) — `--until`, inspect, pause/resume, configuration drift
- [Prepared execution and Sub-TDPs](prepared-and-sub-tdp.md) — prepare/execute, parent/child, attach
- [Agent sessions](agent-sessions.md) — what operators see while planner, producer, and reviewer sessions run

Newcomers: [install](../manual/install.md) → [first run](first-run.md) → [lifecycle](lifecycle.md). Runtime agents: [agent hub](../agents/README.md#start-here).
