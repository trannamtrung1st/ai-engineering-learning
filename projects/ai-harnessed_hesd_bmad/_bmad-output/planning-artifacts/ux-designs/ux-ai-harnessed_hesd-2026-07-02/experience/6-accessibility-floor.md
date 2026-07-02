# Accessibility Floor

NFR-4 scopes **WCAG 2.1 AA** to **student check-in flow**. Admin/Instructor: best-effort AA on forms and tables `[ASSUMPTION]`.

- All form fields labeled; errors associated with `aria-describedby`.
- Student outcome screens: headline + body + CTA focus order top-to-bottom.
- Color status badges always paired with text label (not color-only).
- Tap targets ≥ 48px on student mobile.
- QR Display: minimum 4.5:1 contrast on session title and countdown (see `{colors.heading}` on `{colors.neutral-primary}`).
- `prefers-reduced-motion`: disable live-indicator pulse; instant QR swap without animation.
- Projector mode: QR Display supports browser full-screen (F11); no hover-only controls on QR surface.
