import { ErrorCode } from "@wecheck/domain";
import type { ErrorDetail } from "../../errors/api-error.js";

/** Uppercase alphanumeric + hyphen per validation rules §3.2a */
export const REFERENCE_CODE_RE = /^[A-Z0-9-]{2,16}$/;

export interface ValidationResult<T> {
  ok: true;
  value: T;
}

export interface ValidationFailure {
  ok: false;
  details: ErrorDetail[];
}

export type ParseResult<T> = ValidationResult<T> | ValidationFailure;

export interface CreateReferenceInput {
  code: string;
  name: string;
}

function fail(field: string, code: string, message: string): ValidationFailure {
  return { ok: false, details: [{ field, code, message }] };
}

export function validateReferenceCode(code: unknown, field = "code"): ParseResult<string> {
  if (typeof code !== "string" || !code.trim()) {
    return fail(field, ErrorCode.InvalidFormat, "Định dạng trường không hợp lệ");
  }
  const trimmed = code.trim();
  if (!REFERENCE_CODE_RE.test(trimmed)) {
    return fail(field, ErrorCode.InvalidFormat, "Định dạng trường không hợp lệ");
  }
  return { ok: true, value: trimmed };
}

export function validateReferenceName(name: unknown, field = "name"): ParseResult<string> {
  if (typeof name !== "string") {
    return fail(field, ErrorCode.InvalidLength, "Độ dài dữ liệu không hợp lệ");
  }
  const trimmed = name.trim();
  if (trimmed.length < 1 || trimmed.length > 200) {
    return fail(field, ErrorCode.InvalidLength, "Độ dài dữ liệu không hợp lệ");
  }
  return { ok: true, value: trimmed };
}

export function parseCreateReferenceBody(
  body: unknown,
): ParseResult<CreateReferenceInput> {
  if (typeof body !== "object" || body === null) {
    return fail("body", ErrorCode.ValidationFailed, "Dữ liệu không hợp lệ");
  }
  const record = body as Record<string, unknown>;
  const codeResult = validateReferenceCode(record.code);
  if (!codeResult.ok) {
    return codeResult;
  }
  const nameResult = validateReferenceName(record.name);
  if (!nameResult.ok) {
    return nameResult;
  }
  return {
    ok: true,
    value: { code: codeResult.value, name: nameResult.value },
  };
}
