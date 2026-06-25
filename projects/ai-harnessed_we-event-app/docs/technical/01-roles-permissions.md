# Roles & Permissions

## 1. Access Model
We Event uses RBAC with event-scope constraints:
- Role grants operation class.
- Scope determines which event and registration records the actor may affect.
- Sensitive actions require additional guardrails (reason + audit).

Roles:
- `OrganizerAdmin`
- `OrganizerStaff`
- `Participant`

## 2. Permission Matrix
| Capability | OrganizerAdmin | OrganizerStaff | Participant | System |
|---|---|---|---|---|
| Create/edit event draft | Yes | No | No | No |
| Publish/pause event | Yes | No | No | No |
| Configure rules/capacity/windows | Yes | No | No | No |
| View open events | Yes | Yes | Yes | No |
| Register for event | No | No | Yes | No |
| Cancel own registration | No | No | Yes (policy-bound) | No |
| Check in participant | Optional (if operating) | Yes (assigned events) | Self-check-in only when enabled | No |
| Submit feedback | No | No | Yes (own registration only) | No |
| Evaluate eligibility | No | No | No | Yes |
| Override eligibility (`Revoked`) | Yes (reason required) | No | No | No |
| Export reports | Yes | Scoped/optional | No | No |
| Read audit logs | Yes | Limited | No | No |

## 3. Scope Constraints
- `Participant` can only access own registration/check-in/feedback/eligibility records.
- `OrganizerStaff` can only operate on assigned events.
- `OrganizerAdmin` can operate on organization-owned events.
- System automation acts on explicit triggers and never bypasses invariants.

## 4. Sensitive Actions and Guardrails
Sensitive actions:
- Rule/capacity change after registration opens.
- Manual cancellation by organizer.
- Eligibility override or revocation.
- State-forcing transitions outside normal trigger schedule.

Required guardrails:
- Mandatory reason code + free-text reason.
- Actor identity and timestamp.
- Previous and new values (diff payload).
- Immutable audit record.

## 5. Authorization Decision Pattern
For each command:
1. Authenticate actor.
2. Validate role permission.
3. Validate event scope.
4. Validate state-transition guard.
5. Execute command in transaction.
6. Write audit record for critical action.

## 6. Minimum Audit Payload
```json
{
  "actorId": "uuid",
  "actorRole": "OrganizerAdmin",
  "action": "event.rule_config.updated",
  "entityType": "EventRuleConfig",
  "entityId": "uuid",
  "eventId": "uuid",
  "before": {},
  "after": {},
  "reasonCode": "CAPACITY_CHANGE",
  "reasonText": "Expanded seats due to venue update",
  "occurredAt": "2026-06-24T16:00:00Z"
}
```

## 7. BRD Traceability
- FR-25, FR-26, FR-27
- BR-20, BR-21, BR-22
- AC-11, AC-12
