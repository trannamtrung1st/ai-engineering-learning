# §21 test matrix ownership (plan extensions)

Single owner per named test or E2E scenario. Plan extensions beyond proposal §5.1:
`amendment_pending`; production limit; focused limit; amendment `max_requests` resumable
after run-level pause.

**Note:** mandatory `whole_plan` / `whole_output` `review_incomplete` pauses the run;
focused `review_incomplete` is loop-level retry without run pause.

## Phase 1 band

| Test / scenario | Owner |
| --- | --- |
| §21 tests 1–5 | 1.1.2 pause + 1.3.2 / 1.5.4 / 1.6 E2E (`item-e2f06d5fb3bf`) |
| §21 test 9 (`user_cancelled`) | 1.1.2 + 1.3.3 |
| §21 test 10 (`review_incomplete`) | 1.1.2 + 1.3.2 (mandatory whole_* only) |
| §21 test 31 (startup replacement) | 1.1.2 + 1.5.3 |
| §21 test 39 (ordinary-turn replacement-path) | 1.1.2 + 1.5.3 |
| §21 test 42 (old schema rejected) | 1.1.1 + 1.1.2 + 1.1.3 + 1.2.1 coordinated batch |
| `test_resume_production_limit_exhausted` | 1.1.2 |
| `test_resume_focused_limit_exhausted` | 1.1.2 |
| `test_resume_scope_review_limit_exhausted` | 1.1.2 |
| `test_resume_planning_item_limit_exhausted` | 1.1.2 |

## Phase 2 band

| Test / scenario | Owner |
| --- | --- |
| §21 tests 6–7 | 1.2.2 |
| §21 tests 15–17 | 1.2.1 + 1.3.1 / 1.2.2 + 1.3.1 |
| §21 tests 18–20 | 1.2.1 |
| §21 test 8 (apply path) | 1.2.2 + 1.3.2 apply |

## Phase 3 band

| Test / scenario | Owner |
| --- | --- |
| §21 tests 11–14, 21, 45 | 1.3.1 |
| §21 test 22, 43 | 1.3.3 |
| §21 test 23, 35–36 | 1.3.2 |
| §21 test 24, §10.1-E2E | 1.3.4 (+ 1.6 full E2E) |
| §21 test 44 (failed-run rejection) | 1.3.1 + 1.3.3 (§10.4) |
| `test_prepare_resume_conflicting_review_loops` | 1.3.1 |
| `test_resume_amendment_pending` | 1.3.2 |
| `test_resume_mandatory_review_incomplete_continue` | 1.3.2 |
| `test_resume_provider_unavailable` / `test_resume_provider_turn_failed` / `test_resume_user_cancelled` | 1.3.2 |
| `test_resume_limit_only_counters_unchanged` | 1.3.2 |
| increase+resume E2E (`test_resume_cross_phase_e2e`) | 1.5.4 (`item-e2f06d5fb3bf`) |

## Phase 4 band

| Test / scenario | Owner |
| --- | --- |
| §21 test 37 | 1.4.3 completion gate |
| §21 test 40 | 1.4.1 |

## Phase 5 band

| Test / scenario | Owner |
| --- | --- |
| §21 tests 25–30 | 1.5.2 |
| §21 tests 32–34, 38, 41 | 1.5.3 |
| §21 test 39 replacement-path | 1.5.3 |
