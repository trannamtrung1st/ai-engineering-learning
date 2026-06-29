import {
  SESSION_INACTIVITY_DEFAULT_HOURS,
  SESSION_INACTIVITY_MAX_HOURS,
  SESSION_INACTIVITY_MIN_HOURS,
} from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { now } from "../../infra/clock.js";
import { POLICY_KEY_SESSION_INACTIVITY } from "../../auth/session-policy.js";

export class PolicyService {
  constructor(private readonly db: DbPool) {}

  async getSessionInactivityHours(): Promise<number> {
    const result = await this.db.query<{ value: string }>(
      "SELECT value FROM policy_settings WHERE key = $1",
      [POLICY_KEY_SESSION_INACTIVITY],
    );
    const raw = result.rows[0]?.value;
    if (!raw) {
      return SESSION_INACTIVITY_DEFAULT_HOURS;
    }
    const parsed = Number.parseInt(raw, 10);
    if (
      Number.isNaN(parsed) ||
      parsed < SESSION_INACTIVITY_MIN_HOURS ||
      parsed > SESSION_INACTIVITY_MAX_HOURS
    ) {
      return SESSION_INACTIVITY_DEFAULT_HOURS;
    }
    return parsed;
  }

  async setSessionInactivityHours(
    hours: number,
    adminId: string,
  ): Promise<number> {
    await this.db.query(
      `INSERT INTO policy_settings (key, value, updated_by_id, updated_at)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (key) DO UPDATE
       SET value = EXCLUDED.value, updated_by_id = EXCLUDED.updated_by_id, updated_at = EXCLUDED.updated_at`,
      [POLICY_KEY_SESSION_INACTIVITY, String(hours), adminId, now()],
    );
    return hours;
  }
}
