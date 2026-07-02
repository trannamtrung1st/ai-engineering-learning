# Interaction Primitives

- **Tap / click** primary action per screen — one brand CTA on student flow.
- **Submit** check-in only after GPS sample acquired (loading spinner on button, max 10s `[ASSUMPTION]` then timeout error).
- **Auto-refresh** QR bitmap every 30s without full page reload.
- **Polling** attendance table every ~3s while session Active; pause when tab hidden.
- **Confirm sheet** for destructive actions: close session, roster replace import, manual override.
- **No** student push notifications, password-reset email, or offline queue in MVP.
- **Banned:** skipping GPS modal, auto-retry check-in without user tap, carousel onboarding.
