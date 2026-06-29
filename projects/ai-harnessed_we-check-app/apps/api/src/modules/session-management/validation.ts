import {
  ErrorCode,
  GPS_RADIUS_DEFAULT_METERS,
  GPS_RADIUS_MAX_METERS,
  GPS_RADIUS_MIN_METERS,
} from "@wecheck/domain";
import type { ErrorDetail } from "../../errors/api-error.js";
import { now } from "../../infra/clock.js";
import type { CreateSessionInput, PatchSessionInput } from "./types.js";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;

function outOfRange(field: string, message: string): ErrorDetail {
  return { field, code: "OutOfRange", message };
}

function invalidFormat(field: string): ErrorDetail {
  return {
    field,
    code: ErrorCode.InvalidFormat,
    message: "Định dạng trường không hợp lệ",
  };
}

function invalidLength(field: string, message: string): ErrorDetail {
  return { field, code: ErrorCode.InvalidLength, message };
}

function invalidTimestamp(field: string): ErrorDetail {
  return {
    field,
    code: ErrorCode.InvalidTimestamp,
    message: "Thời gian không hợp lệ",
  };
}

function validateUuid(value: unknown, field: string): ErrorDetail | null {
  if (typeof value !== "string" || !UUID_RE.test(value)) {
    return invalidFormat(field);
  }
  return null;
}

function validateCoordinate(
  value: unknown,
  field: string,
  min: number,
  max: number,
): ErrorDetail | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return invalidFormat(field);
  }
  if (value < min || value > max) {
    return outOfRange(field, `Giá trị phải từ ${min} đến ${max}`);
  }
  return null;
}

function validateScheduledStart(value: unknown): ErrorDetail | null {
  if (typeof value !== "string") {
    return invalidTimestamp("scheduledStart");
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return invalidTimestamp("scheduledStart");
  }
  const cutoff = now().getTime() - SEVEN_DAYS_MS;
  if (parsed.getTime() < cutoff) {
    return outOfRange(
      "scheduledStart",
      "Thời gian bắt đầu không được quá 7 ngày trong quá khứ",
    );
  }
  return null;
}

function validateTitle(value: unknown): ErrorDetail | null {
  if (typeof value !== "string") {
    return invalidLength("title", "Tiêu đề buổi học là bắt buộc");
  }
  const trimmed = value.trim();
  if (trimmed.length < 1 || trimmed.length > 200) {
    return invalidLength("title", "Tiêu đề phải từ 1 đến 200 ký tự");
  }
  return null;
}

function validateRoomName(value: unknown): ErrorDetail | null {
  if (typeof value !== "string") {
    return invalidLength("roomName", "Tên phòng là bắt buộc");
  }
  const trimmed = value.trim();
  if (trimmed.length < 1 || trimmed.length > 100) {
    return invalidLength("roomName", "Tên phòng phải từ 1 đến 100 ký tự");
  }
  return null;
}

function validateRadius(value: unknown): ErrorDetail | null {
  if (value === undefined) {
    return null;
  }
  if (typeof value !== "number" || !Number.isInteger(value)) {
    return invalidFormat("gpsRadiusMeters");
  }
  if (value < GPS_RADIUS_MIN_METERS || value > GPS_RADIUS_MAX_METERS) {
    return outOfRange(
      "gpsRadiusMeters",
      `Giá trị phải từ ${GPS_RADIUS_MIN_METERS} đến ${GPS_RADIUS_MAX_METERS} mét`,
    );
  }
  return null;
}

/** FR-04 — validate session create payload. */
export function validateCreateSession(
  input: CreateSessionInput,
): ErrorDetail[] {
  const errors: ErrorDetail[] = [];

  for (const [field, value] of [
    ["classId", input.classId],
    ["subjectId", input.subjectId],
  ] as const) {
    const err = validateUuid(value, field);
    if (err) errors.push(err);
  }

  for (const check of [
    validateTitle(input.title),
    validateRoomName(input.roomName),
    validateScheduledStart(input.scheduledStart),
    validateCoordinate(input.roomLatitude, "roomLatitude", -90, 90),
    validateCoordinate(input.roomLongitude, "roomLongitude", -180, 180),
    validateRadius(input.gpsRadiusMeters),
  ]) {
    if (check) errors.push(check);
  }

  return errors;
}

/** FR-04 — validate session patch payload. */
export function validatePatchSession(
  input: PatchSessionInput,
): ErrorDetail[] {
  const errors: ErrorDetail[] = [];

  if (input.title !== undefined) {
    const err = validateTitle(input.title);
    if (err) errors.push(err);
  }
  if (input.roomName !== undefined) {
    const err = validateRoomName(input.roomName);
    if (err) errors.push(err);
  }
  if (input.scheduledStart !== undefined) {
    const err = validateScheduledStart(input.scheduledStart);
    if (err) errors.push(err);
  }
  if (input.roomLatitude !== undefined) {
    const err = validateCoordinate(input.roomLatitude, "roomLatitude", -90, 90);
    if (err) errors.push(err);
  }
  if (input.roomLongitude !== undefined) {
    const err = validateCoordinate(
      input.roomLongitude,
      "roomLongitude",
      -180,
      180,
    );
    if (err) errors.push(err);
  }
  if (input.gpsRadiusMeters !== undefined) {
    const err = validateRadius(input.gpsRadiusMeters);
    if (err) errors.push(err);
  }

  return errors;
}

export function normalizeCreateSession(
  input: CreateSessionInput,
): CreateSessionInput {
  return {
    ...input,
    title: input.title.trim(),
    roomName: input.roomName.trim(),
    gpsRadiusMeters: input.gpsRadiusMeters ?? GPS_RADIUS_DEFAULT_METERS,
    roomLatitude: input.roomLatitude ?? null,
    roomLongitude: input.roomLongitude ?? null,
  };
}
