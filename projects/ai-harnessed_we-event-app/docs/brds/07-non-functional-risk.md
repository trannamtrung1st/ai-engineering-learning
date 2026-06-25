# We Event BRD - Non-functional Requirements and Risks

## 1. Non-functional Requirements

## 1.1 Availability and Reliability
- NFR-01: System remains available during event registration peak windows.
- NFR-02: Registration/check-in transactions must ensure data consistency and prevent double booking.
- NFR-03: Data backup and recovery mechanisms are available for incident scenarios.

## 1.2 Performance
- NFR-04: Registration actions must respond quickly under normal load.
- NFR-05: Event list and event detail pages load within acceptable levels on typical campus networks; list views fetch one page at a time rather than loading the entire catalog.
- NFR-06: Event operations dashboard data updates in near real-time for organizers.
- NFR-16: Paginated list endpoints return a single page within acceptable response time when total results exceed 500 rows.

## 1.3 Security and Privacy
- NFR-07: User authentication is required before sensitive operations.
- NFR-08: Authorization is enforced by role and event scope.
- NFR-09: Participant personal data is protected and displayed only as required by business needs.
- NFR-10: All critical operations must have audit logs for traceability.

## 1.4 Usability and Accessibility
- NFR-11: Registration/check-in flows must be clear, low-step, and usable on common devices.
- NFR-12: Registration status notifications must be understandable and consistent.
- NFR-13: Critical actions must provide immediate feedback (success/fail/reason).

## 1.5 Maintainability and Operability
- NFR-14: Event-level business configuration can be updated without complex technical intervention.
- NFR-15: System provides basic logs and metrics for operations and incident handling.

## 2. Risks

| Risk ID | Risk description | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R-01 | Registration spikes in a short period cause overload | High | Medium | Rate limiting, registration flow optimization, infrastructure scaling |
| R-02 | Misconfigured business rules produce incorrect certificate results | High | Medium | Rule templates, result preview, config-change audit |
| R-03 | On-site check-in disrupted by weak network | Medium | High | Retry mechanism, clear status feedback, fallback check-in option |
| R-04 | Users are unfamiliar with new system and continue old tools | Medium | Medium | Lightweight onboarding, role-based guidance, phased rollout |
| R-05 | Data inconsistencies caused by manual operations outside system | Medium | Medium | Single source of truth process, restricted manual import, post-event reconciliation |

## 3. Risk Monitoring
- Track metrics: registration failure rate, check-in success rate, feedback completion rate.
- Conduct post-event reviews to refine rules and operations.
