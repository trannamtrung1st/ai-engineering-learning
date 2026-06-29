import { PASSWORD_POLICY } from "@wecheck/domain";
import { loadEnv } from "./config/env.js";
import { createPool, setPool, closePool } from "./infra/db.js";
import { runMigrations } from "./infra/migrate.js";
import {
  ensurePreviewTokenFixtures,
  runPreviewSeed,
  startPreviewTokenRefresh,
} from "./infra/preview-seed.js";
import { buildApp, getApiMetadata, API_BASE_PATH, API_VERSION } from "./server.js";

export { getApiMetadata, API_BASE_PATH, API_VERSION };

export async function startServer(): Promise<void> {
  const env = loadEnv();
  const pool = createPool(env.databaseUrl);
  setPool(pool);
  let stopPreviewTokenRefresh: (() => void) | undefined;

  try {
    await runMigrations(pool);
    if (env.seedEnabled) {
      await runPreviewSeed(pool);
      stopPreviewTokenRefresh = startPreviewTokenRefresh(pool);
    }
    const app = await buildApp({ db: pool, logger: env.logLevel !== "silent" });
    if (env.seedEnabled) {
      await ensurePreviewTokenFixtures(pool);
    }
    await app.listen({ port: env.port, host: "0.0.0.0" });
    app.log.info(
      {
        port: env.port,
        basePath: API_BASE_PATH,
        passwordMinLength: PASSWORD_POLICY.MIN_LENGTH,
        seedEnabled: env.seedEnabled,
      },
      "We Check API started",
    );
  } catch (error) {
    stopPreviewTokenRefresh?.();
    await closePool();
    throw error;
  }
}

const isMain =
  process.argv[1]?.endsWith("/index.js") ||
  process.argv[1]?.endsWith("/index.ts");

if (isMain) {
  startServer().catch((error) => {
    console.error("Failed to start API server:", error);
    process.exit(1);
  });
}
