import type { ActorRole } from "@we-event/domain";
import { ApiError } from "../../errors/api-error.js";
import type { UserRoleRow } from "../user/types.js";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_PASSWORD_LENGTH = 8;
const MAX_DISPLAY_NAME_LENGTH = 120;
const MAX_EMAIL_LENGTH = 254;

export interface RegisterInput {
  email: string;
  password: string;
  displayName: string;
}

export interface LoginInput {
  email: string;
  password: string;
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function validateRegisterInput(input: RegisterInput): RegisterInput {
  const email = normalizeEmail(input.email);
  const password = input.password;
  const displayName = input.displayName?.trim() ?? "";

  if (!email || !EMAIL_PATTERN.test(email) || email.length > MAX_EMAIL_LENGTH) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "A valid email address is required.",
      statusCode: 400,
      details: { field: "email" },
    });
  }

  if (!password || password.length < MIN_PASSWORD_LENGTH) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`,
      statusCode: 400,
      details: { field: "password", minLength: MIN_PASSWORD_LENGTH },
    });
  }

  if (!displayName || displayName.length > MAX_DISPLAY_NAME_LENGTH) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "Display name is required.",
      statusCode: 400,
      details: { field: "displayName", maxLength: MAX_DISPLAY_NAME_LENGTH },
    });
  }

  return { email, password, displayName };
}

export function validateLoginInput(input: LoginInput): LoginInput {
  const email = normalizeEmail(input.email);
  const password = input.password;

  if (!email || !EMAIL_PATTERN.test(email)) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "A valid email address is required.",
      statusCode: 400,
      details: { field: "email" },
    });
  }

  if (!password) {
    throw new ApiError({
      code: "INVALID_INPUT",
      message: "Password is required.",
      statusCode: 400,
      details: { field: "password" },
    });
  }

  return { email, password };
}

export function selectJwtRole(roles: UserRoleRow[]): {
  role: ActorRole;
  assignedEventIds: string[];
} {
  const admin = roles.find((entry) => entry.role === "OrganizerAdmin");
  if (admin) {
    return { role: "OrganizerAdmin", assignedEventIds: [] };
  }

  const staff = roles.find((entry) => entry.role === "OrganizerStaff");
  if (staff) {
    return {
      role: "OrganizerStaff",
      assignedEventIds: staff.assignedEventIds,
    };
  }

  return { role: "Participant", assignedEventIds: [] };
}
