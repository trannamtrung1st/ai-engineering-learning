/** Canonical UI role identifiers — align with layout templates in docs/ui-ux/06-app-layout-components.md */
export type AppRole = "participant" | "organizer-admin" | "organizer-staff";

export interface UserContext {
  displayName: string;
  role: AppRole;
  organization?: string;
}

export interface NavItem {
  href: string;
  label: string;
  roles: AppRole[];
}

export const organizerNavItems: NavItem[] = [
  {
    href: "/organizer/events",
    label: "Events",
    roles: ["organizer-admin", "organizer-staff"],
  },
  {
    href: "/organizer/check-in",
    label: "Check-in",
    roles: ["organizer-admin", "organizer-staff"],
  },
  {
    href: "/organizer/audit",
    label: "Audit log",
    roles: ["organizer-admin"],
  },
];

export function roleLabel(role: AppRole): string {
  switch (role) {
    case "participant":
      return "Participant";
    case "organizer-admin":
      return "Organizer Admin";
    case "organizer-staff":
      return "Organizer Staff";
  }
}
