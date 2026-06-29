import { ErrorCode } from "@wecheck/domain";
import type { ErrorDetail } from "../../errors/api-error.js";
import type { CheckInRequestBody } from "./types.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isFiniteCoord(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
}

export function validateCheckInBody(body: unknown): {
  ok: true;
  value: Required<Pick<CheckInRequestBody, "tokenId" | "latitude" | "longitude">> &
    Pick<CheckInRequestBody, "gpsAvailable" | "spoofMetadata">;
} | { ok: false; errors: ErrorDetail[] } {
  if (body === null || typeof body !== "object") {
    return {
      ok: false,
      errors: [
        {
          field: "body",
          code: ErrorCode.ValidationFailed,
          message: "Dữ liệu không hợp lệ",
        },
      ],
    };
  }

  const input = body as Record<string, unknown>;
  const errors: ErrorDetail[] = [];

  if (typeof input.tokenId !== "string" || !UUID_RE.test(input.tokenId)) {
    errors.push({
      field: "tokenId",
      code: ErrorCode.InvalidFormat,
      message: "Định dạng trường không hợp lệ",
    });
  }

  if (input.latitude === undefined || !isFiniteCoord(input.latitude, -90, 90)) {
    errors.push({
      field: "latitude",
      code: ErrorCode.InvalidFormat,
      message: "Tọa độ vĩ độ không hợp lệ",
    });
  }

  if (input.longitude === undefined || !isFiniteCoord(input.longitude, -180, 180)) {
    errors.push({
      field: "longitude",
      code: ErrorCode.InvalidFormat,
      message: "Tọa độ kinh độ không hợp lệ",
    });
  }

  if (input.gpsAvailable !== undefined && typeof input.gpsAvailable !== "boolean") {
    errors.push({
      field: "gpsAvailable",
      code: ErrorCode.InvalidFormat,
      message: "Trường gpsAvailable phải là boolean",
    });
  }

  if (input.spoofMetadata !== undefined) {
    if (input.spoofMetadata === null || typeof input.spoofMetadata !== "object") {
      errors.push({
        field: "spoofMetadata",
        code: ErrorCode.InvalidFormat,
        message: "spoofMetadata không hợp lệ",
      });
    } else {
      const meta = input.spoofMetadata as Record<string, unknown>;
      if (
        meta.mockLocationDetected !== undefined &&
        typeof meta.mockLocationDetected !== "boolean"
      ) {
        errors.push({
          field: "spoofMetadata.mockLocationDetected",
          code: ErrorCode.InvalidFormat,
          message: "mockLocationDetected phải là boolean",
        });
      }
      if (
        meta.accuracyMeters !== undefined &&
        (typeof meta.accuracyMeters !== "number" ||
          !Number.isFinite(meta.accuracyMeters) ||
          meta.accuracyMeters < 0)
      ) {
        errors.push({
          field: "spoofMetadata.accuracyMeters",
          code: ErrorCode.InvalidFormat,
          message: "accuracyMeters phải là số không âm",
        });
      }
      if (
        meta.platform !== undefined &&
        !["ios", "android", "other"].includes(String(meta.platform))
      ) {
        errors.push({
          field: "spoofMetadata.platform",
          code: ErrorCode.InvalidEnum,
          message: "platform phải là ios, android hoặc other",
        });
      }
    }
  }

  if (errors.length > 0) {
    return { ok: false, errors };
  }

  const spoofMetadata =
    input.spoofMetadata !== undefined
      ? (input.spoofMetadata as CheckInRequestBody["spoofMetadata"])
      : undefined;

  return {
    ok: true,
    value: {
      tokenId: input.tokenId as string,
      latitude: input.latitude as number,
      longitude: input.longitude as number,
      gpsAvailable: input.gpsAvailable as boolean | undefined,
      spoofMetadata,
    },
  };
}

export function hasGpsCoordinates(
  input: Pick<CheckInRequestBody, "latitude" | "longitude" | "gpsAvailable">,
): boolean {
  if (input.gpsAvailable === false) {
    return false;
  }
  return (
    typeof input.latitude === "number" &&
    typeof input.longitude === "number" &&
    Number.isFinite(input.latitude) &&
    Number.isFinite(input.longitude)
  );
}
