import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createPolicyEngineRepository } from "./repository.js";
import { registerPolicyRoutes } from "./routes.js";

export interface PolicyEngineModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerPolicyEngineModule(
  app: FastifyInstance,
  options: PolicyEngineModuleOptions = {},
): Promise<ReturnType<typeof createPolicyEngineRepository> | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createPolicyEngineRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerPolicyRoutes(app, identityServices, repository);
  return repository;
}

export { createPolicyEngineRepository } from "./repository.js";
export type { PolicyEngineRepository } from "./repository.js";
export {
  flattenResolvedPolicy,
  indexPoliciesByScope,
  resolveEffectivePolicyFromRows,
} from "./resolver.js";
export {
  evaluateGpsDistance,
  evaluateGpsPayload,
  haversineMeters,
  isWithinManualEditWindow,
  resolveAttendanceStatus,
} from "./validation.js";
export type {
  AttendancePolicyRecord,
  EffectivePolicyValues,
  GpsPayload,
  PolicyScopeType,
  ResolvedEffectivePolicy,
} from "./types.js";
