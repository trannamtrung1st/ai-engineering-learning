import type { FastifyPluginAsync } from "fastify";
import type { AppConfig } from "../../config.js";
import { ApiError } from "../../errors/api-error.js";
import {
  buildCoverImageUrl,
  mimeForCoverImageKey,
} from "./cover-image.js";
import { readCoverImage } from "./storage.js";

interface MediaParams {
  "*": string;
}

export function mediaRoutes(config: AppConfig): FastifyPluginAsync {
  return async (app) => {
    app.get<{ Params: MediaParams }>(
      "/media/events/*",
      async (request, reply) => {
        const key = request.params["*"];
        if (!key) {
          throw new ApiError({
            code: "NOT_FOUND",
            message: "Cover image not found.",
            statusCode: 404,
          });
        }

        const mimeType = mimeForCoverImageKey(key);
        if (!mimeType) {
          throw new ApiError({
            code: "NOT_FOUND",
            message: "Cover image not found.",
            statusCode: 404,
            details: { key },
          });
        }

        const data = await readCoverImage(config.uploadsDir, key);
        reply
          .header("Content-Type", mimeType)
          .header("Cache-Control", "public, max-age=3600")
          .send(data);
      },
    );
  };
}

export { buildCoverImageUrl };
