# Components

Visual specs. Behavioral rules live in `../experience/3-component-patterns.md`.

- **Primary button** — `{components.button-primary}`. Full-width on student mobile. Min height 48px.
- **Danger button** — `{components.button-danger}`. End session, destructive roster replace.
- **Card** — `{components.card}`. Session summary, import result panels, check-in success/failure panels.
- **Input / select** — `{components.input}`. 3px focus border. Error state adds danger left border accent.
- **Attendance status badge** — Pill (`{rounded.full}`), compact: Present `{components.status-present}`, Absent `{components.status-absent}`, Failed `{components.status-failed}`, Manual Override `{components.status-override}`.
- **QR Display frame** — `{components.qr-display-frame}`. White canvas, thick border, large shadow. Session title above, countdown below QR, "HESD Workshop" meta label. `[ASSUMPTION]` HESD wordmark text-only in MVP — no logo asset required.
- **Data table** — 2px outer border, shadow-md, zebra rows via `{colors.neutral-secondary}` alternating. Sticky header on Instructor dashboard.
- **CSV upload zone** — Dashed 2px border (uses `{colors.border-default}`), brand background on drag-over.
- **Live indicator** — Small brand-filled square + caption "Đang cập nhật" (Instructor) / pulsing dot suppressed when Reduce Motion preferred.
