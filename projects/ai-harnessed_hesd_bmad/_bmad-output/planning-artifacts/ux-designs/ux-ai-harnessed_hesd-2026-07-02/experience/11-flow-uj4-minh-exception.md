# Flow UJ-4 — Minh handles an exception and closes

**Persona:** Minh (Instructor)  
**PRD ref:** UJ-4

## Steps

1. On live dashboard, Minh filters/search student showing **Failed** / `gps_out_of_range`.
2. Opens **Manual Override** → sets Present, enters reason "GPS lỗi — có mặt tại lớp".
3. Ends session → **Closed**.
4. Exports CSV; row count matches roster size.
5. **Climax:** CSV downloaded; spot-check shows override source column.

## Surfaces touched

- Live attendance dashboard
- Manual override modal
- Session — lifecycle (close)
- CSV export

## Related

- `3-component-patterns.md` (live attendance table, manual override modal)
- `4-state-patterns.md` (session closed, 150-row table)
