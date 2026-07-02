import Fastify from "fastify";
import { registerHealthRoutes } from "./routes/health.js";

export async function buildApp() {
  const app = Fastify({ logger: false });
  await app.register(
    async (v1) => {
      registerHealthRoutes(v1);
    },
    { prefix: "/api/v1" },
  );
  return app;
}
