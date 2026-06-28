import Fastify from "fastify";
import cookie from "@fastify/cookie";
import type { DbPool } from "./infra/db.js";
import { registerErrorHandler } from "./errors/error-handler.js";
import { registerHealthRoutes, registerRequestIdHook } from "./routes/health.js";
import { registerFoundationRoutes } from "./routes/foundation.js";
import { registerIdentityAuthRoutes } from "./modules/identity-auth/routes.js";
import { registerRosterEnrollmentRoutes } from "./modules/roster-enrollment/routes.js";
import { registerSessionManagementRoutes } from "./modules/session-management/routes.js";
import { registerAttendanceRoutes } from "./modules/attendance/routes.js";
import type { AutoCloseScheduler } from "./modules/session-management/auto-close-scheduler.js";
import { SessionStore } from "./auth/session-store.js";
import { loadEnv } from "./config/env.js";

export const API_VERSION = "v1";
export const API_BASE_PATH = "/api/v1";

export interface BuildAppOptions {
  db: DbPool;
  logger?: boolean;
}

export async function buildApp(options: BuildAppOptions) {
  const env = loadEnv();
  const app = Fastify({
    logger: options.logger ?? env.nodeEnv !== "test",
  });

  registerRequestIdHook(app);
  registerErrorHandler(app);

  await app.register(cookie);

  const store = new SessionStore(options.db);
  let autoCloseScheduler: AutoCloseScheduler | undefined;

  await app.register(
    async (api) => {
      await registerHealthRoutes(api, options.db);
      await registerIdentityAuthRoutes(api, options.db, store);
      await registerRosterEnrollmentRoutes(api, options.db, store);
      autoCloseScheduler = await registerSessionManagementRoutes(
        api,
        options.db,
        store,
      );
      await registerAttendanceRoutes(api, options.db, store);
      await registerFoundationRoutes(api, store);
    },
    { prefix: API_BASE_PATH },
  );

  if (autoCloseScheduler && env.nodeEnv !== "test") {
    autoCloseScheduler.start();
  }

  app.addHook("onClose", async () => {
    autoCloseScheduler?.stop();
  });

  return app;
}

import { PASSWORD_POLICY } from "@wecheck/domain";

export function getApiMetadata() {
  return {
    version: API_VERSION,
    basePath: API_BASE_PATH,
    passwordMinLength: PASSWORD_POLICY.MIN_LENGTH,
  };
}
