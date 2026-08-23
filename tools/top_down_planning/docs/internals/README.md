# Internals and maintenance

**Docs home:** [Top Down Planning documentation](../README.md)

**Audience:** maintainers changing configuration, persistence, reviews, packages, security, or extension points.

These pages are technical reference for **current** behavior. Enduring rationale: [design decisions](../decisions/README.md). Layer map: [architecture](../architecture/README.md). Operator how-to: [manual](../manual/README.md).

Python names here are maintainer vocabulary, not a user-facing API.

## Pages

- [Config and snapshots](config-and-snapshots.md) — resolution, digests, snapshots, drift, path containment
- [Persistence](persistence.md) — layout, CAS, journaling, atomic commits, crash recovery
- [Review architecture](reviews.md) — focused and mandatory reviews, families, audit, verification, limits
- [Prepared packages and Sub-TDPs](packages-and-sub-tdp.md) — integrity, lineage, attestations, synthesis
- [Security and reliability](security.md) — capability, redaction, containment, locks, platform limits
- [Maintenance](maintenance.md) — import boundaries, prompts, tests, packaging, safe change workflow
