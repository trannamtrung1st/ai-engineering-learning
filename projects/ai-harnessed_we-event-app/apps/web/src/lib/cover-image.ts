export const COVER_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

export const ALLOWED_COVER_IMAGE_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

export type AllowedCoverImageMimeType =
  (typeof ALLOWED_COVER_IMAGE_MIME_TYPES)[number];

export function validateCoverImageFile(file: File): string | null {
  if (
    !ALLOWED_COVER_IMAGE_MIME_TYPES.includes(
      file.type as AllowedCoverImageMimeType,
    )
  ) {
    return "Cover image must be JPEG, PNG, or WebP.";
  }

  if (file.size <= 0) {
    return "Cover image file is empty.";
  }

  if (file.size > COVER_IMAGE_MAX_BYTES) {
    return "Cover image must be 5 MB or smaller.";
  }

  return null;
}
