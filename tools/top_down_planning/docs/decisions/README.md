# Design decisions

**Docs home:** [Top Down Planning documentation](../README.md)

**Audience:** maintainers who need evidenced rationale for enduring TDP choices.

These records describe **verified current behavior** and its consequences. They cite tests, domain modules, and packaged agent guidance. They do **not** invent dates, discarded alternatives, or motivations. Source comments that mention a “proposal” are implementation provenance only — not a claim that this documentation set includes that proposal.

Architecture and internals describe *how* the system is shaped. These pages record *which* choices are binding.

`tests/unit/test_design_decisions.py` asserts a set of current invariants (recoverable `paused`, invariant `failed`, completed outcomes, no separate `resumable` field, structured stops, split config digests, replaceable session bindings, recovery manifests, pure `prepare_resume`, run ownership, run `schema_version` 3). Each record below points at those tests plus the modules that enforce them.

## Records

- [Lifecycle stop states](lifecycle-stop-states.md)
- [Split configuration digests and drift policy](split-config-digests.md)
- [Replaceable session bindings and recovery manifests](session-bindings.md)
- [Run ownership and concurrency](run-ownership.md)
- [Agent-tool authorization](agent-authorization.md)
- [Prepared-execution integrity](prepared-execution-integrity.md)

Related: [lifecycle terms](../concepts/lifecycle-terms.md), [architecture](../architecture/README.md), [internals](../internals/README.md).
