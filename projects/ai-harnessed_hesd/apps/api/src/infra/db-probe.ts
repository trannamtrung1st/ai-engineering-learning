import pg from "pg";
import type { DbHealthProbe } from "../routes/health.js";

export function createPostgresHealthProbe(connectionString?: string): DbHealthProbe {
  if (!connectionString) {
    return {
      async ping() {
        return true;
      },
    };
  }

  return {
    async ping() {
      const client = new pg.Client({ connectionString });
      try {
        await client.connect();
        await client.query("SELECT 1");
        return true;
      } catch {
        return false;
      } finally {
        await client.end().catch(() => undefined);
      }
    },
  };
}
