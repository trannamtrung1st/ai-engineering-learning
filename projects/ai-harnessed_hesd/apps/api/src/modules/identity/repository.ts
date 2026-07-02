import type pg from "pg";
import type {
  ActorContext,
  MeResponse,
  Role,
  RoleAssignment,
  ScopeType,
} from "./types.js";

export interface AuthUserRow {
  id: string;
  email: string;
  display_name: string;
  password_hash: string | null;
}

export interface ScopeBindings {
  classSectionFacultyId?: string;
  classSectionIdsForFaculty?: string[];
  lecturerClassSectionIds?: string[];
  sessionClassSectionId?: string;
}

export function createIdentityRepository(pool: pg.Pool) {
  return {
    async findUserByEmail(email: string): Promise<AuthUserRow | null> {
      const result = await pool.query<AuthUserRow>(
        `
        SELECT u.id, u.email, u.display_name, c.password_hash
        FROM users u
        LEFT JOIN user_credentials c ON c.user_id = u.id
        WHERE lower(u.email) = lower($1) AND u.is_active = true
        `,
        [email],
      );
      return result.rows[0] ?? null;
    },

    async getRoleAssignments(userId: string): Promise<RoleAssignment[]> {
      const result = await pool.query<{
        role: Role;
        scope_type: ScopeType;
        scope_id: string | null;
      }>(
        `
        SELECT role, scope_type, scope_id
        FROM user_role_assignments
        WHERE user_id = $1
        `,
        [userId],
      );
      return result.rows.map((row) => ({
        role: row.role,
        scopeType: row.scope_type,
        scopeId: row.scope_id,
      }));
    },

    async buildActorContext(userId: string): Promise<ActorContext | null> {
      const userResult = await pool.query<{ id: string; email: string; display_name: string }>(
        `SELECT id, email, display_name FROM users WHERE id = $1 AND is_active = true`,
        [userId],
      );
      const user = userResult.rows[0];
      if (!user) return null;

      const assignments = await this.getRoleAssignments(userId);
      const roles = [...new Set(assignments.map((a) => a.role))];

      return {
        userId: user.id,
        email: user.email,
        displayName: user.display_name,
        roles,
        assignments,
      };
    },

    async resolveScopeBindings(target: {
      classSectionId?: string;
      classSessionId?: string;
      facultyId?: string;
    }): Promise<ScopeBindings> {
      const bindings: ScopeBindings = {};

      if (target.classSectionId) {
        const sectionResult = await pool.query<{ faculty_id: string }>(
          `
          SELECT c.faculty_id
          FROM class_sections cs
          JOIN courses c ON c.id = cs.course_id
          WHERE cs.id = $1
          `,
          [target.classSectionId],
        );
        bindings.classSectionFacultyId = sectionResult.rows[0]?.faculty_id;
      }

      if (target.classSessionId) {
        const sessionResult = await pool.query<{ class_section_id: string; faculty_id: string }>(
          `
          SELECT cs.id AS class_section_id, c.faculty_id
          FROM class_sessions sess
          JOIN class_sections cs ON cs.id = sess.class_section_id
          JOIN courses c ON c.id = cs.course_id
          WHERE sess.id = $1
          `,
          [target.classSessionId],
        );
        if (sessionResult.rows[0]) {
          bindings.sessionClassSectionId = sessionResult.rows[0].class_section_id;
          bindings.classSectionFacultyId = sessionResult.rows[0].faculty_id;
        }
      }

      if (target.facultyId) {
        const sectionsResult = await pool.query<{ id: string }>(
          `
          SELECT cs.id
          FROM class_sections cs
          JOIN courses c ON c.id = cs.course_id
          WHERE c.faculty_id = $1
          `,
          [target.facultyId],
        );
        bindings.classSectionIdsForFaculty = sectionsResult.rows.map((r) => r.id);
      }

      return bindings;
    },

    async getLecturerClassSectionIds(userId: string): Promise<string[]> {
      const result = await pool.query<{ scope_id: string }>(
        `
        SELECT scope_id
        FROM user_role_assignments
        WHERE user_id = $1 AND role = 'Lecturer' AND scope_type = 'ClassSection' AND scope_id IS NOT NULL
        `,
        [userId],
      );
      return result.rows.map((r) => r.scope_id);
    },

  };
}

export type IdentityRepository = ReturnType<typeof createIdentityRepository>;

export function toMeResponse(actor: ActorContext, extra?: {
  facultyIds: string[];
  classSectionIds: string[];
}): MeResponse {
  return {
    userId: actor.userId,
    email: actor.email,
    displayName: actor.displayName,
    roles: actor.roles,
    scopes: actor.assignments.map((a) => ({
      scopeType: a.scopeType,
      scopeId: a.scopeId,
      role: a.role,
    })),
    facultyIds: extra?.facultyIds ?? [],
    classSectionIds: extra?.classSectionIds ?? [],
  };
}
