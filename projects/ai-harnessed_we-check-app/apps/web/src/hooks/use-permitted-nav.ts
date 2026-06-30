import { UserRole } from "@wecheck/domain";
import { useAuthUser } from "@/components/auth/require-auth";
import {
  filterHubCards,
  filterPermittedNav,
  getRolePermissions,
  type HubCardDescriptor,
  type NavDescriptor,
  type NavLayout,
  type Permission,
} from "@/lib/permissions";

export function usePermittedNav(layout: NavLayout): NavDescriptor[] {
  const user = useAuthUser();
  const permissions = getRolePermissions(user.role);
  return filterPermittedNav(layout, permissions);
}

export function usePermittedHubCards(variant: NavLayout): HubCardDescriptor[] {
  const user = useAuthUser();
  const permissions = getRolePermissions(user.role);
  return filterHubCards(variant, permissions);
}

/** Integration-test boundary: explicit permission set without auth context */
export function resolvePermittedNav(
  layout: NavLayout,
  permissions: readonly Permission[],
): NavDescriptor[] {
  return filterPermittedNav(layout, permissions);
}

export function resolveHubCards(
  variant: NavLayout,
  permissions: readonly Permission[],
): HubCardDescriptor[] {
  return filterHubCards(variant, permissions);
}

export function layoutForRole(role: (typeof UserRole)[keyof typeof UserRole]): NavLayout {
  switch (role) {
    case UserRole.Student:
      return "student";
    case UserRole.Instructor:
      return "instructor";
    case UserRole.TrainingOfficeAdmin:
      return "admin";
    default:
      return "student";
  }
}
