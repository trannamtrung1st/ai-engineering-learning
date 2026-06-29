import {
  ErrorCode,
  isPasswordLengthValid,
  PASSWORD_POLICY,
  UserRole,
  type UserRole as UserRoleType,
} from "@wecheck/domain";
import type { ErrorDetail } from "../../errors/api-error.js";
import type { CreateUserInput, LoginInput, UpdateUserInput } from "./types.js";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const INSTITUTIONAL_ID_RE = /^[A-Za-z0-9-]{3,32}$/;
const USER_ROLES = new Set<string>(Object.values(UserRole));

export interface ValidationResult<T> {
  ok: true;
  value: T;
}

export interface ValidationFailure {
  ok: false;
  details: ErrorDetail[];
}

export type ParseResult<T> = ValidationResult<T> | ValidationFailure;

function fail(field: string, code: string, message: string): ValidationFailure {
  return { ok: false, details: [{ field, code, message }] };
}

function mergeFailures(...failures: ValidationFailure[]): ValidationFailure {
  return {
    ok: false,
    details: failures.flatMap((f) => f.details),
  };
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function validateEmail(email: unknown): ParseResult<string> {
  if (typeof email !== "string" || !email.trim()) {
    return fail("email", ErrorCode.InvalidEmail, "Email không hợp lệ");
  }
  const normalized = normalizeEmail(email);
  if (normalized.length > 254 || !EMAIL_RE.test(normalized)) {
    return fail("email", ErrorCode.InvalidEmail, "Email không hợp lệ");
  }
  return { ok: true, value: normalized };
}

export function validatePassword(
  password: unknown,
  field = "password",
  required = true,
): ParseResult<string | undefined> {
  if (password === undefined || password === null || password === "") {
    if (!required) {
      return { ok: true, value: undefined };
    }
    return fail(field, ErrorCode.PasswordTooShort, "Mật khẩu phải có ít nhất 8 ký tự");
  }
  if (typeof password !== "string") {
    return fail(field, ErrorCode.PasswordTooShort, "Mật khẩu phải có ít nhất 8 ký tự");
  }
  if (!isPasswordLengthValid(password.length)) {
    if (password.length < PASSWORD_POLICY.MIN_LENGTH) {
      return fail(field, ErrorCode.PasswordTooShort, "Mật khẩu phải có ít nhất 8 ký tự");
    }
    return fail(field, ErrorCode.InvalidLength, "Độ dài dữ liệu không hợp lệ");
  }
  return { ok: true, value: password };
}

export function validateDisplayName(displayName: unknown): ParseResult<string> {
  if (typeof displayName !== "string") {
    return fail("displayName", ErrorCode.InvalidLength, "Độ dài dữ liệu không hợp lệ");
  }
  const trimmed = displayName.trim();
  if (trimmed.length < 1 || trimmed.length > 200) {
    return fail("displayName", ErrorCode.InvalidLength, "Độ dài dữ liệu không hợp lệ");
  }
  return { ok: true, value: trimmed };
}

export function validateInstitutionalId(
  institutionalId: unknown,
): ParseResult<string> {
  if (typeof institutionalId !== "string") {
    return fail(
      "institutionalId",
      ErrorCode.InvalidInstitutionalId,
      "Mã định danh không hợp lệ",
    );
  }
  const trimmed = institutionalId.trim();
  if (!INSTITUTIONAL_ID_RE.test(trimmed)) {
    return fail(
      "institutionalId",
      ErrorCode.InvalidInstitutionalId,
      "Mã định danh không hợp lệ",
    );
  }
  return { ok: true, value: trimmed };
}

export function validateRole(role: unknown): ParseResult<UserRoleType> {
  if (typeof role !== "string" || !USER_ROLES.has(role)) {
    return fail("role", ErrorCode.InvalidEnum, "Giá trị enum không hợp lệ");
  }
  return { ok: true, value: role as UserRoleType };
}

export function validateReturnUrl(returnUrl: unknown): ParseResult<string | undefined> {
  if (returnUrl === undefined || returnUrl === null || returnUrl === "") {
    return { ok: true, value: undefined };
  }
  if (typeof returnUrl !== "string") {
    return fail("returnUrl", ErrorCode.InvalidReturnUrl, "Đường dẫn quay lại không hợp lệ");
  }
  if (
    !returnUrl.startsWith("/") ||
    returnUrl.startsWith("//") ||
    returnUrl.length > 512
  ) {
    return fail("returnUrl", ErrorCode.InvalidReturnUrl, "Đường dẫn quay lại không hợp lệ");
  }
  return { ok: true, value: returnUrl };
}

export function validateLoginBody(body: unknown): ParseResult<LoginInput> {
  if (!body || typeof body !== "object") {
    return fail("email", ErrorCode.InvalidEmail, "Email không hợp lệ");
  }
  const raw = body as Record<string, unknown>;
  const email = validateEmail(raw.email);
  if (!email.ok) {
    return email;
  }
  if (typeof raw.password !== "string" || !raw.password) {
    return fail("password", ErrorCode.InvalidCredentials, "Email hoặc mật khẩu không đúng");
  }
  const returnUrl = validateReturnUrl(raw.returnUrl);
  if (!returnUrl.ok) {
    return returnUrl;
  }
  return {
    ok: true,
    value: {
      email: email.value,
      password: raw.password,
      returnUrl: returnUrl.value,
    },
  };
}

export function validateCreateUserBody(body: unknown): ParseResult<CreateUserInput> {
  if (!body || typeof body !== "object") {
    return fail("institutionalId", ErrorCode.ValidationFailed, "Dữ liệu không hợp lệ");
  }
  const raw = body as Record<string, unknown>;
  const institutionalId = validateInstitutionalId(raw.institutionalId);
  const displayName = validateDisplayName(raw.displayName);
  const email = validateEmail(raw.email);
  const password = validatePassword(raw.password, "password", true);
  const role = validateRole(raw.role);

  const failures: ValidationFailure[] = [];
  if (!institutionalId.ok) failures.push(institutionalId);
  if (!displayName.ok) failures.push(displayName);
  if (!email.ok) failures.push(email);
  if (!password.ok) failures.push(password);
  if (!role.ok) failures.push(role);
  if (failures.length > 0) {
    return mergeFailures(...failures);
  }

  if (
    !institutionalId.ok ||
    !displayName.ok ||
    !email.ok ||
    !password.ok ||
    !role.ok ||
    password.value === undefined
  ) {
    return fail("institutionalId", ErrorCode.ValidationFailed, "Dữ liệu không hợp lệ");
  }

  const active =
    raw.active === undefined ? true : raw.active === true || raw.active === false
      ? raw.active
      : undefined;
  if (active === undefined) {
    return fail("active", ErrorCode.InvalidEnum, "Giá trị enum không hợp lệ");
  }

  return {
    ok: true,
    value: {
      institutionalId: institutionalId.value,
      displayName: displayName.value,
      email: email.value,
      password: password.value,
      role: role.value,
      active,
    },
  };
}

export function validateUpdateUserBody(body: unknown): ParseResult<UpdateUserInput> {
  if (!body || typeof body !== "object") {
    return fail("displayName", ErrorCode.ValidationFailed, "Dữ liệu không hợp lệ");
  }
  const raw = body as Record<string, unknown>;
  const input: UpdateUserInput = {};
  const failures: ValidationFailure[] = [];

  if (raw.institutionalId !== undefined) {
    const result = validateInstitutionalId(raw.institutionalId);
    if (!result.ok) failures.push(result);
    else input.institutionalId = result.value;
  }
  if (raw.displayName !== undefined) {
    const result = validateDisplayName(raw.displayName);
    if (!result.ok) failures.push(result);
    else input.displayName = result.value;
  }
  if (raw.email !== undefined) {
    const result = validateEmail(raw.email);
    if (!result.ok) failures.push(result);
    else input.email = result.value;
  }
  if (raw.password !== undefined) {
    const result = validatePassword(raw.password, "password", true);
    if (!result.ok) failures.push(result);
    else input.password = result.value;
  }
  if (raw.role !== undefined) {
    const result = validateRole(raw.role);
    if (!result.ok) failures.push(result);
    else input.role = result.value;
  }
  if (raw.active !== undefined) {
    if (raw.active !== true && raw.active !== false) {
      failures.push(fail("active", ErrorCode.InvalidEnum, "Giá trị enum không hợp lệ"));
    } else {
      input.active = raw.active;
    }
  }

  if (failures.length > 0) {
    return mergeFailures(...failures);
  }
  if (Object.keys(input).length === 0) {
    return fail("displayName", ErrorCode.ValidationFailed, "Dữ liệu không hợp lệ");
  }
  return { ok: true, value: input };
}

export function validateListUsersQuery(query: Record<string, unknown>): ParseResult<{
  role?: UserRoleType;
  active?: boolean;
  search?: string;
  limit: number;
  cursor?: string;
}> {
  const failures: ValidationFailure[] = [];
  let role: UserRoleType | undefined;
  let active: boolean | undefined;
  let search: string | undefined;
  let limit = 50;
  let cursor: string | undefined;

  if (query.role !== undefined) {
    const result = validateRole(query.role);
    if (!result.ok) failures.push(result);
    else role = result.value;
  }
  if (query.active !== undefined) {
    if (query.active === "true") active = true;
    else if (query.active === "false") active = false;
    else failures.push(fail("active", ErrorCode.InvalidEnum, "Giá trị enum không hợp lệ"));
  }
  if (query.search !== undefined) {
    if (typeof query.search !== "string" || query.search.length > 200) {
      failures.push(fail("search", ErrorCode.InvalidLength, "Độ dài dữ liệu không hợp lệ"));
    } else {
      search = query.search.trim() || undefined;
    }
  }
  if (query.limit !== undefined) {
    const parsed = Number.parseInt(String(query.limit), 10);
    if (Number.isNaN(parsed) || parsed < 1 || parsed > 200) {
      failures.push(fail("limit", ErrorCode.InvalidPagination, "Tham số phân trang không hợp lệ"));
    } else {
      limit = parsed;
    }
  }
  if (query.cursor !== undefined) {
    if (query.cursor === "null" || query.cursor === "") {
      cursor = undefined;
    } else if (typeof query.cursor !== "string") {
      failures.push(fail("cursor", ErrorCode.InvalidPagination, "Tham số phân trang không hợp lệ"));
    } else {
      cursor = query.cursor;
    }
  }

  if (failures.length > 0) {
    return mergeFailures(...failures);
  }
  return { ok: true, value: { role, active, search, limit, cursor } };
}

export function validateSessionInactivityHours(
  body: unknown,
): ParseResult<{ inactivityHours: number }> {
  if (!body || typeof body !== "object") {
    return fail(
      "inactivityHours",
      ErrorCode.ValidationFailed,
      "Dữ liệu không hợp lệ",
    );
  }
  const raw = (body as Record<string, unknown>).inactivityHours;
  const parsed =
    typeof raw === "number" ? raw : Number.parseInt(String(raw ?? ""), 10);
  if (
    Number.isNaN(parsed) ||
    parsed < 4 ||
    parsed > 12 ||
    !Number.isInteger(parsed)
  ) {
    return fail(
      "inactivityHours",
      ErrorCode.ValidationFailed,
      "Giá trị phải từ 4 đến 12 giờ",
    );
  }
  return { ok: true, value: { inactivityHours: parsed } };
}
