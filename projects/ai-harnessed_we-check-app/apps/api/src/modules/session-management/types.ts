import type { SessionStatus } from "@wecheck/domain";

export interface SessionRecord {
  id: string;
  instructorId: string;
  classId: string;
  subjectId: string;
  title: string;
  roomName: string;
  roomLatitude: number | null;
  roomLongitude: number | null;
  gpsRadiusMeters: number;
  scheduledStart: Date;
  status: SessionStatus;
  openedAt: Date | null;
  closedAt: Date | null;
  version: number;
  createdAt: Date;
  updatedAt: Date;
}

export interface SessionDto {
  id: string;
  instructorId: string;
  classId: string;
  subjectId: string;
  title: string;
  roomName: string;
  roomLatitude: number | null;
  roomLongitude: number | null;
  gpsRadiusMeters: number;
  scheduledStart: string;
  status: SessionStatus;
  openedAt: string | null;
  closedAt: string | null;
  enrollmentCount?: number;
}

export interface CreateSessionInput {
  classId: string;
  subjectId: string;
  title: string;
  roomName: string;
  roomLatitude?: number | null;
  roomLongitude?: number | null;
  gpsRadiusMeters?: number;
  scheduledStart: string;
}

export interface PatchSessionInput {
  title?: string;
  roomName?: string;
  roomLatitude?: number | null;
  roomLongitude?: number | null;
  gpsRadiusMeters?: number;
  scheduledStart?: string;
}

export interface AttendanceSummary {
  enrolled: number;
  pending: number;
  present: number;
  absent: number;
  excused: number;
  rejected: number;
}

export interface AttendanceRecordDto {
  id: string;
  studentId: string;
  institutionalId: string;
  displayName: string;
  status: string;
  checkedInAt: string | null;
  /** Latest SpoofSuspected check-in attempt for monitor badge (AC-10, FR-10) */
  spoofSuspected?: boolean;
}

export interface SessionMonitorAlerts {
  codeSharing: boolean;
}

export interface SessionAttendanceResponse {
  summary: AttendanceSummary;
  records: AttendanceRecordDto[];
  alerts: SessionMonitorAlerts;
}

export interface QrTokenDisplayDto {
  sessionId: string;
  tokenId: string;
  qrPayload: string;
  issuedAt: string;
  expiresAt: string;
  secondsRemaining: number;
  attendanceWindowClosesAt: string;
}
