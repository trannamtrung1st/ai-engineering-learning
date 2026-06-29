import { randomUUID } from "node:crypto";
import type { PoolClient } from "pg";
import type { DbPool } from "../../infra/db.js";
import type { EnrollmentRecord } from "./types.js";

type DbQueryable = DbPool | PoolClient;

interface EnrollmentRow {
  id: string;
  student_id: string;
  institutional_id: string;
  display_name: string;
  enrolled_at: Date;
}

export class EnrollmentRepository {
  constructor(private readonly db: DbPool) {}

  async exists(
    studentId: string,
    classId: string,
    subjectId: string,
  ): Promise<boolean> {
    const result = await this.db.query<{ id: string }>(
      `SELECT id FROM enrollments
       WHERE student_id = $1 AND class_id = $2 AND subject_id = $3`,
      [studentId, classId, subjectId],
    );
    return (result.rowCount ?? 0) > 0;
  }

  async create(
    studentId: string,
    classId: string,
    subjectId: string,
    client?: DbQueryable,
  ): Promise<string> {
    const db = client ?? this.db;
    const id = randomUUID();
    await db.query(
      `INSERT INTO enrollments (id, student_id, class_id, subject_id)
       VALUES ($1, $2, $3, $4)`,
      [id, studentId, classId, subjectId],
    );
    return id;
  }

  async listByClassSubject(
    classId: string,
    subjectId: string,
  ): Promise<EnrollmentRecord[]> {
    const result = await this.db.query<EnrollmentRow>(
      `SELECT e.id, e.student_id, u.institutional_id, u.display_name, e.enrolled_at
       FROM enrollments e
       INNER JOIN users u ON u.id = e.student_id
       WHERE e.class_id = $1 AND e.subject_id = $2
       ORDER BY u.display_name`,
      [classId, subjectId],
    );
    return result.rows.map((row) => ({
      enrollmentId: row.id,
      studentId: row.student_id,
      institutionalId: row.institutional_id,
      displayName: row.display_name,
      enrolledAt: row.enrolled_at,
    }));
  }

  async countByClassSubject(classId: string, subjectId: string): Promise<number> {
    const result = await this.db.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM enrollments
       WHERE class_id = $1 AND subject_id = $2`,
      [classId, subjectId],
    );
    return Number.parseInt(result.rows[0]?.count ?? "0", 10);
  }
}
