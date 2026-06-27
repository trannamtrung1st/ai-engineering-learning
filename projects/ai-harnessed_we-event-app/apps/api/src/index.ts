import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import fjwt from "@fastify/jwt";
import Fastify, { type FastifyError } from "fastify";
import { loadConfig } from "./config.js";
import { API_BASE_PATH, API_VERSION } from "./constants.js";
import { closeDb, initDb } from "./db/pool.js";
import { ApiError, buildErrorEnvelope } from "./errors/api-error.js";
import { runDevSeed } from "./infra/dev-seed.js";
import { registerRoutes } from "./routes/index.js";

export { API_BASE_PATH, API_VERSION };

export function getApiMetadata() {
  return {
    version: API_VERSION,
    basePath: API_BASE_PATH,
  };
}

export async function buildApp() {
  const config = loadConfig();
  await initDb(config.databaseUrl);

  const app = Fastify({
    logger: true,
    genReqId: () => randomUUID(),
  });

  await app.register(fjwt, {
    secret: config.jwtSecret,
  });

  app.setErrorHandler((error: FastifyError | ApiError, request, reply) => {
    const requestId = request.id;

    if (error instanceof ApiError) {
      reply
        .status(error.statusCode)
        .send(
          buildErrorEnvelope(
            error.code,
            error.message,
            requestId,
            error.details,
          ),
        );
      return;
    }

    if (error.validation) {
      reply.status(400).send(
        buildErrorEnvelope(
          "INVALID_INPUT",
          "Request validation failed.",
          requestId,
          { issues: error.validation },
        ),
      );
      return;
    }

    if (error.code === "FST_REQ_FILE_TOO_LARGE") {
      reply.status(400).send(
        buildErrorEnvelope(
          "INVALID_INPUT",
          "Cover image must be 5 MB or smaller.",
          requestId,
          { maxBytes: 5 * 1024 * 1024 },
        ),
      );
      return;
    }

    request.log.error({ err: error, requestId }, "unhandled error");
    reply.status(500).send(
      buildErrorEnvelope(
        "INTERNAL_ERROR",
        "An unexpected error occurred.",
        requestId,
      ),
    );
  });

  await registerRoutes(app, API_BASE_PATH, config);

  app.addHook("onClose", async () => {
    await closeDb();
  });

  return { app, config };
}

export async function startServer(): Promise<void> {
  const { app, config } = await buildApp();

  const shutdown = async () => {
    await app.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  await app.listen({ port: config.port, host: "0.0.0.0" });

  if (config.seedEnabled) {
    void runDevSeed().catch((error: unknown) => {
      app.log.error({ err: error }, "dev seed failed");
    });
  }
}

const isMainModule =
  process.argv[1] !== undefined &&
  import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMainModule) {
  startServer().catch((error: unknown) => {
    console.error("Failed to start API server:", error);
    // Let node --watch retry after dist/ or env changes instead of exiting.
  });
}
