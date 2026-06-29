import { shouldAutoCloseSession } from "@wecheck/domain";
import type { DbPool } from "../../infra/db.js";
import { runWhenPreviewDbIdle } from "../../infra/integration-test-lock.js";
import { now } from "../../infra/clock.js";
import type { SessionService } from "./session-service.js";

/** BR-01 — auto-close Active sessions at scheduledStart + 10 minutes. */
export class AutoCloseScheduler {
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly db: DbPool,
    private readonly sessions: SessionService,
  ) {}

  start(intervalMs = 15_000): void {
    if (this.timer) {
      return;
    }
    this.timer = setInterval(() => {
      void this.run();
    }, intervalMs);
    this.timer.unref();
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  async run(): Promise<number> {
    let closed = 0;
    await runWhenPreviewDbIdle(this.db, async () => {
      const current = now();
      const result = await this.db.query<{
        id: string;
        scheduled_start: Date;
      }>(
        `SELECT id, scheduled_start
         FROM sessions
         WHERE status = 'Active'`,
      );

      for (const row of result.rows) {
        if (shouldAutoCloseSession(row.scheduled_start, current)) {
          const didClose = await this.sessions.autoClose(row.id);
          if (didClose) {
            closed += 1;
          }
        }
      }
    });
    return closed;
  }
}
