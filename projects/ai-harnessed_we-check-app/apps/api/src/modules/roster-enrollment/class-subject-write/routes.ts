import type { FastifyInstance } from "fastify";
import { UserRole } from "@wecheck/domain";
import type { DbPool } from "../../../infra/db.js";
import {
  createAuthMiddleware,
  requirePermission,
} from "../../../auth/middleware.js";
import { Permission } from "../../../auth/permissions.js";
import type { SessionStore } from "../../../auth/session-store.js";
import { forbidden, validationFailed } from "../../../errors/api-error.js";
import { parseCreateReferenceBody } from "../validation.js";
import { ClassSubjectWriteService } from "./class-subject-write-service.js";

export async function registerClassSubjectWriteRoutes(
  app: FastifyInstance,
  db: DbPool,
  store: SessionStore,
): Promise<void> {
  const writeService = new ClassSubjectWriteService(db);
  const auth = createAuthMiddleware(store);

  app.post(
    "/classes",
    { preHandler: [auth, requirePermission(Permission.RosterWrite)] },
    async (request, reply) => {
      if (request.auth?.user.role !== UserRole.TrainingOfficeAdmin) {
        throw forbidden();
      }

      const parsed = parseCreateReferenceBody(request.body);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const created = await writeService.createClass(
        parsed.value.code,
        parsed.value.name,
      );

      return reply.status(201).send({
        id: created.id,
        code: created.code,
        name: created.name,
        term: created.term,
      });
    },
  );

  app.post(
    "/subjects",
    { preHandler: [auth, requirePermission(Permission.RosterWrite)] },
    async (request, reply) => {
      if (request.auth?.user.role !== UserRole.TrainingOfficeAdmin) {
        throw forbidden();
      }

      const parsed = parseCreateReferenceBody(request.body);
      if (!parsed.ok) {
        throw validationFailed(parsed.details);
      }

      const created = await writeService.createSubject(
        parsed.value.code,
        parsed.value.name,
      );

      return reply.status(201).send({
        id: created.id,
        code: created.code,
        name: created.name,
      });
    },
  );
}
