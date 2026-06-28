import type { DbPool } from "../../infra/db.js";
import type { ClassRecord, SubjectRecord } from "./types.js";

interface ClassRow {
  id: string;
  code: string;
  name: string;
  term: string | null;
}

interface SubjectRow {
  id: string;
  code: string;
  name: string;
}

export class ReferenceRepository {
  constructor(private readonly db: DbPool) {}

  async findClassByCode(code: string): Promise<ClassRecord | null> {
    const result = await this.db.query<ClassRow>(
      "SELECT id, code, name, term FROM classes WHERE code = $1",
      [code],
    );
    const row = result.rows[0];
    return row ? { id: row.id, code: row.code, name: row.name, term: row.term } : null;
  }

  async findSubjectByCode(code: string): Promise<SubjectRecord | null> {
    const result = await this.db.query<SubjectRow>(
      "SELECT id, code, name FROM subjects WHERE code = $1",
      [code],
    );
    const row = result.rows[0];
    return row ? { id: row.id, code: row.code, name: row.name } : null;
  }

  async findClassById(id: string): Promise<ClassRecord | null> {
    const result = await this.db.query<ClassRow>(
      "SELECT id, code, name, term FROM classes WHERE id = $1",
      [id],
    );
    const row = result.rows[0];
    return row ? { id: row.id, code: row.code, name: row.name, term: row.term } : null;
  }

  async findSubjectById(id: string): Promise<SubjectRecord | null> {
    const result = await this.db.query<SubjectRow>(
      "SELECT id, code, name FROM subjects WHERE id = $1",
      [id],
    );
    const row = result.rows[0];
    return row ? { id: row.id, code: row.code, name: row.name } : null;
  }

  async listClassesForInstructor(instructorId: string): Promise<ClassRecord[]> {
    const result = await this.db.query<ClassRow>(
      `SELECT DISTINCT c.id, c.code, c.name, c.term
       FROM classes c
       INNER JOIN class_assignments ca ON ca.class_id = c.id
       WHERE ca.instructor_id = $1
       ORDER BY c.code`,
      [instructorId],
    );
    return result.rows.map((row) => ({
      id: row.id,
      code: row.code,
      name: row.name,
      term: row.term,
    }));
  }

  async listAllClasses(): Promise<ClassRecord[]> {
    const result = await this.db.query<ClassRow>(
      "SELECT id, code, name, term FROM classes ORDER BY code",
    );
    return result.rows.map((row) => ({
      id: row.id,
      code: row.code,
      name: row.name,
      term: row.term,
    }));
  }

  async listSubjectsForInstructor(instructorId: string): Promise<SubjectRecord[]> {
    const result = await this.db.query<SubjectRow>(
      `SELECT DISTINCT s.id, s.code, s.name
       FROM subjects s
       INNER JOIN class_assignments ca ON ca.subject_id = s.id
       WHERE ca.instructor_id = $1
       ORDER BY s.code`,
      [instructorId],
    );
    return result.rows.map((row) => ({ id: row.id, code: row.code, name: row.name }));
  }

  async listAllSubjects(): Promise<SubjectRecord[]> {
    const result = await this.db.query<SubjectRow>(
      "SELECT id, code, name FROM subjects ORDER BY code",
    );
    return result.rows.map((row) => ({ id: row.id, code: row.code, name: row.name }));
  }
}
