import { randomUUID } from "node:crypto";
import type { DbPool } from "../../infra/db.js";

export class AssignmentRepository {
  constructor(private readonly db: DbPool) {}

  async hasAssignment(
    instructorId: string,
    classId: string,
    subjectId: string,
  ): Promise<boolean> {
    const result = await this.db.query<{ id: string }>(
      `SELECT id FROM class_assignments
       WHERE instructor_id = $1 AND class_id = $2 AND subject_id = $3`,
      [instructorId, classId, subjectId],
    );
    return (result.rowCount ?? 0) > 0;
  }

  async create(
    instructorId: string,
    classId: string,
    subjectId: string,
  ): Promise<string> {
    const id = randomUUID();
    await this.db.query(
      `INSERT INTO class_assignments (id, instructor_id, class_id, subject_id)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (instructor_id, class_id, subject_id) DO NOTHING`,
      [id, instructorId, classId, subjectId],
    );
    return id;
  }
}
