import { API_BASE_PATH } from "../../constants.js";
import { ApiError } from "../../errors/api-error.js";

export const COVER_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

export const ALLOWED_COVER_IMAGE_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

export type AllowedCoverImageMimeType =
  (typeof ALLOWED_COVER_IMAGE_MIME_TYPES)[number];

export const COVER_IMAGE_KEY_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(jpe?g|png|webp)$/i;

const MIME_TO_EXTENSION: Record<AllowedCoverImageMimeType, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
};

const EXTENSION_TO_MIME: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
};

export function extensionForMime(mimeType: string): string | null {
  if (
    !ALLOWED_COVER_IMAGE_MIME_TYPES.includes(
      mimeType as AllowedCoverImageMimeType,
    )
  ) {
    return null;
  }
  return MIME_TO_EXTENSION[mimeType as AllowedCoverImageMimeType];
}

export function mimeForCoverImageKey(key: string): string | null {
  const match = key.match(/\.([a-z0-9]+)$/i);
  if (!match) {
    return null;
  }
  return EXTENSION_TO_MIME[match[1]!.toLowerCase()] ?? null;
}

export function validateCoverImage(
  mimeType: string | undefined,
  byteLength: number,
): void {
  if (!mimeType || !extensionForMime(mimeType)) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message:
        "Cover image must be JPEG, PNG, or WebP (image/jpeg, image/png, image/webp).",
      statusCode: 400,
      details: { mimeType: mimeType ?? null },
    });
  }

  if (byteLength <= 0) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "Cover image file is empty.",
      statusCode: 400,
    });
  }

  if (byteLength > COVER_IMAGE_MAX_BYTES) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "Cover image must be 5 MB or smaller.",
      statusCode: 400,
      details: { maxBytes: COVER_IMAGE_MAX_BYTES, sizeBytes: byteLength },
    });
  }
}

export function buildCoverImageKey(
  eventId: string,
  fileId: string,
  extension: string,
): string {
  return `${eventId}/${fileId}.${extension}`;
}

export function buildCoverImageUrl(coverImageKey: string): string {
  return `${API_BASE_PATH}/media/events/${coverImageKey}`;
}
