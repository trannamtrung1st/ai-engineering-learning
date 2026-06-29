import type { UserRole } from "@wecheck/domain";

export interface UserRecord {
  id: string;
  institutionalId: string;
  displayName: string;
  email: string;
  passwordHash: string;
  role: UserRole;
  active: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface UserDto {
  id: string;
  institutionalId: string;
  displayName: string;
  email: string;
  role: UserRole;
  active: boolean;
  createdAt: string;
}

export interface CreateUserInput {
  institutionalId: string;
  displayName: string;
  email: string;
  password: string;
  role: UserRole;
  active?: boolean;
}

export interface UpdateUserInput {
  institutionalId?: string;
  displayName?: string;
  email?: string;
  password?: string;
  role?: UserRole;
  active?: boolean;
}

export interface LoginInput {
  email: string;
  password: string;
  returnUrl?: string;
}

export function toUserDto(user: UserRecord): UserDto {
  return {
    id: user.id,
    institutionalId: user.institutionalId,
    displayName: user.displayName,
    email: user.email,
    role: user.role,
    active: user.active,
    createdAt: user.createdAt.toISOString(),
  };
}
