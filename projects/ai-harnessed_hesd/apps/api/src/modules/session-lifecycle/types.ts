export type SessionState = "Scheduled" | "Open" | "Closed" | "Cancelled";

export interface ClassSessionRow {
  id: string;
  classSectionId: string;
  roomId: string | null;
  scheduledStartAt: string;
  scheduledEndAt: string;
  state: SessionState;
  openedAt: string | null;
  openedByUserId: string | null;
  closedAt: string | null;
  closedByUserId: string | null;
}

export interface QrPreview {
  expiresAt: string;
  qrPayload: string;
}

export interface OpenSessionResult {
  classSessionId: string;
  state: "Open";
  openedAt: string;
  qr: QrPreview;
}

export interface CloseSummary {
  present: number;
  late: number;
  manualPresent: number;
  absent: number;
}

export interface CloseSessionResult {
  classSessionId: string;
  state: "Closed";
  closedAt: string;
  summary: CloseSummary;
}
