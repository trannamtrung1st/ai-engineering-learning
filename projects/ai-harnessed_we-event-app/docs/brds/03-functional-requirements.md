# We Event BRD - Functional Requirements

## 1. Requirement Format
- Requirement ID: `FR-xx`
- Actor type: Organizer Admin, Organizer Staff, Participant, System
- Objective: describe the business value to be delivered

## 2. Event Management
- FR-01: Organizer Admin can create an event with basic information (name, description, time, location, organizing unit).
- FR-02: Organizer Admin can configure maximum event capacity.
- FR-03: Organizer Admin can configure registration open/close timing.
- FR-04: Organizer Admin can publish/pause an event.

## 3. Registration and Capacity
- FR-05: Participant can view events currently open for registration.
- FR-06: Participant can register at most once per event (duplicate prevention).
- FR-07: System automatically assigns `Registered` if seats are available.
- FR-08: System automatically assigns `Waitlisted` if full and waitlist is enabled.
- FR-09: System automatically rejects registration if full and waitlist is disabled.
- FR-10: Participant can track registration status in near real-time.
- FR-11: Participant can cancel registration under allowed conditions.
- FR-12: System automatically promotes from waitlist to `Registered` when a seat becomes available.

## 4. Check-in and Attendance
- FR-13: Organizer Staff can check in participants.
- FR-14: Participant can self check-in when self-service check-in is enabled.
- FR-15: System only records valid check-ins within the configured check-in window.
- FR-16: System stores check-in history (timestamp, check-in source, operator).
- FR-17: System updates attendance status (`Attended`/`Absent`) after event completion.

## 5. Feedback and Certificate
- FR-18: Organizer Admin can configure feedback as mandatory/optional.
- FR-19: Participant can submit feedback after the event within the allowed window.
- FR-20: System evaluates certificate eligibility using configured business rules.
- FR-21: Organizer Admin can view participant lists that are eligible/not eligible for certificate.

## 6. Monitoring and Reporting
- FR-22: Organizer Admin can view event overview (registrations, waitlist, check-ins, feedback).
- FR-23: Organizer Admin can retrieve registration status change history.
- FR-24: Organizer Admin can export event operational data for internal reporting.

## 7. Access and Roles
- FR-25: System enforces role-based access (Admin, Staff, Participant).
- FR-26: Participant can only operate on their own registration data.
- FR-27: Staff can only operate within assigned event scope.
