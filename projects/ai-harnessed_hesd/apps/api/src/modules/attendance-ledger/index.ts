import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createAttendanceLedgerRepository } from "./repository.js";
import { registerAttendanceLedgerRoutes } from "./routes.js";

export interface AttendanceLedgerModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerAttendanceLedgerModule(
  app: FastifyInstance,
  options: AttendanceLedgerModuleOptions = {},
): Promise<ReturnType<typeof createAttendanceLedgerRepository> | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createAttendanceLedgerRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerAttendanceLedgerRoutes(app, identityServices, repository);
  return repository;
}

export { createAttendanceLedgerRepository } from "./repository.js";
export type { AttendanceLedgerRepository } from "./repository.js";
export {
  isAdminOverrideRole,
  isAttendanceStatus,
  isCorrectableStatus,
  isSuccessfulAttendance,
  isWithinManualEditWindow,
  validateCorrectionPayload,
  validateCorrectionWindow,
} from "./validation.js";
export type {
  AttendanceStatus,
  CorrectionResult,
  RosterCounts,
  RosterRow,
  SessionRoster,
} from "./types.js";
