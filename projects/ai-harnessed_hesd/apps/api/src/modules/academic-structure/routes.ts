import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode } from "@attendly/domain";
import {
  combineGuards,
  createAuthenticate,
  createAuthorizeGuard,
  type IdentityServices,
} from "../identity/middleware.js";
import type { ActorContext } from "../identity/types.js";
import { forbidden, resolveRequestId, sendApiError, sendApiSuccess } from "../identity/http.js";
import { buildPaginationMeta, parsePagination } from "./pagination.js";
import type { AcademicRepository } from "./repository.js";
import type { ScheduleTemplate } from "./types.js";
import { isUuid, validateScheduleTemplate, validateTermDates } from "./validation.js";

function requireAcademicAdmin(actor: ActorContext | undefined, reply: FastifyReply, request: FastifyRequest): boolean {
  if (!actor?.roles.includes("AcademicAdmin")) {
    forbidden(reply, request);
    return false;
  }
  return true;
}

function canReadClassSections(actor: ActorContext | undefined): boolean {
  if (!actor) return false;
  return actor.roles.some((role) =>
    ["Lecturer", "DepartmentAdmin", "AcademicAdmin"].includes(role),
  );
}

function paginatedSuccess<T>(
  reply: FastifyReply,
  request: FastifyRequest,
  items: T[],
  page: number,
  pageSize: number,
  totalItems: number,
): void {
  const body = {
    data: items,
    meta: {
      requestId: resolveRequestId(request),
      timestamp: new Date().toISOString(),
      pagination: buildPaginationMeta(page, pageSize, totalItems),
    },
    error: null,
  };
  void reply.status(200).send(body);
}

export async function registerAcademicRoutes(
  app: FastifyInstance,
  services: IdentityServices,
  repository: AcademicRepository,
): Promise<void> {
  const authenticate = createAuthenticate(services);

  const guardEnrollmentImport = createAuthorizeGuard(services, {
    resource: "Enrollment",
    action: "create",
    resolveScope: (request) => {
      const body = request.body as { classSectionId?: string };
      return { classSectionId: body.classSectionId };
    },
  });

  app.post("/terms", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const body = request.body as {
      code?: string;
      name?: string;
      startDate?: string;
      endDate?: string;
      isActive?: boolean;
    };

    if (!body.code?.trim() || !body.name?.trim() || !body.startDate || !body.endDate) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    if (!validateTermDates(body.startDate, body.endDate)) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    if (await repository.termCodeExists(body.code.trim())) {
      sendApiError(reply, request, 409, ErrorCode.Conflict);
      return;
    }

    try {
      const term = await repository.createTerm({
        code: body.code.trim(),
        name: body.name.trim(),
        startDate: body.startDate,
        endDate: body.endDate,
        isActive: body.isActive ?? true,
      });
      sendApiSuccess(reply, request, 200, term);
    } catch (error) {
      if ((error as { code?: string }).code === "23505") {
        sendApiError(reply, request, 409, ErrorCode.Conflict);
        return;
      }
      throw error;
    }
  });

  app.get("/terms", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const query = request.query as { page?: string; pageSize?: string; activeOnly?: string };
    const { page, pageSize, offset } = parsePagination(query);
    const activeOnly = query.activeOnly === "true";
    const { items, total } = await repository.listTerms(offset, pageSize, activeOnly);
    paginatedSuccess(reply, request, items, page, pageSize, total);
  });

  app.get("/terms/:termId", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const { termId } = request.params as { termId: string };
    if (!isUuid(termId)) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    const term = await repository.getTermById(termId);
    if (!term) {
      sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
      return;
    }
    sendApiSuccess(reply, request, 200, term);
  });

  app.patch("/terms/:termId", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const { termId } = request.params as { termId: string };
    const body = request.body as {
      name?: string;
      startDate?: string;
      endDate?: string;
      isActive?: boolean;
    };

    if (!isUuid(termId)) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    const current = await repository.getTermById(termId);
    if (!current) {
      sendApiError(reply, request, 404, ErrorCode.SessionNotFound);
      return;
    }

    const startDate = body.startDate ?? current.startDate;
    const endDate = body.endDate ?? current.endDate;
    if (!validateTermDates(startDate, endDate)) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    const updated = await repository.updateTerm(termId, {
      name: body.name?.trim(),
      startDate: body.startDate,
      endDate: body.endDate,
      isActive: body.isActive,
    });
    sendApiSuccess(reply, request, 200, updated);
  });

  app.post("/courses", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const body = request.body as {
      code?: string;
      name?: string;
      facultyId?: string;
      creditUnits?: number;
    };

    if (!body.code?.trim() || !body.name?.trim() || !isUuid(body.facultyId)) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    if (!(await repository.facultyExists(body.facultyId!))) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    try {
      const course = await repository.createCourse({
        code: body.code.trim(),
        name: body.name.trim(),
        facultyId: body.facultyId!,
        creditUnits: body.creditUnits,
      });
      sendApiSuccess(reply, request, 200, course);
    } catch (error) {
      if ((error as { code?: string }).code === "23505") {
        sendApiError(reply, request, 409, ErrorCode.Conflict);
        return;
      }
      throw error;
    }
  });

  app.get("/courses", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const query = request.query as { page?: string; pageSize?: string };
    const { page, pageSize, offset } = parsePagination(query);
    const { items, total } = await repository.listCourses(offset, pageSize);
    paginatedSuccess(reply, request, items, page, pageSize, total);
  });

  app.post("/rooms", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const body = request.body as {
      code?: string;
      name?: string;
      building?: string;
      latitude?: number;
      longitude?: number;
    };

    if (!body.code?.trim() || !body.name?.trim()) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    try {
      const room = await repository.createRoom({
        code: body.code.trim(),
        name: body.name.trim(),
        building: body.building?.trim(),
        latitude: body.latitude,
        longitude: body.longitude,
      });
      sendApiSuccess(reply, request, 200, room);
    } catch (error) {
      if ((error as { code?: string }).code === "23505") {
        sendApiError(reply, request, 409, ErrorCode.Conflict);
        return;
      }
      throw error;
    }
  });

  app.get("/rooms", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const query = request.query as { page?: string; pageSize?: string };
    const { page, pageSize, offset } = parsePagination(query);
    const { items, total } = await repository.listRooms(offset, pageSize);
    paginatedSuccess(reply, request, items, page, pageSize, total);
  });

  app.post("/class-sections", { preHandler: authenticate }, async (request, reply) => {
    if (!requireAcademicAdmin(request.actor, reply, request)) return;

    const body = request.body as {
      sectionCode?: string;
      termId?: string;
      courseId?: string;
      lecturerUserId?: string;
      defaultRoomId?: string;
      capacity?: number;
      scheduleTemplate?: ScheduleTemplate;
    };

    if (
      !body.sectionCode?.trim() ||
      !isUuid(body.termId) ||
      !isUuid(body.courseId) ||
      !isUuid(body.lecturerUserId)
    ) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    if (body.defaultRoomId && !isUuid(body.defaultRoomId)) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    const templateError = validateScheduleTemplate(body.scheduleTemplate);
    if (templateError) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    const term = await repository.getTermById(body.termId!);
    if (!term) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    const course = await repository.getCourseById(body.courseId!);
    if (!course) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    if (!(await repository.userExists(body.lecturerUserId!))) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    if (body.defaultRoomId && !(await repository.getRoomById(body.defaultRoomId))) {
      sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
      return;
    }

    try {
      const { section, generatedSessionCount } = await repository.createClassSection({
        sectionCode: body.sectionCode.trim(),
        termId: body.termId!,
        courseId: body.courseId!,
        lecturerUserId: body.lecturerUserId!,
        defaultRoomId: body.defaultRoomId,
        capacity: body.capacity,
        scheduleTemplate: body.scheduleTemplate,
      });

      sendApiSuccess(reply, request, 200, {
        ...section,
        generatedSessionCount,
      });
    } catch (error) {
      if ((error as { code?: string }).code === "23503") {
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }
      if ((error as { code?: string }).code === "23505") {
        sendApiError(reply, request, 409, ErrorCode.Conflict);
        return;
      }
      throw error;
    }
  });

  app.get("/class-sections", { preHandler: authenticate }, async (request, reply) => {
    if (!canReadClassSections(request.actor)) {
      forbidden(reply, request);
      return;
    }

    const query = request.query as {
      page?: string;
      pageSize?: string;
      termId?: string;
      lecturerUserId?: string;
    };
    const { page, pageSize, offset } = parsePagination(query);

    const filters: { termId?: string; lecturerUserId?: string } = {};
    if (query.termId) filters.termId = query.termId;
    if (query.lecturerUserId) filters.lecturerUserId = query.lecturerUserId;

    const { items, total } = await repository.listClassSections(filters, offset, pageSize);
    paginatedSuccess(reply, request, items, page, pageSize, total);
  });

  app.post(
    "/enrollments/import",
    { preHandler: combineGuards(authenticate, guardEnrollmentImport) },
    async (request, reply) => {
      const body = request.body as {
        classSectionId?: string;
        rows?: { studentCode?: string }[];
      };

      if (!isUuid(body.classSectionId) || !Array.isArray(body.rows)) {
        sendApiError(reply, request, 400, ErrorCode.InvalidPayload);
        return;
      }

      try {
        const result = await repository.importEnrollments(
          body.classSectionId!,
          body.rows,
          request.actor!.userId,
        );
        sendApiSuccess(reply, request, 200, result);
      } catch (error) {
        if (error instanceof Error && error.message === "SECTION_NOT_FOUND") {
          sendApiError(reply, request, 404, ErrorCode.SessionNotFound, {
            classSectionId: body.classSectionId,
          });
          return;
        }
        throw error;
      }
    },
  );
}
