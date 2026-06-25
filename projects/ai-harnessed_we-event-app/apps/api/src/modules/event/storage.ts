import { constants } from "node:fs";
import { access, mkdir, unlink, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { ApiError } from "../../errors/api-error.js";
import { COVER_IMAGE_KEY_PATTERN } from "./cover-image.js";

function eventsRoot(uploadsDir: string): string {
  return resolve(uploadsDir, "events");
}

export function resolveCoverImagePath(
  uploadsDir: string,
  key: string,
): string {
  if (!COVER_IMAGE_KEY_PATTERN.test(key)) {
    throw new ApiError({
      code: "NOT_FOUND",
      message: "Cover image not found.",
      statusCode: 404,
      details: { key },
    });
  }

  const root = eventsRoot(uploadsDir);
  const filePath = resolve(root, key);
  const rootWithSep = `${root}/`;
  if (!filePath.startsWith(rootWithSep)) {
    throw new ApiError({
      code: "NOT_FOUND",
      message: "Cover image not found.",
      statusCode: 404,
      details: { key },
    });
  }

  return filePath;
}

export async function ensureEventsUploadDir(uploadsDir: string): Promise<void> {
  await mkdir(eventsRoot(uploadsDir), { recursive: true });
}

export async function saveCoverImage(
  uploadsDir: string,
  key: string,
  data: Buffer,
): Promise<void> {
  const filePath = resolveCoverImagePath(uploadsDir, key);
  await mkdir(dirname(filePath), { recursive: true });
  await writeFile(filePath, data);
}

export async function deleteCoverImageFile(
  uploadsDir: string,
  key: string,
): Promise<void> {
  try {
    const filePath = resolveCoverImagePath(uploadsDir, key);
    await unlink(filePath);
  } catch (error) {
    if (
      error instanceof ApiError ||
      (error as NodeJS.ErrnoException).code === "ENOENT"
    ) {
      return;
    }
    throw error;
  }
}

export async function readCoverImage(
  uploadsDir: string,
  key: string,
): Promise<Buffer> {
  const filePath = resolveCoverImagePath(uploadsDir, key);
  try {
    await access(filePath, constants.R_OK);
  } catch {
    throw new ApiError({
      code: "NOT_FOUND",
      message: "Cover image not found.",
      statusCode: 404,
      details: { key },
    });
  }

  const { readFile } = await import("node:fs/promises");
  return readFile(filePath);
}
