import type { DbPool } from "./db.js";

/** Advisory lock key — integration tests hold exclusively; preview seed skips when busy. */
export const INTEGRATION_TEST_LOCK_KEY = 0x5745434b;

const DEADLOCK_CODE = "40P01";
const MAX_RESET_ATTEMPTS = 6;

function isDeadlock(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code: string }).code === DEADLOCK_CODE
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function withIntegrationTestDbResetOnce<T>(
  db: DbPool,
  fn: () => Promise<T>,
): Promise<T> {
  const client = await db.connect();
  try {
    await client.query("SET lock_timeout = '30s'");
    await client.query("SELECT pg_advisory_lock($1)", [INTEGRATION_TEST_LOCK_KEY]);
    try {
      return await fn();
    } finally {
      await client.query("SELECT pg_advisory_unlock($1)", [INTEGRATION_TEST_LOCK_KEY]);
    }
  } finally {
    client.release();
  }
}

/**
 * Run DB reset/truncate work while holding pg_advisory_lock on one pool connection.
 * Preview stack uses pg_try_advisory_lock on the same key and skips when tests run.
 */
export async function withIntegrationTestDbReset<T>(
  db: DbPool,
  fn: () => Promise<T>,
): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt < MAX_RESET_ATTEMPTS; attempt += 1) {
    try {
      return await withIntegrationTestDbResetOnce(db, fn);
    } catch (error) {
      lastError = error;
      if (!isDeadlock(error) || attempt === MAX_RESET_ATTEMPTS - 1) {
        throw error;
      }
      await delay(40 * (attempt + 1));
    }
  }
  throw lastError;
}

/** Non-blocking preview side-effects — skip when integration tests are resetting DB. */
export async function runWhenPreviewDbIdle(
  db: DbPool,
  fn: () => Promise<void>,
): Promise<void> {
  const client = await db.connect();
  try {
    const acquired = await client.query<{ pg_try_advisory_lock: boolean }>(
      "SELECT pg_try_advisory_lock($1)",
      [INTEGRATION_TEST_LOCK_KEY],
    );
    if (!acquired.rows[0]?.pg_try_advisory_lock) {
      return;
    }
    try {
      await fn();
    } finally {
      await client.query("SELECT pg_advisory_unlock($1)", [INTEGRATION_TEST_LOCK_KEY]);
    }
  } finally {
    client.release();
  }
}
