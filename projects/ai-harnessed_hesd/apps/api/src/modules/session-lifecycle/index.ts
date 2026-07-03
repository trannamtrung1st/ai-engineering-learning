import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createSessionLifecycleRepository } from "./repository.js";
import { registerSessionLifecycleRoutes } from "./routes.js";

export interface SessionLifecycleModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerSessionLifecycleModule(
  app: FastifyInstance,
  options: SessionLifecycleModuleOptions = {},
): Promise<ReturnType<typeof createSessionLifecycleRepository> | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createSessionLifecycleRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerSessionLifecycleRoutes(app, identityServices, repository);
  return repository;
}

export { createSessionLifecycleRepository } from "./repository.js";
export type { SessionLifecycleRepository } from "./repository.js";
export {
  sessionCheckInGate,
  validateCloseTransition,
  validateOpenTransition,
} from "./validation.js";
export type {
  ClassSessionRow,
  CloseSessionResult,
  CloseSummary,
  OpenSessionResult,
  SessionState,
} from "./types.js";
