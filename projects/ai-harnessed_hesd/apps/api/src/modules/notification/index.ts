import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createNotificationRepository } from "./repository.js";
import { registerNotificationRoutes } from "./routes.js";

export interface NotificationModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerNotificationModule(
  app: FastifyInstance,
  options: NotificationModuleOptions = {},
): Promise<ReturnType<typeof createNotificationRepository> | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createNotificationRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerNotificationRoutes(app, identityServices, repository);
  return repository;
}

export { createNotificationRepository } from "./repository.js";
export type { NotificationRepository } from "./repository.js";
export {
  computeUnexcusedAbsenceRate,
  exceedsAbsenceThreshold,
  resolveConfiguredAbsenceThreshold,
  resolveExcusedCountsTowardThreshold,
} from "./evaluator.js";
export { isNotificationModuleEnabled } from "./config.js";
