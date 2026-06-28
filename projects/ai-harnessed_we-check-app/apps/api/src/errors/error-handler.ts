import type { FastifyError, FastifyReply, FastifyRequest } from "fastify";
import { ErrorCode } from "@wecheck/domain";
import { ApiError, ERROR_MESSAGES, internalError } from "./api-error.js";

export function registerErrorHandler(app: {
  setErrorHandler: (
    handler: (
      error: FastifyError | ApiError | Error,
      request: FastifyRequest,
      reply: FastifyReply,
    ) => void | Promise<void>,
  ) => void;
}): void {
  app.setErrorHandler((error, request, reply) => {
    const requestId = request.requestId;

    if (error instanceof ApiError) {
      void reply.status(error.statusCode).send(error.toBody(requestId));
      return;
    }

    if (error instanceof SyntaxError || error.message?.includes("JSON")) {
      void reply.status(400).send({
        errorCode: ErrorCode.MalformedJson,
        message: ERROR_MESSAGES[ErrorCode.MalformedJson],
        requestId,
      });
      return;
    }

    request.log.error({ err: error, requestId }, "Unhandled error");
    const apiError = internalError();
    void reply.status(apiError.statusCode).send(apiError.toBody(requestId));
  });
}
