# Spec: Attendance reporting

**Status:** approved

## Goal

Make recorded attendance visible after the fact: a student can review their own attendance history per enrolled section, and a lecturer can see a per-section summary of every enrolled student and export it as CSV, with each export audited.

## Requirements

- WHEN a logged-in student opens their attendance history THEN they see, for each section they are enrolled in, every past class session with their status (Present, Late, Absent, Excused, Manual Present) or "no record" for sessions where attendance was never resolved
- WHEN a student views their history for a section THEN they also see per-status totals for that section (e.g. 8 Present, 1 Late, 1 Absent)
- WHEN a student attempts to view attendance history that is not their own THEN the request is rejected
- WHEN the owning lecturer opens the report for one of their sections THEN they see one row per enrolled student with per-status counts across that section's sessions and an attendance rate (Present + Late + Manual Present + Excused over resolved sessions)
- WHEN a lecturer requests a report for a section they do not own THEN the request is rejected
- WHEN the owning lecturer exports a section report THEN the system returns a CSV containing the same rows as the on-screen report (student, per-status counts, attendance rate)
- WHEN a CSV export completes THEN an audit entry records who exported which section and when
- WHEN demo seed data is loaded THEN at least one section has enough resolved attendance across more than one session that the student history and lecturer report show mixed statuses (not all Present)

## Out of scope

- Reports across courses, terms, or the whole school — this slice is per-section only (no Term/Course entities exist yet)
- Absence-threshold alerts and notifications (BR-17) — the report shows rates, it does not warn anyone
- Excel export or SIS API integration — CSV only
- Realtime/live dashboard during an open session — this is after-the-fact reporting
- Academic Admin or other new roles — only the existing student and lecturer roles see reports
- Filtering, sorting, pagination, or date-range controls beyond a plain per-section view

## Acceptance criteria

- [ ] A seeded student can log in and see their own per-session history and per-status totals for their enrolled section
- [ ] A student cannot retrieve another student's history
- [ ] The seeded lecturer can view the section report showing every enrolled student with per-status counts and attendance rate
- [ ] A lecturer cannot view or export a report for a section they do not own
- [ ] CSV export downloads with the same data as the on-screen report and produces an audit entry (actor, section, timestamp)
- [ ] Seed data alone produces a demo where statuses are mixed across at least two sessions
