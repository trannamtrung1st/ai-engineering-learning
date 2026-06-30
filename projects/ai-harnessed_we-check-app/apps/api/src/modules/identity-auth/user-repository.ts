import { randomUUID } from "node:crypto";
import type { PoolClient } from "pg";
import type { UserRole } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import type { CreateUserInput, UserRecord } from "./types.js";

interface UserRow {
  id: string;
  institutional_id: string;
  display_name: string;
  email: string;
  password_hash: string;
  role: UserRole;
  active: boolean;
  created_at: Date;
  updated_at: Date;
}

function mapRow(row: UserRow): UserRecord {
  return {
    id: row.id,
    institutionalId: row.institutional_id,
    displayName: row.display_name,
    email: row.email,
    passwordHash: row.password_hash,
    role: row.role,
    active: row.active,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

export class UserRepository {
  constructor(private readonly db: DbPool) {}

  async count(): Promise<number> {
    const result = await this.db.query<{ count: string }>(
      "SELECT COUNT(*)::text AS count FROM users",
    );
    return Number.parseInt(result.rows[0]?.count ?? "0", 10);
  }

  async countOnClient(client: PoolClient): Promise<number> {
    const result = await client.query<{ count: string }>(
      "SELECT COUNT(*)::text AS count FROM users",
    );
    return Number.parseInt(result.rows[0]?.count ?? "0", 10);
  }

  async findByEmail(email: string): Promise<UserRecord | null> {
    const result = await this.db.query<UserRow>(
      `SELECT id, institutional_id, display_name, email, password_hash, role, active, created_at, updated_at
       FROM users WHERE email = $1`,
      [email],
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async findById(id: string): Promise<UserRecord | null> {
    const result = await this.db.query<UserRow>(
      `SELECT id, institutional_id, display_name, email, password_hash, role, active, created_at, updated_at
       FROM users WHERE id = $1`,
      [id],
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async findByInstitutionalId(institutionalId: string): Promise<UserRecord | null> {
    const result = await this.db.query<UserRow>(
      `SELECT id, institutional_id, display_name, email, password_hash, role, active, created_at, updated_at
       FROM users WHERE institutional_id = $1`,
      [institutionalId],
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async create(
    input: CreateUserInput & { passwordHash: string },
  ): Promise<UserRecord> {
    const id = randomUUID();
    const result = await this.db.query<UserRow>(
      `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       RETURNING id, institutional_id, display_name, email, password_hash, role, active, created_at, updated_at`,
      [
        id,
        input.institutionalId,
        input.displayName,
        input.email,
        input.passwordHash,
        input.role,
        input.active ?? true,
      ],
    );
    return mapRow(result.rows[0]!);
  }

  async createOnClient(
    client: PoolClient,
    input: {
      institutionalId: string;
      displayName: string;
      email: string;
      passwordHash: string;
      role: UserRole;
      active?: boolean;
    },
  ): Promise<UserRecord> {
    const id = randomUUID();
    const result = await client.query<UserRow>(
      `INSERT INTO users (id, institutional_id, display_name, email, password_hash, role, active)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       RETURNING id, institutional_id, display_name, email, password_hash, role, active, created_at, updated_at`,
      [
        id,
        input.institutionalId,
        input.displayName,
        input.email,
        input.passwordHash,
        input.role,
        input.active ?? true,
      ],
    );
    return mapRow(result.rows[0]!);
  }

  async writeAuditLogOnClient(
    client: PoolClient,
    input: {
      userId: string;
      actorId: string;
      action: string;
      reason?: string;
    },
  ): Promise<void> {
    await client.query(
      `INSERT INTO user_audit_logs (user_id, actor_id, action, reason)
       VALUES ($1, $2, $3, $4)`,
      [input.userId, input.actorId, input.action, input.reason ?? null],
    );
  }

  async update(
    userId: string,
    fields: {
      institutionalId?: string;
      displayName?: string;
      email?: string;
      passwordHash?: string;
      role?: UserRole;
      active?: boolean;
    },
  ): Promise<UserRecord | null> {
    const sets: string[] = ["updated_at = NOW()"];
    const values: unknown[] = [];
    let idx = 1;

    if (fields.institutionalId !== undefined) {
      sets.push(`institutional_id = $${idx++}`);
      values.push(fields.institutionalId);
    }
    if (fields.displayName !== undefined) {
      sets.push(`display_name = $${idx++}`);
      values.push(fields.displayName);
    }
    if (fields.email !== undefined) {
      sets.push(`email = $${idx++}`);
      values.push(fields.email);
    }
    if (fields.passwordHash !== undefined) {
      sets.push(`password_hash = $${idx++}`);
      values.push(fields.passwordHash);
    }
    if (fields.role !== undefined) {
      sets.push(`role = $${idx++}`);
      values.push(fields.role);
    }
    if (fields.active !== undefined) {
      sets.push(`active = $${idx++}`);
      values.push(fields.active);
    }

    values.push(userId);
    const result = await this.db.query<UserRow>(
      `UPDATE users SET ${sets.join(", ")}
       WHERE id = $${idx}
       RETURNING id, institutional_id, display_name, email, password_hash, role, active, created_at, updated_at`,
      values,
    );
    const row = result.rows[0];
    return row ? mapRow(row) : null;
  }

  async list(options: {
    role?: UserRole;
    active?: boolean;
    search?: string;
    limit: number;
    cursor?: string;
  }): Promise<{ items: UserRecord[]; nextCursor: string | null }> {
    const conditions: string[] = [];
    const values: unknown[] = [];
    let idx = 1;

    if (options.role) {
      conditions.push(`role = $${idx++}`);
      values.push(options.role);
    }
    if (options.active !== undefined) {
      conditions.push(`active = $${idx++}`);
      values.push(options.active);
    }
    if (options.search) {
      conditions.push(
        `(email ILIKE $${idx} OR institutional_id ILIKE $${idx})`,
      );
      values.push(`%${options.search}%`);
      idx++;
    }

    if (options.cursor) {
      try {
        const decoded = JSON.parse(
          Buffer.from(options.cursor, "base64url").toString("utf8"),
        ) as { createdAt: string; id: string };
        conditions.push(
          `(created_at, id) < ($${idx}::timestamptz, $${idx + 1}::uuid)`,
        );
        values.push(decoded.createdAt, decoded.id);
        idx += 2;
      } catch {
        conditions.push("FALSE");
      }
    }

    const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
    values.push(options.limit + 1);

    const result = await this.db.query<UserRow>(
      `SELECT id, institutional_id, display_name, email, password_hash, role, active, created_at, updated_at
       FROM users
       ${where}
       ORDER BY created_at DESC, id DESC
       LIMIT $${idx}`,
      values,
    );

    const rows = result.rows;
    const hasMore = rows.length > options.limit;
    const page = hasMore ? rows.slice(0, options.limit) : rows;
    const last = page[page.length - 1];
    const nextCursor =
      hasMore && last
        ? Buffer.from(
            JSON.stringify({
              createdAt: last.created_at.toISOString(),
              id: last.id,
            }),
          ).toString("base64url")
        : null;

    return { items: page.map(mapRow), nextCursor };
  }

  async writeAuditLog(input: {
    userId: string;
    actorId: string;
    action: string;
    reason?: string;
  }): Promise<void> {
    await this.db.query(
      `INSERT INTO user_audit_logs (user_id, actor_id, action, reason)
       VALUES ($1, $2, $3, $4)`,
      [input.userId, input.actorId, input.action, input.reason ?? null],
    );
  }
}

export function isUniqueViolation(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code: string }).code === "23505"
  );
}

export function uniqueFieldFromError(error: unknown): string | null {
  if (!isUniqueViolation(error)) {
    return null;
  }
  const detail = (error as { detail?: string }).detail ?? "";
  if (detail.includes("email")) return "email";
  if (detail.includes("institutional_id")) return "institutionalId";
  return "institutionalId";
}
