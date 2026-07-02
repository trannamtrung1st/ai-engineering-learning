# Flow UJ-1 — Linh provisions the cohort

**Persona:** Linh (Admin)  
**PRD ref:** UJ-1

## Steps

1. Linh downloads student CSV template.
2. Uploads `students.csv` → reviews per-row errors (duplicate email row 12).
3. Fixes file, re-imports.
4. Creates roster, imports roster CSV (append mode).
5. **Climax:** Dashboard shows 120 students, 0 import errors.

## Surfaces touched

- Admin dashboard
- Students — CSV import
- Rosters — list / detail / CSV import

## Related

- `1-information-architecture.md` (Admin surfaces)
- `3-component-patterns.md` (CSV import panel, roster import mode)
- `4-state-patterns.md` (import partial failure)
