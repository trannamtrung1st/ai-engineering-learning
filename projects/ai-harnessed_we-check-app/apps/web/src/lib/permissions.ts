import { UserRole, type UserRole as UserRoleType } from "@wecheck/domain";

/** Permission vocabulary per docs/technical/01-roles-permissions.md §2.1 */
export const Permission = {
  UserRead: "user:read",
  UserWrite: "user:write",
  RosterRead: "roster:read",
  RosterWrite: "roster:write",
  SessionRead: "session:read",
  SessionWrite: "session:write",
  QrDisplay: "qr:display",
  CheckinSubmit: "checkin:submit",
  AttendanceRead: "attendance:read",
  AttendanceWrite: "attendance:write",
  ReportRead: "report:read",
  ReportExport: "report:export",
  AuditRead: "audit:read",
  NotificationRead: "notification:read",
  PolicyWrite: "policy:write",
} as const;

export type Permission = (typeof Permission)[keyof typeof Permission];

const ROLE_PERMISSIONS: Readonly<Record<UserRoleType, ReadonlySet<Permission>>> =
  {
    [UserRole.Student]: new Set([
      Permission.UserRead,
      Permission.CheckinSubmit,
      Permission.AttendanceRead,
      Permission.NotificationRead,
    ]),
    [UserRole.Instructor]: new Set([
      Permission.UserRead,
      Permission.RosterRead,
      Permission.SessionRead,
      Permission.SessionWrite,
      Permission.QrDisplay,
      Permission.AttendanceRead,
      Permission.AttendanceWrite,
      Permission.ReportRead,
      Permission.NotificationRead,
    ]),
    [UserRole.TrainingOfficeAdmin]: new Set([
      Permission.UserRead,
      Permission.UserWrite,
      Permission.RosterRead,
      Permission.RosterWrite,
      Permission.SessionRead,
      Permission.AttendanceRead,
      Permission.AttendanceWrite,
      Permission.ReportRead,
      Permission.ReportExport,
      Permission.AuditRead,
      Permission.NotificationRead,
      Permission.PolicyWrite,
    ]),
  };

export type NavLayout = "student" | "instructor" | "admin";

export interface NavDescriptor {
  to: string;
  label: string;
  permissions: readonly Permission[];
}

export interface HubCardDescriptor {
  to: string;
  title: string;
  description?: string;
  testId: string;
  permissions: readonly Permission[];
}

const STUDENT_NAV: NavDescriptor[] = [
  { to: "/check-in", label: "Điểm danh", permissions: [Permission.CheckinSubmit] },
  { to: "/history", label: "Lịch sử", permissions: [Permission.AttendanceRead] },
];

const INSTRUCTOR_NAV: NavDescriptor[] = [
  { to: "/sessions", label: "Buổi học", permissions: [Permission.SessionRead] },
  { to: "/reports", label: "Báo cáo", permissions: [Permission.ReportRead] },
];

const ADMIN_NAV: NavDescriptor[] = [
  {
    to: "/admin",
    label: "Trang chủ",
    permissions: [Permission.UserWrite],
  },
  {
    to: "/admin/users",
    label: "Người dùng",
    permissions: [Permission.UserWrite],
  },
  {
    to: "/admin/rosters",
    label: "Danh sách lớp",
    permissions: [Permission.RosterRead],
  },
  {
    to: "/admin/reports",
    label: "Báo cáo",
    permissions: [Permission.ReportRead],
  },
  {
    to: "/admin/export",
    label: "Xuất CSV",
    permissions: [Permission.ReportExport],
  },
  {
    to: "/admin/policy",
    label: "Chính sách",
    permissions: [Permission.PolicyWrite],
  },
];

export function getRolePermissions(role: UserRoleType): Permission[] {
  return [...(ROLE_PERMISSIONS[role] ?? [])];
}

export function hasPermission(
  permissions: readonly Permission[],
  required: Permission,
): boolean {
  return permissions.includes(required);
}

function hasAnyPermission(
  permissions: readonly Permission[],
  required: readonly Permission[],
): boolean {
  return required.some((permission) => permissions.includes(permission));
}

/** FR-18 / BR-14 — omit nav items the user lacks (not disabled) */
export function filterPermittedNav(
  layout: NavLayout,
  permissions: readonly Permission[],
): NavDescriptor[] {
  const catalog =
    layout === "student"
      ? STUDENT_NAV
      : layout === "instructor"
        ? INSTRUCTOR_NAV
        : ADMIN_NAV;

  return catalog.filter((item) => hasAnyPermission(permissions, item.permissions));
}

/** FR-18 / BR-14 — hub quick-link cards filtered by permission */
export function filterHubCards(
  variant: NavLayout,
  permissions: readonly Permission[],
): HubCardDescriptor[] {
  return HUB_CARD_CATALOG[variant].filter((card) =>
    hasAnyPermission(permissions, card.permissions),
  );
}

const HUB_CARD_CATALOG: Record<NavLayout, HubCardDescriptor[]> = {
  student: [
    {
      to: "/check-in",
      title: "Quét mã điểm danh",
      description: "Mở camera quét mã QR tại phòng học",
      testId: "student-hub-scan",
      permissions: [Permission.CheckinSubmit],
    },
    {
      to: "/history",
      title: "Xem lịch sử",
      description: "Theo dõi kết quả điểm danh các buổi học",
      testId: "student-hub-history",
      permissions: [Permission.AttendanceRead],
    },
  ],
  instructor: [
    {
      to: "/sessions/new",
      title: "Tạo buổi học mới",
      description: "Thiết lập buổi học và vị trí GPS",
      testId: "instructor-hub-create-session",
      permissions: [Permission.SessionWrite],
    },
    {
      to: "/reports",
      title: "Báo cáo điểm danh",
      description: "Xem báo cáo theo lớp được phân công",
      testId: "instructor-hub-reports",
      permissions: [Permission.ReportRead],
    },
  ],
  admin: [
    {
      to: "/admin/users",
      title: "Quản lý người dùng",
      description: "Thêm và chỉnh sửa tài khoản sinh viên, giảng viên, quản trị",
      testId: "admin-hub-users",
      permissions: [Permission.UserWrite],
    },
    {
      to: "/admin/rosters",
      title: "Danh sách lớp",
      description: "Xem danh sách lớp và sinh viên đã ghi danh",
      testId: "admin-hub-rosters",
      permissions: [Permission.RosterRead],
    },
    {
      to: "/admin/classes/new",
      title: "Thêm lớp/môn",
      description: "Tạo mã lớp và môn học trước khi nhập CSV",
      testId: "admin-hub-classes",
      permissions: [Permission.RosterWrite],
    },
    {
      to: "/admin/rosters/import",
      title: "Nhập CSV",
      description: "Nhập danh sách sinh viên theo lớp và môn",
      testId: "admin-hub-import",
      permissions: [Permission.RosterWrite],
    },
    {
      to: "/admin/reports",
      title: "Báo cáo",
      description: "Xem báo cáo điểm danh toàn trường",
      testId: "admin-hub-reports",
      permissions: [Permission.ReportRead],
    },
    {
      to: "/admin/export",
      title: "Xuất CSV",
      description: "Xuất dữ liệu điểm danh theo bộ lọc",
      testId: "admin-hub-export",
      permissions: [Permission.ReportExport],
    },
    {
      to: "/admin/policy",
      title: "Chính sách",
      description: "Cấu hình ngưỡng cảnh báo vắng mặt",
      testId: "admin-hub-policy",
      permissions: [Permission.PolicyWrite],
    },
  ],
};
