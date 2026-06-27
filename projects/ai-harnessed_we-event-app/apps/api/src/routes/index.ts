import type { FastifyInstance } from "fastify";
import type { AppConfig } from "../config.js";
import { requireAuth } from "../auth/middleware.js";
import { authRoutes } from "../modules/auth/index.js";
import { adminRoutes } from "./admin.js";
import { devAuthRoutes } from "./dev-auth.js";
import { healthRoutes } from "./health.js";
import { eventRoutes, mediaRoutes } from "../modules/event/index.js";
import { auditRoutes } from "../modules/audit/index.js";
import { dashboardRoutes } from "../modules/dashboard/index.js";
import { checkinRoutes } from "../modules/checkin/index.js";
import { eligibilityRoutes } from "../modules/eligibility/index.js";
import { feedbackRoutes } from "../modules/feedback/index.js";
import { registrationRoutes } from "../modules/registration/index.js";
import { scopeRoutes } from "./scope.js";
import { sessionRoutes } from "./session.js";

export async function registerRoutes(
  app: FastifyInstance,
  basePath: string,
  config: AppConfig,
): Promise<void> {
  await app.register(healthRoutes, { prefix: basePath });
  await app.register(devAuthRoutes(config), { prefix: basePath });
  await app.register(authRoutes, { prefix: basePath });
  await app.register(mediaRoutes(config), { prefix: basePath });

  await app.register(
    async (protectedApp) => {
      protectedApp.addHook("onRequest", requireAuth);
      await protectedApp.register(sessionRoutes);
      await protectedApp.register(scopeRoutes);
      await protectedApp.register(eventRoutes(config));
      await protectedApp.register(registrationRoutes);
      await protectedApp.register(checkinRoutes);
      await protectedApp.register(feedbackRoutes);
      await protectedApp.register(eligibilityRoutes);
      await protectedApp.register(auditRoutes);
      await protectedApp.register(dashboardRoutes);
      await protectedApp.register(adminRoutes);
    },
    { prefix: basePath },
  );
}
