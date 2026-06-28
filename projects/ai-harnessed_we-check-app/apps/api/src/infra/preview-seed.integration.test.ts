import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";
import { ErrorCode, QrTokenStatus, SessionStatus } from "@wecheck/domain";
import { createPool, setPool, closePool, type DbPool } from "./db.js";
import { runMigrations } from "./migrate.js";
import {
  PREVIEW_CREDENTIALS,
  PREVIEW_IDS,
  runPreviewSeed,
} from "./preview-seed.js";
import { hashPassword } from "../modules/identity-auth/password-hasher.js";
import { truncateAuthTables } from "../auth/session-store.js";
import { truncateRosterTables } from "../modules/roster-enrollment/roster-service.js";
import { truncateSessionTables } from "../modules/session-management/session-service.js";
import { ApiError } from "../errors/api-error.js";

const DEFAULT_DATABASE_URL =
  process.env.DATABASE_URL ??
  "postgresql://wecheck:wecheck@localhost:5432/wecheck";

/** NFR-17 / NFR-06 — preview seed fixtures for browser gates */
describe("preview seed (NFR-17, NFR-06)", () => {
  let db: DbPool;

  before(async () => {
    db = createPool(DEFAULT_DATABASE_URL);
    setPool(db);
    await runMigrations(db);
  });

  after(async () => {
    await closePool();
  });

  async function resetDb(): Promise<void> {
    await truncateSessionTables(db);
    await truncateRosterTables(db);
    await truncateAuthTables(db);
    await db.query("DELETE FROM policy_settings WHERE key = 'preview_seed_version'");
  }

  it("seeds deactivated user and stale QR token for browser fixtures", async () => {
    await resetDb();
    await runPreviewSeed(db);

    const deactivatedLogin = await db.query<{ active: boolean }>(
      "SELECT active FROM users WHERE email = $1",
      [PREVIEW_CREDENTIALS.deactivated.email],
    );
    assert.equal(deactivatedLogin.rows[0]?.active, false);

    const staleToken = await db.query<{ status: string; session_id: string }>(
      "SELECT status, session_id FROM qr_tokens WHERE id = $1",
      [PREVIEW_IDS.staleQrToken],
    );
    assert.equal(staleToken.rows[0]?.status, QrTokenStatus.Expired);
    assert.equal(staleToken.rows[0]?.session_id, PREVIEW_IDS.sessionActive);

    const activeSession = await db.query<{ status: string }>(
      "SELECT status FROM sessions WHERE id = $1",
      [PREVIEW_IDS.sessionActive],
    );
    assert.equal(activeSession.rows[0]?.status, SessionStatus.Active);

    await runPreviewSeed(db);
    const userCount = await db.query<{ count: string }>(
      "SELECT COUNT(*)::text AS count FROM users",
    );
    assert.equal(userCount.rows[0]?.count, "4");
  });

  it("deactivated login returns AccountDeactivated (TC-NFR-17-013)", async () => {
    await resetDb();
    await runPreviewSeed(db);

    const passwordHash = await hashPassword(PREVIEW_CREDENTIALS.deactivated.password);
    await db.query(
      "UPDATE users SET password_hash = $1 WHERE email = $2",
      [passwordHash, PREVIEW_CREDENTIALS.deactivated.email],
    );

    const { AuthService } = await import("../modules/identity-auth/auth-service.js");
    const { UserRepository } = await import("../modules/identity-auth/user-repository.js");
    const { SessionStore } = await import("../auth/session-store.js");
    const auth = new AuthService(new UserRepository(db), new SessionStore(db));

    await assert.rejects(
      () =>
        auth.authenticate({
          email: PREVIEW_CREDENTIALS.deactivated.email,
          password: PREVIEW_CREDENTIALS.deactivated.password,
        }),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.errorCode, ErrorCode.AccountDeactivated);
        return true;
      },
    );
  });
});
