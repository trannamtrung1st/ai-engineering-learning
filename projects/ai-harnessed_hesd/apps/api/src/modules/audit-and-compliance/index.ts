import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createAuditRepository } from "./repository.js";
import { registerAuditRoutes } from "./routes.js";

export interface AuditModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerAuditModule(
  app: FastifyInstance,
  options: AuditModuleOptions = {},
): Promise<ReturnType<typeof createAuditRepository> | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createAuditRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerAuditRoutes(app, identityServices, repository);
  return repository;
}

export {
  writeAuditEvent,
  writeAttendanceAuditEvent,
  writeCheckInAttemptAuditEvent,
  buildAttendanceAuditPayload,
} from "./service.js";
export type { WriteAuditEventInput } from "./service.js";
export { createAuditRepository } from "./repository.js";
export type { AuditRepository } from "./repository.js";
export { parseAuditLogQuery, deriveApiActionType, apiActionTypeToDbFilter } from "./validation.js";
export { resolveAuditReadScope } from "./scope.js";
export type {
  AuditLogEntry,
  AuditLogQueryFilters,
  ApiAuditActionType,
  AttendanceAuditSubtype,
} from "./types.js";
