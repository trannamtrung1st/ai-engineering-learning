import type { FastifyPluginAsync } from "fastify";
import { authService, signAuthToken } from "./service.js";
import { ensureUserSchema } from "../user/repository.js";

interface RegisterBody {
  email: string;
  password: string;
  displayName: string;
}

interface LoginBody {
  email: string;
  password: string;
}

export const authRoutes: FastifyPluginAsync = async (app) => {
  await ensureUserSchema();

  app.post<{ Body: RegisterBody }>("/auth/register", async (request, reply) => {
    const body = request.body ?? ({} as RegisterBody);
    return authService.register(body, (payload) => signAuthToken(reply, payload));
  });

  app.post<{ Body: LoginBody }>("/auth/login", async (request, reply) => {
    const body = request.body ?? ({} as LoginBody);
    return authService.login(body, (payload) => signAuthToken(reply, payload));
  });
};
