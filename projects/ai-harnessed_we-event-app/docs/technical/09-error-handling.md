# Error Handling

## 1. Error Handling Goals
- Predictable failure semantics for clients.
- User-safe messages with actionable context.
- Rich internal diagnostics and auditability.

## 2. Error Taxonomy
## 2.1 Validation Errors (`400`, `422`)
- malformed payload
- invalid enum/state value
- semantic window/policy violations

## 2.2 Authorization Errors (`401`, `403`)
- missing/invalid auth token
- role or scope mismatch

## 2.3 Domain Conflict Errors (`409`)
- duplicate active registration
- illegal state transition
- duplicate check-in
- stale version update conflict

## 2.4 Not Found Errors (`404`)
- event/registration not found
- out-of-scope entities intentionally hidden

## 2.5 Internal Errors (`500`)
- transaction failures
- persistence failures
- unhandled domain exceptions

## 3. Standard Error Response
```json
{
  "error": {
    "code": "CHECKIN_WINDOW_CLOSED",
    "message": "Check-in is not available at this time.",
    "details": {
      "checkinOpenAt": "2026-06-24T08:00:00Z",
      "checkinCloseAt": "2026-06-24T10:00:00Z"
    },
    "requestId": "uuid",
    "timestamp": "2026-06-24T09:30:00Z"
  }
}
```

## 4. Error Code Catalog (MVP)
- `REGISTRATION_DUPLICATE_ACTIVE`
- `REGISTRATION_WINDOW_CLOSED`
- `REGISTRATION_REJECTED_FULL`
- `CAPACITY_EXCEEDED`
- `CANCELLATION_DEADLINE_PASSED`
- `CANCELLATION_NOT_ALLOWED`
- `CHECKIN_WINDOW_CLOSED`
- `CHECKIN_ALREADY_RECORDED`
- `FEEDBACK_NOT_ALLOWED`
- `FEEDBACK_DUPLICATE`
- `FEEDBACK_REQUIRED`
- `NOT_ELIGIBLE_ATTENDANCE`
- `NOT_ELIGIBLE_FEEDBACK`
- `ELIGIBILITY_OVERRIDE_FORBIDDEN`
- `EVENT_RULE_CHANGE_FORBIDDEN`
- `AUDIT_REQUIRED_FOR_CRITICAL_CHANGE`
- `INVALID_STATE_TRANSITION`

## 5. Retry and Idempotency Policy
- Clients may safely retry idempotent write requests using `Idempotency-Key`.
- Conflict errors should not be auto-retried without fetching latest state.
- Time-window failures require user action; no blind retries.

## 6. Logging and Audit Correlation
Every error log includes:
- `requestId`
- `actorId` (if authenticated)
- `eventId`/`registrationId` where relevant
- `errorCode`
- stack trace (server-side only)

Critical failures affecting business state:
- Create audit entry when failure occurs after partial transition attempt.
- Roll back transaction to preserve invariants.

## 7. User Messaging Guidelines
- Avoid exposing internal DB or stack-trace details.
- Message explains what failed and what user can do next.
- Prefer policy wording over technical jargon.

## 8. Local Development Failure Drills
- Simulate race on registration.
- Simulate out-of-window check-in.
- Simulate invalid admin override (missing reason).
- Validate proper error code + status + audit/log behavior.

## 9. BRD Traceability
- NFR-10, NFR-13, NFR-15
- BR-10, BR-13, BR-19..BR-22
- AC-11, AC-12
