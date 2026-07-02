import pg from "pg";
import type { FastifyInstance } from "fastify";
import { registerAuthRoutes } from "./auth-routes.js";
import { registerIdentityHooks } from "./middleware.js";
import { registerProtectedRouteStubs } from "./protected-stubs.js";
import { createIdentityRepository } from "./repository.js";

export interface IdentityModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerIdentityModule(
  app: FastifyInstance,
  options: IdentityModuleOptions = {},
): Promise<pg.Pool | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createIdentityRepository(pool);
  const services = { repository };

  await registerIdentityHooks(app);
  await registerAuthRoutes(app, { repository });
  await registerProtectedRouteStubs(app, services);

  return pool;
}

export { authorize } from "./authorize.js";
export { capabilityForRole, rolesWithCapability } from "./permissions.js";
export { createIdentityRepository, toMeResponse } from "./repository.js";
export type { ActorContext, AuthDecision, Role, RoleAssignment, ScopeContext } from "./types.js";
