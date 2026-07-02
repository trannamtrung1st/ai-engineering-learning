import { randomUUID } from "node:crypto";
import type pg from "pg";
import type {
  ClassSectionRow,
  CourseRow,
  EnrollmentImportResult,
  ImportRejectedRow,
  RoomRow,
  ScheduleTemplate,
  TermRow,
} from "./types.js";
import {
  datesForDayOfWeek,
  isStudentEnrolled,
  sessionTimesForDate,
} from "./validation.js";

function mapTerm(row: {
  id: string;
  code: string;
  name: string;
  start_date: string | Date;
  end_date: string | Date;
  is_active: boolean;
}): TermRow {
  return {
    id: row.id,
    code: row.code,
    name: row.name,
    startDate:
      row.start_date instanceof Date
        ? row.start_date.toISOString().slice(0, 10)
        : String(row.start_date).slice(0, 10),
    endDate:
      row.end_date instanceof Date
        ? row.end_date.toISOString().slice(0, 10)
        : String(row.end_date).slice(0, 10),
    isActive: row.is_active,
  };
}

function mapCourse(row: {
  id: string;
  code: string;
  name: string;
  faculty_id: string;
  credit_units: number | null;
  is_active: boolean;
}): CourseRow {
  return {
    id: row.id,
    code: row.code,
    name: row.name,
    facultyId: row.faculty_id,
    creditUnits: row.credit_units,
    isActive: row.is_active,
  };
}

function mapRoom(row: {
  id: string;
  code: string;
  building: string | null;
  name: string;
  latitude: string | null;
  longitude: string | null;
  is_active: boolean;
}): RoomRow {
  return {
    id: row.id,
    code: row.code,
    building: row.building,
    name: row.name,
    latitude: row.latitude === null ? null : Number(row.latitude),
    longitude: row.longitude === null ? null : Number(row.longitude),
    isActive: row.is_active,
  };
}

function mapSection(row: {
  id: string;
  section_code: string;
  term_id: string;
  course_id: string;
  lecturer_user_id: string;
  default_room_id: string | null;
  capacity: number | null;
  is_active: boolean;
}): ClassSectionRow {
  return {
    id: row.id,
    sectionCode: row.section_code,
    termId: row.term_id,
    courseId: row.course_id,
    lecturerUserId: row.lecturer_user_id,
    defaultRoomId: row.default_room_id,
    capacity: row.capacity,
    isActive: row.is_active,
  };
}

export function createAcademicRepository(pool: pg.Pool) {
  const query = pool.query.bind(pool);

  return {
    isStudentEnrolled(studentUserId: string, classSectionId: string) {
      return isStudentEnrolled(query, studentUserId, classSectionId);
    },

    async createTerm(input: {
      code: string;
      name: string;
      startDate: string;
      endDate: string;
      isActive: boolean;
    }): Promise<TermRow> {
      const id = randomUUID();
      const result = await query(
        `
        INSERT INTO terms (id, code, name, start_date, end_date, is_active)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, code, name, start_date, end_date, is_active
        `,
        [id, input.code, input.name, input.startDate, input.endDate, input.isActive],
      );
      return mapTerm(result.rows[0]);
    },

    async listTerms(
      offset: number,
      limit: number,
      activeOnly?: boolean,
    ): Promise<{ items: TermRow[]; total: number }> {
      const where = activeOnly ? "WHERE is_active = true" : "";
      const countResult = await query<{ count: string }>(
        `SELECT COUNT(*)::text AS count FROM terms ${where}`,
      );
      const result = await query(
        `
        SELECT id, code, name, start_date, end_date, is_active
        FROM terms
        ${where}
        ORDER BY start_date DESC, code ASC
        OFFSET $1 LIMIT $2
        `,
        [offset, limit],
      );
      return {
        items: result.rows.map(mapTerm),
        total: Number.parseInt(countResult.rows[0]?.count ?? "0", 10),
      };
    },

    async getTermById(termId: string): Promise<TermRow | null> {
      const result = await query(
        `SELECT id, code, name, start_date, end_date, is_active FROM terms WHERE id = $1`,
        [termId],
      );
      return result.rows[0] ? mapTerm(result.rows[0]) : null;
    },

    async updateTerm(
      termId: string,
      patch: Partial<{ name: string; startDate: string; endDate: string; isActive: boolean }>,
    ): Promise<TermRow | null> {
      const current = await this.getTermById(termId);
      if (!current) return null;

      const result = await query(
        `
        UPDATE terms
        SET
          name = COALESCE($2, name),
          start_date = COALESCE($3, start_date),
          end_date = COALESCE($4, end_date),
          is_active = COALESCE($5, is_active)
        WHERE id = $1
        RETURNING id, code, name, start_date, end_date, is_active
        `,
        [
          termId,
          patch.name ?? null,
          patch.startDate ?? null,
          patch.endDate ?? null,
          patch.isActive ?? null,
        ],
      );
      return result.rows[0] ? mapTerm(result.rows[0]) : null;
    },

    async termCodeExists(code: string, excludeId?: string): Promise<boolean> {
      const result = await query(
        `SELECT 1 FROM terms WHERE code = $1 AND ($2::uuid IS NULL OR id <> $2) LIMIT 1`,
        [code, excludeId ?? null],
      );
      return (result.rowCount ?? 0) > 0;
    },

    async createCourse(input: {
      code: string;
      name: string;
      facultyId: string;
      creditUnits?: number;
    }): Promise<CourseRow> {
      const id = randomUUID();
      const result = await query(
        `
        INSERT INTO courses (id, code, name, faculty_id, credit_units, is_active)
        VALUES ($1, $2, $3, $4, $5, true)
        RETURNING id, code, name, faculty_id, credit_units, is_active
        `,
        [id, input.code, input.name, input.facultyId, input.creditUnits ?? null],
      );
      return mapCourse(result.rows[0]);
    },

    async listCourses(offset: number, limit: number): Promise<{ items: CourseRow[]; total: number }> {
      const countResult = await query<{ count: string }>(`SELECT COUNT(*)::text AS count FROM courses`);
      const result = await query(
        `
        SELECT id, code, name, faculty_id, credit_units, is_active
        FROM courses
        ORDER BY code ASC
        OFFSET $1 LIMIT $2
        `,
        [offset, limit],
      );
      return {
        items: result.rows.map(mapCourse),
        total: Number.parseInt(countResult.rows[0]?.count ?? "0", 10),
      };
    },

    async getCourseById(courseId: string): Promise<CourseRow | null> {
      const result = await query(
        `SELECT id, code, name, faculty_id, credit_units, is_active FROM courses WHERE id = $1`,
        [courseId],
      );
      return result.rows[0] ? mapCourse(result.rows[0]) : null;
    },

    async facultyExists(facultyId: string): Promise<boolean> {
      const result = await query(`SELECT 1 FROM faculties WHERE id = $1 LIMIT 1`, [facultyId]);
      return (result.rowCount ?? 0) > 0;
    },

    async createRoom(input: {
      code: string;
      name: string;
      building?: string;
      latitude?: number;
      longitude?: number;
    }): Promise<RoomRow> {
      const id = randomUUID();
      const result = await query(
        `
        INSERT INTO rooms (id, code, building, name, latitude, longitude, is_active)
        VALUES ($1, $2, $3, $4, $5, $6, true)
        RETURNING id, code, building, name, latitude, longitude, is_active
        `,
        [
          id,
          input.code,
          input.building ?? null,
          input.name,
          input.latitude ?? null,
          input.longitude ?? null,
        ],
      );
      return mapRoom(result.rows[0]);
    },

    async listRooms(offset: number, limit: number): Promise<{ items: RoomRow[]; total: number }> {
      const countResult = await query<{ count: string }>(`SELECT COUNT(*)::text AS count FROM rooms`);
      const result = await query(
        `
        SELECT id, code, building, name, latitude, longitude, is_active
        FROM rooms
        ORDER BY code ASC
        OFFSET $1 LIMIT $2
        `,
        [offset, limit],
      );
      return {
        items: result.rows.map(mapRoom),
        total: Number.parseInt(countResult.rows[0]?.count ?? "0", 10),
      };
    },

    async getRoomById(roomId: string): Promise<RoomRow | null> {
      const result = await query(
        `SELECT id, code, building, name, latitude, longitude, is_active FROM rooms WHERE id = $1`,
        [roomId],
      );
      return result.rows[0] ? mapRoom(result.rows[0]) : null;
    },

    async userExists(userId: string): Promise<boolean> {
      const result = await query(`SELECT 1 FROM users WHERE id = $1 AND is_active = true LIMIT 1`, [
        userId,
      ]);
      return (result.rowCount ?? 0) > 0;
    },

    async classSectionExists(classSectionId: string): Promise<boolean> {
      const result = await query(`SELECT 1 FROM class_sections WHERE id = $1 LIMIT 1`, [
        classSectionId,
      ]);
      return (result.rowCount ?? 0) > 0;
    },

    async createClassSection(
      input: {
        sectionCode: string;
        termId: string;
        courseId: string;
        lecturerUserId: string;
        defaultRoomId?: string;
        capacity?: number;
        scheduleTemplate?: ScheduleTemplate;
      },
      client?: pg.PoolClient,
    ): Promise<{ section: ClassSectionRow; generatedSessionCount: number }> {
      const run = client ? client.query.bind(client) : query;
      const id = randomUUID();

      const sectionResult = await run(
        `
        INSERT INTO class_sections (
          id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, true)
        RETURNING id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
        `,
        [
          id,
          input.sectionCode,
          input.termId,
          input.courseId,
          input.lecturerUserId,
          input.defaultRoomId ?? null,
          input.capacity ?? null,
        ],
      );

      let generatedSessionCount = 0;
      if (input.scheduleTemplate) {
        const termResult = await run<{ start_date: string | Date; end_date: string | Date }>(
          `SELECT start_date, end_date FROM terms WHERE id = $1`,
          [input.termId],
        );
        const term = termResult.rows[0];
        if (term) {
          const startDate =
            term.start_date instanceof Date
              ? term.start_date.toISOString().slice(0, 10)
              : String(term.start_date).slice(0, 10);
          const endDate =
            term.end_date instanceof Date
              ? term.end_date.toISOString().slice(0, 10)
              : String(term.end_date).slice(0, 10);

          const dates = datesForDayOfWeek(
            startDate,
            endDate,
            input.scheduleTemplate.dayOfWeek,
          );

          for (const date of dates) {
            const { scheduledStartAt, scheduledEndAt } = sessionTimesForDate(
              date,
              input.scheduleTemplate.startTime,
              input.scheduleTemplate.durationMinutes,
            );
            await run(
              `
              INSERT INTO class_sessions (
                id, class_section_id, room_id, scheduled_start_at, scheduled_end_at, state
              )
              VALUES ($1, $2, $3, $4, $5, 'Scheduled')
              `,
              [
                randomUUID(),
                id,
                input.defaultRoomId ?? null,
                scheduledStartAt.toISOString(),
                scheduledEndAt.toISOString(),
              ],
            );
            generatedSessionCount += 1;
          }
        }
      }

      return {
        section: mapSection(sectionResult.rows[0]),
        generatedSessionCount,
      };
    },

    async listClassSections(
      filters: { termId?: string; lecturerUserId?: string },
      offset: number,
      limit: number,
    ): Promise<{ items: ClassSectionRow[]; total: number }> {
      const clauses: string[] = [];
      const params: unknown[] = [];
      let paramIndex = 1;

      if (filters.termId) {
        clauses.push(`term_id = $${paramIndex++}`);
        params.push(filters.termId);
      }
      if (filters.lecturerUserId) {
        clauses.push(`lecturer_user_id = $${paramIndex++}`);
        params.push(filters.lecturerUserId);
      }

      const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
      const countResult = await query<{ count: string }>(
        `SELECT COUNT(*)::text AS count FROM class_sections ${where}`,
        params,
      );
      params.push(offset, limit);
      const result = await query(
        `
        SELECT id, section_code, term_id, course_id, lecturer_user_id, default_room_id, capacity, is_active
        FROM class_sections
        ${where}
        ORDER BY section_code ASC
        OFFSET $${paramIndex++} LIMIT $${paramIndex}
        `,
        params,
      );

      return {
        items: result.rows.map(mapSection),
        total: Number.parseInt(countResult.rows[0]?.count ?? "0", 10),
      };
    },

    async importEnrollments(
      classSectionId: string,
      rows: { studentCode?: string }[],
      actorUserId: string,
    ): Promise<EnrollmentImportResult> {
      const client = await pool.connect();
      const rejectedRows: ImportRejectedRow[] = [];
      let acceptedRows = 0;
      const seenCodes = new Set<string>();

      try {
        await client.query("BEGIN");

        const sectionCheck = await client.query(
          `SELECT 1 FROM class_sections WHERE id = $1`,
          [classSectionId],
        );
        if ((sectionCheck.rowCount ?? 0) === 0) {
          await client.query("ROLLBACK");
          throw new Error("SECTION_NOT_FOUND");
        }

        for (let index = 0; index < rows.length; index += 1) {
          const rowNumber = index + 1;
          const studentCode = rows[index]?.studentCode?.trim();

          if (!studentCode) {
            rejectedRows.push({
              rowNumber,
              code: "InvalidPayload",
              message: "Thieu ma sinh vien.",
            });
            continue;
          }

          if (seenCodes.has(studentCode.toLowerCase())) {
            rejectedRows.push({
              rowNumber,
              code: "DuplicateRow",
              message: "Ma sinh vien trung lap trong file.",
            });
            continue;
          }
          seenCodes.add(studentCode.toLowerCase());

          const studentResult = await client.query<{ user_id: string }>(
            `
            SELECT sp.user_id
            FROM student_profiles sp
            JOIN users u ON u.id = sp.user_id
            WHERE sp.student_code = $1 AND u.is_active = true
            `,
            [studentCode],
          );

          if ((studentResult.rowCount ?? 0) === 0) {
            rejectedRows.push({
              rowNumber,
              code: "StudentNotFound",
              message: "Khong tim thay ma sinh vien.",
            });
            continue;
          }

          const studentUserId = studentResult.rows[0]!.user_id;

          const existing = await client.query<{ status: string }>(
            `
            SELECT status FROM enrollments
            WHERE class_section_id = $1 AND student_user_id = $2
            `,
            [classSectionId, studentUserId],
          );

          if ((existing.rowCount ?? 0) > 0) {
            if (existing.rows[0]!.status === "Active") {
              rejectedRows.push({
                rowNumber,
                code: "DuplicateEnrollment",
                message: "Sinh vien da duoc ghi danh.",
              });
              continue;
            }
            await client.query(
              `
              UPDATE enrollments
              SET status = 'Active', dropped_at = NULL, updated_at = now()
              WHERE class_section_id = $1 AND student_user_id = $2
              `,
              [classSectionId, studentUserId],
            );
          } else {
            await client.query(
              `
              INSERT INTO enrollments (id, class_section_id, student_user_id, status)
              VALUES ($1, $2, $3, 'Active')
              `,
              [randomUUID(), classSectionId, studentUserId],
            );
          }

          acceptedRows += 1;
        }

        await client.query(
          `
          INSERT INTO audit_logs (id, actor_user_id, action_type, target_type, target_id, new_value, reason)
          VALUES ($1, $2, 'EnrollmentImport', 'ClassSection', $3, $4::jsonb, $5)
          `,
          [
            randomUUID(),
            actorUserId,
            classSectionId,
            JSON.stringify({ acceptedRows, rejectedCount: rejectedRows.length }),
            "CSV enrollment import",
          ],
        );

        await client.query("COMMIT");
      } catch (error) {
        await client.query("ROLLBACK");
        throw error;
      } finally {
        client.release();
      }

      return { classSectionId, acceptedRows, rejectedRows };
    },

    async removeEnrollment(studentUserId: string, classSectionId: string): Promise<void> {
      await query(
        `
        UPDATE enrollments
        SET status = 'Dropped', dropped_at = now(), updated_at = now()
        WHERE class_section_id = $1 AND student_user_id = $2 AND status = 'Active'
        `,
        [classSectionId, studentUserId],
      );
    },

    async addEnrollment(studentUserId: string, classSectionId: string): Promise<void> {
      const existing = await query<{ status: string }>(
        `SELECT status FROM enrollments WHERE class_section_id = $1 AND student_user_id = $2`,
        [classSectionId, studentUserId],
      );

      if ((existing.rowCount ?? 0) > 0) {
        await query(
          `
          UPDATE enrollments
          SET status = 'Active', dropped_at = NULL, updated_at = now()
          WHERE class_section_id = $1 AND student_user_id = $2
          `,
          [classSectionId, studentUserId],
        );
      } else {
        await query(
          `
          INSERT INTO enrollments (id, class_section_id, student_user_id, status)
          VALUES ($1, $2, $3, 'Active')
          `,
          [randomUUID(), classSectionId, studentUserId],
        );
      }
    },
  };
}

export type AcademicRepository = ReturnType<typeof createAcademicRepository>;

export { isStudentEnrolled };
