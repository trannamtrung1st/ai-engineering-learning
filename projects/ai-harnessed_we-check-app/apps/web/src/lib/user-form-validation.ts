import { UserRole, isPasswordLengthValid, type UserRole as UserRoleType } from "@wecheck/domain";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const INSTITUTIONAL_ID_RE = /^[A-Za-z0-9-]{3,32}$/;

export interface UserFormValues {
  institutionalId: string;
  displayName: string;
  email: string;
  password: string;
  role: UserRoleType | "";
}

export function validateUserForm(
  values: UserFormValues,
  options: { mode: "create" | "edit"; requirePassword?: boolean },
): Record<string, string> {
  const errors: Record<string, string> = {};

  const institutionalId = values.institutionalId.trim();
  if (!institutionalId) {
    errors.institutionalId = "Trường này là bắt buộc";
  } else if (!INSTITUTIONAL_ID_RE.test(institutionalId)) {
    errors.institutionalId = "Mã định danh không hợp lệ";
  }

  const displayName = values.displayName.trim();
  if (!displayName) {
    errors.displayName = "Trường này là bắt buộc";
  } else if (displayName.length < 2 || displayName.length > 100) {
    errors.displayName = "Tối thiểu 2 ký tự";
  }

  const email = values.email.trim();
  if (!email) {
    errors.email = "Trường này là bắt buộc";
  } else if (!EMAIL_RE.test(email)) {
    errors.email = "Email không hợp lệ";
  }

  if (options.mode === "create" || options.requirePassword) {
    if (!values.password) {
      errors.password = "Mật khẩu phải có ít nhất 8 ký tự";
    } else if (!isPasswordLengthValid(values.password.length)) {
      errors.password = "Mật khẩu phải có ít nhất 8 ký tự";
    }
  }

  if (!values.role || !Object.values(UserRole).includes(values.role as UserRoleType)) {
    errors.role = "Trường này là bắt buộc";
  }

  return errors;
}
