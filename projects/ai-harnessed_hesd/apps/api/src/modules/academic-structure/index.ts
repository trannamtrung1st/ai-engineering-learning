import pg from "pg";
import type { FastifyInstance } from "fastify";
import type { IdentityServices } from "../identity/middleware.js";
import { createIdentityRepository } from "../identity/repository.js";
import { createAcademicRepository, type AcademicRepository } from "./repository.js";
import { registerAcademicRoutes } from "./routes.js";

export interface AcademicModuleOptions {
  connectionString?: string;
  pool?: pg.Pool;
}

export async function registerAcademicStructureModule(
  app: FastifyInstance,
  options: AcademicModuleOptions = {},
): Promise<AcademicRepository | null> {
  const connectionString = options.connectionString ?? process.env.DATABASE_URL;
  if (!connectionString && !options.pool) {
    return null;
  }

  const pool = options.pool ?? new pg.Pool({ connectionString });
  const repository = createAcademicRepository(pool);
  const identityServices: IdentityServices = {
    repository: createIdentityRepository(pool),
  };

  await registerAcademicRoutes(app, identityServices, repository);
  return repository;
}

export { createAcademicRepository, isStudentEnrolled } from "./repository.js";
export type { AcademicRepository } from "./repository.js";
export type {
  ClassSectionRow,
  CourseRow,
  EnrollmentImportResult,
  RoomRow,
  TermRow,
} from "./types.js";
