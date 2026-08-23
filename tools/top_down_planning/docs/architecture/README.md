# Architecture

**Docs home:** [Top Down Planning documentation](../README.md)

**Audience:** maintainers locating layer ownership and system shape.

These pages describe **current** TDP architecture. They are not a public API freeze: Python module and type names here are maintainer vocabulary. Operator procedures stay in the [manual](../manual/README.md). Persistence, review-loop mechanics, package integrity, and security controls: [internals](../internals/README.md). Why some of these shapes exist: [design decisions](../decisions/README.md).

## Pages

- [System context](system-context.md) — layers and the `core_tools` boundary
- [Lifecycle architecture](lifecycle.md) — phases, review stages, ownership, outcomes
- [Domain model](domain.md) — plans, production, reviews, dispositions, acceptance
- [Sessions](sessions.md) — context, provider binding, activity boundaries, cleanup
