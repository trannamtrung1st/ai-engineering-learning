---
name: tdd
description: >-
  Test-Driven Development using red-green-refactor. Tests express expected
  behavior from requirements before implementation — never retrofit tests to
  match code written first. Use when adding features, fixing bugs, writing unit
  tests, or when the user mentions TDD, test-first, or red-green-refactor.
---

# TDD (Red-Green-Refactor)

Tests are the **contract** for behavior. Write them from expected outcomes (spec, domain rules, acceptance criteria), then implement the minimum code to satisfy them.

## When to apply

**Use TDD** when adding or changing observable behavior: features, bug fixes, API/CLI semantics, validation rules, state transitions.

**Skip new tests** for docs-only edits, comments, or pure refactors that do not change behavior. Do not write tests that only restate the obvious (e.g. asserting a constant returns itself).

## Workflow

1. **Name the behavior** — one sentence: "when X, system does Y".
2. **Red** — write a failing test with concrete inputs and **expected** outputs derived from requirements, not from existing code.
3. **Confirm red** — run the test; failure must be missing/wrong behavior, not a typo or import error.
4. **Green** — smallest production change that makes the test pass.
5. **Refactor** — improve structure; keep tests green.

Repeat per case: happy path first, then edges (empty, boundary, errors).

## Tests are the contract

- Assert **observable behavior**: return values, raised errors, persisted state, CLI exit codes/messages.
- Do not assert private helpers, call order, or internal structure unless that structure *is* the requirement.
- Expected values come from specs and domain rules — **not** from reading what the code currently returns.
- When a test fails after implementation, **fix production code**. Only change the test when the requirement was wrong.

## Bug fixes

1. Write a failing test that captures the **correct** expected behavior (reproduction).
2. Fix production code until green.
3. Never weaken or delete the test to match a bug.

## Anti-patterns

```python
# BAD — implement first, then mirror the accident in tests
def parse_tokens(s):
    return s.split(",")  # no trim, wrong for spec

def test_parse_tokens():
    assert parse_tokens("a,b") == ["a", "b"]  # copied from running code

# GOOD — spec: split on comma, trim whitespace, "" → []
def test_parse_tokens_splits_and_trims():
    assert parse_tokens(" a , b ") == ["a", "b"]

def test_parse_tokens_empty_string_returns_empty_list():
    assert parse_tokens("") == []
# then implement parse_tokens to satisfy both
```

Other anti-patterns:

- Changing assertions because "the code does X" when the spec says Y
- Skipping or deleting tests to make CI pass
- Over-mocking so the test only verifies the mock, not behavior
- Writing tests that import and call private functions

## Test naming

`test_<behavior>_when_<condition>` — describe outcome, not implementation.

## With `tools/` packages

Read `.cursor/skills/tools-dev/SKILL.md` for fakes/stubs and fast-test conventions. TDD order is unchanged: red → green → refactor, using `StubProvider`, `run_cli()`, and package helpers — not live I/O.

## Checklist

- [ ] Expected outcomes written before production code (or before the bug fix)
- [ ] Test failed for the right reason before implementation
- [ ] Implementation is the minimum to pass
- [ ] Assertions match requirements, not current code
- [ ] Refactor did not change observable behavior
