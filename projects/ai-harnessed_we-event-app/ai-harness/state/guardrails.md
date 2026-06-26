# Guardrails (Ralph Signs)

Lessons learned across harness iterations. Read before every implementer session.

## Signs

<!-- Agent appends entries here after failures. Format: - [slice-id] lesson -->
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T082434Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083048Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083049Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083050Z-checks.json
- [repo-monorepo-bootstrap] Computational checks failed — see 20260625T083050Z-checks.json
- [docker-compose-db] Computational checks failed — see 20260625T091348Z-checks.json
- [api-foundation] AI review failed — see 20260625T092300Z-review.json
- [module-event] AI review failed — see 20260625T093544Z-review.json
- [module-registration] AI review failed — see 20260625T095129Z-review.json
- [web-design-system-shell] AI review failed — see 20260625T103226Z-review.json
- [web-design-system-shell] AI review failed — see 20260625T110259Z-review.json
- [web-design-system-shell] AI review failed — see 20260625T110938Z-review.json
- [web-design-system-shell] AI review failed — see 20260625T111833Z-review.json
- [web-participant-journeys] AI review failed — see 20260625T140938Z-review.json
- [web-participant-journeys] AI review failed — see 20260625T142403Z-review.json
- [pagination] List endpoints must return the paginated envelope (`items`, `page`, `pageSize`, `total`, `totalPages`) per `docs/technical/05-api-design.md` §3; bare arrays are deprecated.
- [pagination] Listing pages must not client-fetch all events then fan out N+1 registration calls for my-registrations; use `GET /me/registrations` with server-driven pagination.
- [module-event] AI review failed — see 20260625T150028Z-review.json
- [web-participant-journeys] AI review failed — see 20260625T153514Z-review.json
- [web-participant-journeys] AI review failed — see 20260625T154212Z-review.json
- [web-organizer-journeys] AI review failed — see 20260625T155640Z-review.json
- [module-registration] Computational checks failed — see 20260625T162337Z-checks.json
- [module-registration] Computational checks failed — see 20260625T170113Z-checks.json
- [module-registration] AI review failed — see 20260625T171051Z-review.json
- [web-organizer-journeys] AI review failed — see 20260625T174157Z-review.json
- [web-organizer-journeys] Computational checks failed — see 20260625T175157Z-checks.json
- [web-organizer-journeys] Computational checks failed — see 20260625T175615Z-checks.json
- [e2e-acceptance-suite] HTTP e2e dev tokens must use UUID `sub` values for organizers (DB actor columns) and participants (idempotency/feedback paths); non-UUID subs like `e2e-organizer-*` cause Postgres 22P02 errors.
- [module-user-accounts] Computational checks failed — see 20260625T183152Z-checks.json
- [module-user-accounts] Computational checks failed — see 20260625T191632Z-checks.json
- [web-design-system-shell] Computational checks failed — see 20260625T193720Z-checks.json
