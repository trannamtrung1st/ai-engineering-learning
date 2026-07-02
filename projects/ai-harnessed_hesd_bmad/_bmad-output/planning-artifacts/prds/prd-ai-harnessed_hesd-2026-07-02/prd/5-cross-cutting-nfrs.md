# 5. Cross-Cutting NFRs

### NFR-1: Concurrent check-in load

System supports at least **150 Check-In Attempts within a 10-minute window** per Active session without degrading below FR-14 latency target.

### NFR-2: Availability during workshops

**99% uptime** during scheduled HESD workshop hours for pilot term.

### NFR-3: Mobile web compatibility

Student check-in works on current versions of **Chrome and Safari on iOS and Android**.

### NFR-4: Accessibility

Student check-in flow meets **WCAG 2.1 AA** for forms, errors, and success states.

### NFR-5: Data retention

Attendance Records and Audit Log Entries retained **minimum 90 days** from session date.

### NFR-6: Location data handling

GPS coordinates used only for Geofence validation at check-in time; raw coordinates stored in Audit Log Entry for failed attempts only. Not displayed to other Students.

---
