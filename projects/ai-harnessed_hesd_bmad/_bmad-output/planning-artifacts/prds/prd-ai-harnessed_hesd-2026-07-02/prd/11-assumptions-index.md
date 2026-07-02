# 11. Assumptions Index

Confirmed at finalize unless marked pilot-validate:

- **A-1:** Primary UI locale is Vietnamese for Student and Instructor flows; documentation remains English.
- **A-2:** Admin and Instructor use web dashboards; Student uses mobile web only.
- **A-3:** Auth is email + password; no SSO.
- **A-4:** CSV import without password generates one-time temporary password in result.
- **A-5:** Admin can create Instructor accounts.
- **A-6:** Session lifecycle: draft → scheduled → active → closed.
- **A-7:** Realtime dashboard updates within 5 seconds at 150 users — pilot-validate.
- **A-8:** 90-day minimum data retention.
- **A-9:** GPS coordinates stored for failed attempts only in audit.
- **A-10:** Admin and Instructor share one web app with role-gated routes.
