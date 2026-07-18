import { integer, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

const timestamps = {
  createdAt: integer("created_at", { mode: "timestamp_ms" })
    .notNull()
    .$defaultFn(() => new Date()),
};

export const users = sqliteTable(
  "users",
  {
    id: text("id").primaryKey(),
    email: text("email").notNull(),
    name: text("name").notNull(),
    role: text("role", { enum: ["student", "lecturer"] }).notNull(),
    passwordHash: text("password_hash").notNull(),
    ...timestamps,
  },
  (table) => [uniqueIndex("users_email_unique").on(table.email)],
);

export const classSections = sqliteTable("class_sections", {
  id: text("id").primaryKey(),
  name: text("name").notNull(),
  lecturerId: text("lecturer_id")
    .notNull()
    .references(() => users.id),
  presentWindowMinutes: integer("present_window_minutes").notNull(),
  lateWindowMinutes: integer("late_window_minutes").notNull(),
  ...timestamps,
});

export const enrollments = sqliteTable(
  "enrollments",
  {
    id: text("id").primaryKey(),
    classSectionId: text("class_section_id")
      .notNull()
      .references(() => classSections.id),
    studentId: text("student_id")
      .notNull()
      .references(() => users.id),
    ...timestamps,
  },
  (table) => [
    uniqueIndex("enrollments_section_student_unique").on(
      table.classSectionId,
      table.studentId,
    ),
  ],
);

export const classSessions = sqliteTable("class_sessions", {
  id: text("id").primaryKey(),
  classSectionId: text("class_section_id")
    .notNull()
    .references(() => classSections.id),
  startsAt: integer("starts_at", { mode: "timestamp_ms" }).notNull(),
  attendanceOpenedAt: integer("attendance_opened_at", { mode: "timestamp_ms" }),
  attendanceClosedAt: integer("attendance_closed_at", { mode: "timestamp_ms" }),
  ...timestamps,
});

export const qrSessionTokens = sqliteTable("qr_session_tokens", {
  id: text("id").primaryKey(),
  classSessionId: text("class_session_id")
    .notNull()
    .references(() => classSessions.id),
  tokenHash: text("token_hash").notNull(),
  expiresAt: integer("expires_at", { mode: "timestamp_ms" }).notNull(),
  ...timestamps,
});

export const checkInAttempts = sqliteTable("check_in_attempts", {
  id: text("id").primaryKey(),
  studentId: text("student_id")
    .notNull()
    .references(() => users.id),
  classSessionId: text("class_session_id").references(() => classSessions.id),
  tokenHash: text("token_hash"),
  outcome: text("outcome", { enum: ["success", "rejected"] }).notNull(),
  reason: text("reason"),
  ...timestamps,
});

export const attendanceRecords = sqliteTable(
  "attendance_records",
  {
    id: text("id").primaryKey(),
    studentId: text("student_id")
      .notNull()
      .references(() => users.id),
    classSessionId: text("class_session_id")
      .notNull()
      .references(() => classSessions.id),
    status: text("status", {
      enum: ["present", "late", "absent", "excused", "manual_present"],
    }).notNull(),
    method: text("method", { enum: ["qr", "manual", "system"] }).notNull(),
    checkedInAt: integer("checked_in_at", { mode: "timestamp_ms" }).notNull(),
    ...timestamps,
  },
  (table) => [
    uniqueIndex("attendance_session_student_unique").on(
      table.classSessionId,
      table.studentId,
    ),
  ],
);

export const auditLogs = sqliteTable("audit_logs", {
  id: text("id").primaryKey(),
  actorId: text("actor_id")
    .notNull()
    .references(() => users.id),
  attendanceRecordId: text("attendance_record_id").references(
    () => attendanceRecords.id,
  ),
  action: text("action").notNull(),
  oldValue: text("old_value"),
  newValue: text("new_value").notNull(),
  reason: text("reason").notNull(),
  ...timestamps,
});
