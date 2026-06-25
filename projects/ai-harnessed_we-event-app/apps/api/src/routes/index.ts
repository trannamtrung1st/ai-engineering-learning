import type { FastifyInstance } from "fastify";
import type { AppConfig } from "../config.js";
import { requireAuth } from "../auth/middleware.js";
import { adminRoutes } from "./admin.js";
import { devAuthRoutes } from "./dev-auth.js";
import { healthRoutes } from "./health.js";
import { scopeRoutes } from "./scope.js";
import { sessionRoutes } from "./session.js";

export async function registerRoutes(
  app: FastifyInstance,
  basePath: string,
  config: AppConfig,
): Promise<void> {
  await app.register(healthRoutes, { prefix: basePath });
  await app.register(devAuthRoutes(config), { prefix: basePath });

  await app.register(
    async (protectedApp) => {
      protectedApp.addHook("onRequest", requireAuth);
      await protectedApp.register(sessionRoutes);
      await protectedApp.register(scopeRoutes);
      await protectedApp.register(adminRoutes);
    },
    { prefix: basePath },
  );
}
