export const ATTENDANCE_STATUSES = [
  "Pending",
  "Present",
  "Late",
  "Absent",
  "Excused",
  "Manual Present",
] as const;

export type AttendanceStatus = (typeof ATTENDANCE_STATUSES)[number];

export const CORRECTABLE_STATUSES = [
  "Present",
  "Late",
  "Absent",
  "Excused",
  "Manual Present",
] as const;

export type CorrectableStatus = (typeof CORRECTABLE_STATUSES)[number];

export type CheckInMethod = "QR" | "Manual" | "Admin Correction" | null;

export interface RosterRow {
  studentUserId: string;
  studentCode: string;
  displayName: string;
  attendanceStatus: AttendanceStatus;
  checkInMethod: CheckInMethod;
  checkInAt: string | null;
  latestAttemptOutcome: string | null;
  atRisk?: boolean;
  unexcusedAbsenceRate?: number | null;
  absenceThresholdPercent?: number | null;
}

export interface RosterCounts {
  present: number;
  late: number;
  pending: number;
  absent: number;
  excused: number;
  manualPresent: number;
  rejectedAttempts: number;
}

export interface SessionRoster {
  classSessionId: string;
  state: string;
  counts: RosterCounts;
  rows: RosterRow[];
}

export interface CorrectionResult {
  classSessionId: string;
  studentUserId: string;
  attendanceStatus: AttendanceStatus;
  checkInMethod: CheckInMethod;
  checkInAt: string | null;
  previousStatus: AttendanceStatus | null;
  reason: string;
}

export interface EffectivePolicy {
  manualEditWindowHours: number;
  reasonRequired: boolean;
}
