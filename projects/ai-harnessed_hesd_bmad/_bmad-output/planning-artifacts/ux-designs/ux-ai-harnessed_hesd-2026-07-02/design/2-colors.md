# Colors

Palette inherits Neobrutalism tokens. Product-specific usage rules:

- **Brand Yellow (`{colors.brand}`)** — primary actions (check in, activate session, export CSV), QR Display accent band, active nav item fill. Never used for body paragraphs.
- **Neutrals (`{colors.neutral-primary}` / `{colors.neutral-secondary}`)** — page canvas and section bands. Admin/Instructor surfaces alternate secondary for table sections.
- **Heading Black (`{colors.heading}`)** — all Archivo Black headlines, borders, shadow color in light mode. Signature outline color.
- **Body Gray (`{colors.body}`)** — supporting copy, table metadata, timestamps.
- **Success (`{colors.success}`)** — Present status, check-in success screen background accent.
- **Danger (`{colors.danger}`)** — Failed status, destructive confirmations, check-in failure hero band.
- **Warning (`{colors.warning}`)** — Manual Override badge, draft-session reminders.

`[ASSUMPTION]` Light mode is the MVP default on all surfaces (projector legibility). Dark mode tokens exist in the design system but are not required for MVP.

Avoid: gradients on layout surfaces, soft/blurred shadows, rounded card corners, decorative accent colors (purple, sky, teal) on navigation or body copy.
