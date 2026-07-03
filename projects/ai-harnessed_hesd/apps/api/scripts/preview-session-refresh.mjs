/**
 * Resets preview seed class sessions for performance-smoke Playwright runs.
 * Mirrors scripts/db-seed.mjs refreshSeedSessionFixtures scheduled row.
 */
import pg from "pg";

const SEED = {
  sessionScheduled: "70000000-0000-4000-8000-000000000001",
  section: "50000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
};

const databaseUrl =
  process.env.DATABASE_URL ?? "postgresql://postgres:postgres@localhost:5432/app";

async function main() {
  const pool = new pg.Pool({ connectionString: databaseUrl });
  const now = new Date();
  const scheduledStart = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const scheduledEnd = new Date(scheduledStart.getTime() + 90 * 60 * 1000);

  await pool.query(
    `
    DELETE FROM attendance_records WHERE class_session_id = $1
    `,
    [SEED.sessionScheduled],
  );
  await pool.query(
    `
    DELETE FROM check_in_attempts WHERE class_session_id = $1
    `,
    [SEED.sessionScheduled],
  );
  await pool.query(
    `
    DELETE FROM qr_session_tokens WHERE class_session_id = $1
    `,
    [SEED.sessionScheduled],
  );

  await pool.query(
    `
    INSERT INTO class_sessions (
      id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
    )
    VALUES ($1, $2, $3, $4, $5, 'Scheduled')
    ON CONFLICT (id) DO UPDATE SET
      class_section_id = EXCLUDED.class_section_id,
      room_id = EXCLUDED.room_id,
      scheduled_start_at = EXCLUDED.scheduled_start_at,
      scheduled_end_at = EXCLUDED.scheduled_end_at,
      state = 'Scheduled',
      opened_at = NULL,
      opened_by_user_id = NULL,
      closed_at = NULL,
      closed_by_user_id = NULL
    `,
    [SEED.sessionScheduled, SEED.section, SEED.room, scheduledStart, scheduledEnd],
  );

  await pool.end();
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
