import pg from "pg";

export type DbPool = pg.Pool;

let pool: DbPool | null = null;

export function createPool(connectionString: string): DbPool {
  return new pg.Pool({ connectionString, max: 20 });
}

export function setPool(next: DbPool): void {
  pool = next;
}

export function getPool(): DbPool {
  if (!pool) {
    throw new Error("Database pool not initialized");
  }
  return pool;
}

export async function checkDbConnection(db: DbPool): Promise<boolean> {
  try {
    await db.query("SELECT 1");
    return true;
  } catch {
    return false;
  }
}

export async function closePool(): Promise<void> {
  if (pool) {
    await pool.end();
    pool = null;
  }
}
