#!/usr/bin/env node
/**
 * Baseline seed fixtures for local and test stacks (term/course/section/session/roles).
 */
import pg from "pg";

const databaseUrl = process.env.DATABASE_URL ?? process.env.TEST_DATABASE_URL;
const SEED_ID = "infra-database-migrations-baseline";

/** Deterministic fixture IDs for integration tests and local smoke flows. */
const SEED_IDS = {
  faculty: "10000000-0000-4000-8000-000000000001",
  term: "20000000-0000-4000-8000-000000000001",
  course: "30000000-0000-4000-8000-000000000001",
  room: "40000000-0000-4000-8000-000000000001",
  section: "50000000-0000-4000-8000-000000000001",
  lecturerUser: "60000000-0000-4000-8000-000000000001",
  studentUsers: [
    "60000000-0000-4000-8000-000000000002",
    "60000000-0000-4000-8000-000000000003",
    "60000000-0000-4000-8000-000000000004",
  ],
  academicAdminUser: "60000000-0000-4000-8000-000000000005",
  sessionScheduled: "70000000-0000-4000-8000-000000000001",
  sessionOpen: "70000000-0000-4000-8000-000000000002",
  institutionPolicy: "80000000-0000-4000-8000-000000000001",
};

if (!databaseUrl) {
  console.error("db:seed — DATABASE_URL or TEST_DATABASE_URL is required");
  process.exit(1);
}

if (process.env.SEED_ENABLED === "false") {
  console.log("db:seed — skipped (SEED_ENABLED=false)");
  process.exit(0);
}

const client = new pg.Client({ connectionString: databaseUrl });

async function ensureSeedBookkeeping() {
  await client.query(`
    CREATE TABLE IF NOT EXISTS _attendly_seed_runs (
      id text PRIMARY KEY,
      seeded_at timestamptz NOT NULL DEFAULT now()
    )
  `);
}

async function isSeedApplied() {
  const result = await client.query(
    "SELECT 1 FROM _attendly_seed_runs WHERE id = $1",
    [SEED_ID],
  );
  return (result.rowCount ?? 0) > 0;
}

async function markSeedApplied() {
  await client.query(
    `
    INSERT INTO _attendly_seed_runs (id)
    VALUES ($1)
    ON CONFLICT (id) DO NOTHING
    `,
    [SEED_ID],
  );
}

async function seedFixtures() {
  const now = new Date();
  const termStart = "2026-01-15";
  const termEnd = "2026-06-30";
  const scheduledStart = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const scheduledEnd = new Date(scheduledStart.getTime() + 90 * 60 * 1000);
  const openStart = new Date(now.getTime() - 15 * 60 * 1000);
  const openEnd = new Date(openStart.getTime() + 90 * 60 * 1000);

  await client.query("BEGIN");
  try {
    await client.query(
      `
      INSERT INTO faculties (id, code, name, is_active)
      VALUES ($1, 'CNTT', 'Công nghệ thông tin', true)
      ON CONFLICT (id) DO NOTHING
      `,
      [SEED_IDS.faculty],
    );

    await client.query(
      `
      INSERT INTO terms (id, code, name, start_date, end_date, is_active)
      VALUES ($1, '2026-1', 'Học kỳ 1 năm 2026', $2, $3, true)
      ON CONFLICT (id) DO NOTHING
      `,
      [SEED_IDS.term, termStart, termEnd],
    );

    await client.query(
      `
      INSERT INTO courses (id, code, name, faculty_id, credit_units, is_active)
      VALUES ($1, 'SE101', 'Nhập môn phần mềm', $2, 3, true)
      ON CONFLICT (id) DO NOTHING
      `,
      [SEED_IDS.course, SEED_IDS.faculty],
    );

    await client.query(
      `
      INSERT INTO rooms (id, code, building, name, latitude, longitude, is_active)
      VALUES ($1, 'A101', 'Tòa A', 'Phòng A101', 10.762622, 106.660172, true)
      ON CONFLICT (id) DO NOTHING
      `,
      [SEED_IDS.room],
    );

    const users = [
      {
        id: SEED_IDS.lecturerUser,
        email: "lecturer@attendly.local",
        displayName: "Nguyễn Văn Giảng",
      },
      {
        id: SEED_IDS.studentUsers[0],
        email: "student1@attendly.local",
        displayName: "Trần Thị Sinh Viên",
      },
      {
        id: SEED_IDS.studentUsers[1],
        email: "student2@attendly.local",
        displayName: "Lê Văn Học",
      },
      {
        id: SEED_IDS.studentUsers[2],
        email: "student3@attendly.local",
        displayName: "Phạm Minh An",
      },
      {
        id: SEED_IDS.academicAdminUser,
        email: "academic-admin@attendly.local",
        displayName: "Hoàng Quản Trị",
      },
    ];

    for (const user of users) {
      await client.query(
        `
        INSERT INTO users (id, email, display_name, is_active)
        VALUES ($1, $2, $3, true)
        ON CONFLICT (id) DO NOTHING
        `,
        [user.id, user.email, user.displayName],
      );
    }

    await client.query(
      `
      INSERT INTO lecturer_profiles (user_id, staff_code, faculty_id)
      VALUES ($1, 'GV001', $2)
      ON CONFLICT (user_id) DO NOTHING
      `,
      [SEED_IDS.lecturerUser, SEED_IDS.faculty],
    );

    const studentCodes = ["SV001", "SV002", "SV003"];
    for (let i = 0; i < SEED_IDS.studentUsers.length; i++) {
      await client.query(
        `
        INSERT INTO student_profiles (user_id, student_code, faculty_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO NOTHING
        `,
        [SEED_IDS.studentUsers[i], studentCodes[i], SEED_IDS.faculty],
      );
    }

    await client.query(
      `
      INSERT INTO class_sections (
        id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
      )
      VALUES ($1, 'SE101-01', $2, $3, $4, $5, 60, true)
      ON CONFLICT (id) DO NOTHING
      `,
      [
        SEED_IDS.section,
        SEED_IDS.term,
        SEED_IDS.course,
        SEED_IDS.lecturerUser,
        SEED_IDS.room,
      ],
    );

    for (const studentId of SEED_IDS.studentUsers) {
      await client.query(
        `
        INSERT INTO enrollments (id, class_section_id, student_user_id, status)
        VALUES (gen_random_uuid(), $1, $2, 'Active')
        ON CONFLICT (class_section_id, student_user_id) DO NOTHING
        `,
        [SEED_IDS.section, studentId],
      );
    }

    await client.query(
      `
      INSERT INTO class_sessions (
        id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
      )
      VALUES ($1, $2, $3, $4, $5, 'Scheduled')
      ON CONFLICT (id) DO NOTHING
      `,
      [SEED_IDS.sessionScheduled, SEED_IDS.section, SEED_IDS.room, scheduledStart, scheduledEnd],
    );

    await client.query(
      `
      INSERT INTO class_sessions (
        id,
        class_section_id,
        room_id,
        scheduled_start_at,
        scheduled_end_at,
        state,
        opened_at,
        opened_by_user_id
      )
      VALUES ($1, $2, $3, $4, $5, 'Open', $6, $7)
      ON CONFLICT (id) DO NOTHING
      `,
      [
        SEED_IDS.sessionOpen,
        SEED_IDS.section,
        SEED_IDS.room,
        openStart,
        openEnd,
        openStart,
        SEED_IDS.lecturerUser,
      ],
    );

    const roleAssignments = [
      {
        id: "90000000-0000-4000-8000-000000000001",
        userId: SEED_IDS.lecturerUser,
        role: "Lecturer",
        scopeType: "ClassSection",
        scopeId: SEED_IDS.section,
      },
      {
        id: "90000000-0000-4000-8000-000000000002",
        userId: SEED_IDS.academicAdminUser,
        role: "AcademicAdmin",
        scopeType: "Institution",
        scopeId: null,
      },
      ...SEED_IDS.studentUsers.map((userId, index) => ({
        id: `90000000-0000-4000-8000-0000000000${10 + index}`,
        userId,
        role: "Student",
        scopeType: "Self",
        scopeId: userId,
      })),
    ];

    for (const assignment of roleAssignments) {
      await client.query(
        `
        INSERT INTO user_role_assignments (id, user_id, role, scope_type, scope_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (user_id, role, scope_type, scope_id) DO NOTHING
        `,
        [
          assignment.id,
          assignment.userId,
          assignment.role,
          assignment.scopeType,
          assignment.scopeId,
        ],
      );
    }

    await client.query(
      `
      INSERT INTO attendance_policies (
        id,
        scope_type,
        scope_id,
        present_window_minutes,
        late_window_minutes,
        manual_edit_window_hours,
        gps_required,
        gps_radius_meters,
        is_active
      )
      VALUES ($1, 'Institution', NULL, 15, 15, 24, false, 100, true)
      ON CONFLICT (id) DO NOTHING
      `,
      [SEED_IDS.institutionPolicy],
    );

    await markSeedApplied();
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  }
}

try {
  await client.connect();
  await ensureSeedBookkeeping();

  if (await isSeedApplied()) {
    console.log(`db:seed — skip ${SEED_ID} (already applied)`);
    process.exit(0);
  }

  const tables = await client.query(
    `
    SELECT to_regclass('public.users') AS regclass
    `,
  );
  if (!tables.rows[0]?.regclass) {
    console.error("db:seed — users table missing; run db:migrate first");
    process.exit(1);
  }

  await seedFixtures();
  console.log("db:seed — baseline fixtures applied");
} catch (error) {
  console.error("db:seed — failed:", error);
  process.exit(1);
} finally {
  await client.end().catch(() => undefined);
}
