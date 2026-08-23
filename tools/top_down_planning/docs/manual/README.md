# User and operator manual

**Docs home:** [Top Down Planning documentation](../README.md)

**Audience:** operators installing, configuring, and running TDP.

This section is the canonical reference for install, user CLI, configuration, run-store inspection, observability, and recovery. First-run and staged-operations walkthroughs live under [workflows](../workflows/README.md) and link here. Runtime-agent commands live under [agents](../agents/README.md).

## Pages

- [Install and setup](install.md) — prerequisites, installation, provider setup, minimal config
- [User CLI](cli.md) — `run`, `prepare`, `execute`, `resume`, `status`, `inspect`, `validate`, `doctor`, `sub-tdp attach`
- [Configuration](configuration.md) — precedence, paths, contracts, overlays, limits, provider
- [Run store](run-store.md) — outputs and inspection without hand-editing orchestrator state
- [Observability](observability.md) — logging, stream JSON, transcripts, notifications
- [Troubleshooting](troubleshooting.md) — cancellation, concurrency, common errors, diagnosis, recovery

Production runs use the `cursor` provider. The `stub` provider is test-only. Host IDE planning modes are not part of the operator workflow.
