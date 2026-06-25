import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ActorRole } from "@we-event/domain";
import type { PoolClient } from "pg";
import { getPool } from "../../db/pool.js";
import { ApiError } from "../../errors/api-error.js";
import { ensureEventSchema } from "../event/repository.js";
import type {
  CreateUserInput,
  UserProfile,
  UserRoleAssignment,
  UserRoleRow,
  UserRow,
} from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

let schemaReady: Promise<void> | null = null;

export async function ensureUserSchema(): Promise<void> {
  if (!schemaReady) {
    schemaReady = (async () => {
      await ensureEventSchema();
      const sql = await readFile(join(__dirname, "schema.sql"), "utf8");
      await getPool().query(sql);
    })();
  }
  await schemaReady;
}

function mapUser(row: Record<string, unknown>): UserRow {
  return {
    id: row.id as string,
    email: row.email as string,
    displayName: row.display_name as string,
    createdAt: (row.created_at as Date).toISOString(),
    updatedAt: (row.updated_at as Date).toISOString(),
  };
}

function mapUserRole(row: Record<string, unknown>): UserRoleRow {
  return {
    id: row.id as string,
    userId: row.user_id as string,
    role: row.role as ActorRole,
    organizationId: (row.organization_id as string | null) ?? null,
    assignedEventIds: (row.assigned_event_ids as string[] | null) ?? [],
  };
}

export function toUserProfile(user: UserRow, roles: UserRoleRow[]): UserProfile {
  return {
    userId: user.id,
    email: user.email,
    displayName: user.displayName,
    roles: roles.map(
      (role): UserRoleAssignment => ({
        role: role.role,
        organizationId: role.organizationId,
        assignedEventIds: role.assignedEventIds,
      }),
    ),
  };
}

export async function findUserByEmail(email: string): Promise<UserRow | null> {
  await ensureUserSchema();
  const result = await getPool().query(
    `SELECT id, email, display_name, created_at, updated_at
     FROM users
     WHERE lower(email) = lower($1)`,
    [email.trim()],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapUser(result.rows[0]!);
}

export async function findUserById(id: string): Promise<UserRow | null> {
  await ensureUserSchema();
  const result = await getPool().query(
    `SELECT id, email, display_name, created_at, updated_at
     FROM users
     WHERE id = $1`,
    [id],
  );
  if (result.rowCount === 0) {
    return null;
  }
  return mapUser(result.rows[0]!);
}

export async function findUserPasswordHashByEmail(
  email: string,
): Promise<{ user: UserRow; passwordHash: string } | null> {
  await ensureUserSchema();
  const result = await getPool().query(
    `SELECT id, email, display_name, password_hash, created_at, updated_at
     FROM users
     WHERE lower(email) = lower($1)`,
    [email.trim()],
  );
  if (result.rowCount === 0) {
    return null;
  }
  const row = result.rows[0]!;
  return {
    user: mapUser(row),
    passwordHash: row.password_hash as string,
  };
}

export async function listUserRoles(userId: string): Promise<UserRoleRow[]> {
  await ensureUserSchema();
  const result = await getPool().query(
    `SELECT id, user_id, role, organization_id, assigned_event_ids
     FROM user_roles
     WHERE user_id = $1
     ORDER BY role ASC`,
    [userId],
  );
  return result.rows.map((row) => mapUserRole(row));
}

export async function createUser(
  input: CreateUserInput,
  client?: PoolClient,
): Promise<UserRow> {
  await ensureUserSchema();
  const db = client ?? getPool();
  const normalizedEmail = input.email.trim().toLowerCase();

  try {
    const result = await db.query(
      `INSERT INTO users (email, password_hash, display_name)
       VALUES ($1, $2, $3)
       RETURNING id, email, display_name, created_at, updated_at`,
      [normalizedEmail, input.passwordHash, input.displayName.trim()],
    );
    return mapUser(result.rows[0]!);
  } catch (error: unknown) {
    if (
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === "23505"
    ) {
      throw new ApiError({
        code: "EMAIL_ALREADY_REGISTERED",
        message: "An account with this email already exists.",
        statusCode: 409,
      });
    }
    throw error;
  }
}

export async function assignUserRole(
  userId: string,
  role: ActorRole,
  options: {
    organizationId?: string | null;
    assignedEventIds?: string[];
  } = {},
  client?: PoolClient,
): Promise<UserRoleRow> {
  await ensureUserSchema();
  const db = client ?? getPool();
  const result = await db.query(
    `INSERT INTO user_roles (user_id, role, organization_id, assigned_event_ids)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (user_id, role, organization_id)
     DO UPDATE SET assigned_event_ids = EXCLUDED.assigned_event_ids
     RETURNING id, user_id, role, organization_id, assigned_event_ids`,
    [
      userId,
      role,
      options.organizationId ?? null,
      options.assignedEventIds ?? [],
    ],
  );
  return mapUserRole(result.rows[0]!);
}

export async function createUserWithRole(
  input: CreateUserInput,
  role: ActorRole,
  options: {
    organizationId?: string | null;
    assignedEventIds?: string[];
  } = {},
): Promise<{ user: UserRow; roles: UserRoleRow[] }> {
  const pool = getPool();
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const user = await createUser(input, client);
    const roleRow = await assignUserRole(user.id, role, options, client);
    await client.query("COMMIT");
    return { user, roles: [roleRow] };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

/**
 * Ensures a participant user exists for integration tests and dev-token flows.
 */
export async function ensureParticipantUser(
  userId: string,
  displayName = "Test Participant",
  passwordHash: string,
): Promise<UserRow> {
  await ensureUserSchema();
  const email = `participant+${userId}@we-event.test`;
  const existing = await findUserById(userId);
  if (existing) {
    return existing;
  }

  const result = await getPool().query(
    `INSERT INTO users (id, email, password_hash, display_name)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (id) DO UPDATE
       SET display_name = EXCLUDED.display_name,
           updated_at = NOW()
     RETURNING id, email, display_name, created_at, updated_at`,
    [userId, email, passwordHash, displayName],
  );
  const user = mapUser(result.rows[0]!);
  await assignUserRole(user.id, "Participant");
  return user;
}

export async function provisionTestUser(
  userId: string,
  role: ActorRole,
  displayName = "Test User",
  passwordHash: string,
  options: {
    organizationId?: string | null;
    assignedEventIds?: string[];
  } = {},
): Promise<UserRow> {
  await ensureUserSchema();
  const email = `${role.toLowerCase()}+${userId}@we-event.test`;
  const result = await getPool().query(
    `INSERT INTO users (id, email, password_hash, display_name)
     VALUES ($1, $2, $3, $4)
     ON CONFLICT (id) DO UPDATE
       SET display_name = EXCLUDED.display_name,
           updated_at = NOW()
     RETURNING id, email, display_name, created_at, updated_at`,
    [userId, email, passwordHash, displayName],
  );
  const user = mapUser(result.rows[0]!);
  await assignUserRole(user.id, role, options);
  return user;
}
