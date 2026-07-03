import { randomUUID } from "node:crypto";
import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { authorize, type ScopeBindings as AuthorizeBindings } from "./authorize.js";
import { verifyAccessToken } from "./jwt.js";
import { authDenied, unauthenticated } from "./http.js";
import type { IdentityRepository } from "./repository.js";
import type { Action, ActorContext, Resource, ScopeContext } from "./types.js";

declare module "fastify" {
  interface FastifyRequest {
    actor?: ActorContext;
    requestId?: string;
  }
}

export interface IdentityServices {
  repository: IdentityRepository;
}

function bearerToken(request: FastifyRequest): string | null {
  const header = request.headers.authorization;
  if (!header?.startsWith("Bearer ")) return null;
  return header.slice("Bearer ".length).trim() || null;
}

export async function registerIdentityHooks(app: FastifyInstance): Promise<void> {
  app.decorateRequest("actor", undefined);
  app.decorateRequest("requestId", undefined);

  app.addHook("onRequest", async (request) => {
    const header = request.headers["x-request-id"];
    request.requestId =
      typeof header === "string" && header.length > 0
        ? header
        : randomUUID();
  });
}

export function createAuthenticate(services: IdentityServices) {
  return async function authenticate(
    request: FastifyRequest,
    reply: FastifyReply,
  ): Promise<void> {
    const token = bearerToken(request);
    if (!token) {
      unauthenticated(reply, request);
      return reply;
    }

    try {
      const claims = await verifyAccessToken(token);
      const actor = await services.repository.buildActorContext(claims.sub);
      if (!actor) {
        unauthenticated(reply, request);
        return reply;
      }
      request.actor = actor;
    } catch {
      unauthenticated(reply, request);
      return reply;
    }
  };
}

export interface GuardOptions {
  resource: Resource;
  action: Action;
  resolveScope?: (request: FastifyRequest) => ScopeContext | Promise<ScopeContext>;
}

export function createAuthorizeGuard(services: IdentityServices, options: GuardOptions) {
  return async function authorizeGuard(
    request: FastifyRequest,
    reply: FastifyReply,
  ): Promise<void> {
    if (!request.actor) {
      unauthenticated(reply, request);
      return reply;
    }

    const scopeContext = options.resolveScope
      ? await options.resolveScope(request)
      : {};

    const dbBindings = await services.repository.resolveScopeBindings({
      classSectionId: scopeContext.classSectionId,
      classSessionId: scopeContext.classSessionId,
      facultyId: scopeContext.facultyId,
    });

    const lecturerSections = await services.repository.getLecturerClassSectionIds(
      request.actor.userId,
    );

    const bindings: AuthorizeBindings = {
      classSectionFacultyId: dbBindings.classSectionFacultyId,
      classSectionIdsForFaculty: dbBindings.classSectionIdsForFaculty,
      lecturerClassSectionIds: lecturerSections,
    };

    if (dbBindings.sessionClassSectionId && !scopeContext.classSectionId) {
      scopeContext.classSectionId = dbBindings.sessionClassSectionId;
    }

    if (options.resource === "CheckInSubmit" && request.actor) {
      scopeContext.studentUserId = request.actor.userId;
    }

    const decision = authorize(
      request.actor,
      options.resource,
      options.action,
      scopeContext,
      bindings,
    );

    if (!decision.allowed) {
      authDenied(reply, request, decision.code);
      return reply;
    }
  };
}

export function combineGuards(
  ...guards: Array<(request: FastifyRequest, reply: FastifyReply) => Promise<void>>
) {
  return async (request: FastifyRequest, reply: FastifyReply): Promise<void> => {
    for (const guard of guards) {
      await guard(request, reply);
      if (reply.sent) return;
    }
  };
}
