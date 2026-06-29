import {
  GPS_RADIUS_DEFAULT_METERS,
  SessionStatus,
} from "@wecheck/domain";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { SessionForm } from "@/components/instructor/session-form";

vi.mock("@/lib/reference-api", () => ({
  fetchClasses: vi.fn(),
  fetchSubjects: vi.fn(),
}));

vi.mock("@/lib/sessions-api", () => ({
  createSession: vi.fn(),
  openSession: vi.fn(),
  updateSession: vi.fn(),
}));

import { fetchClasses, fetchSubjects } from "@/lib/reference-api";
import { createSession, openSession, updateSession } from "@/lib/sessions-api";

const classId = "10000000-0000-4000-8000-000000000101";
const subjectId = "20000000-0000-4000-8000-000000000201";

/** FR-04 / AC-04 / BR-07 — session create form */
describe("SessionForm (FR-04, AC-04, BR-07)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchClasses).mockResolvedValue([
      { id: classId, code: "HESD-01", name: "HESD Cohort A", term: null },
    ]);
    vi.mocked(fetchSubjects).mockResolvedValue([
      { id: subjectId, code: "SWE-101", name: "Software Engineering 101" },
    ]);
  });

  it("TC-FR-04-016: renders form with default 100 m GPS radius", async () => {
    render(<SessionForm mode="create" />);

    await waitFor(() => {
      expect(screen.getByTestId("session-form")).toBeInTheDocument();
    });

    expect(screen.getByLabelText(/Bán kính GPS/)).toHaveValue(GPS_RADIUS_DEFAULT_METERS);
    expect(screen.getByTestId("gps-map-picker")).toBeInTheDocument();
  });

  it("TC-FR-04-016: Lưu nháp calls createSession with GPS coordinates", async () => {
    const onSaved = vi.fn();
    vi.mocked(createSession).mockResolvedValue({
      ok: true,
      data: {
        id: "new-session-id",
        instructorId: "inst",
        classId,
        subjectId,
        title: "Buổi 5",
        roomName: "Phòng A201",
        roomLatitude: 10.762622,
        roomLongitude: 106.660172,
        gpsRadiusMeters: 100,
        scheduledStart: "2026-06-30T08:00:00.000Z",
        status: SessionStatus.Draft,
        openedAt: null,
        closedAt: null,
      },
    });

    render(<SessionForm mode="create" onSaved={onSaved} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Tên buổi học/)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Tên buổi học/), {
      target: { value: "Buổi 5 — Kiến trúc" },
    });
    fireEvent.change(screen.getByLabelText(/Phòng học/), {
      target: { value: "Phòng A201" },
    });

    fireEvent.click(screen.getByTestId("session-save-draft"));

    await waitFor(() => {
      expect(createSession).toHaveBeenCalledWith(
        expect.objectContaining({
          classId,
          subjectId,
          title: "Buổi 5 — Kiến trúc",
          roomName: "Phòng A201",
          roomLatitude: 10.762622,
          roomLongitude: 106.660172,
          gpsRadiusMeters: 100,
        }),
      );
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it("TC-FR-04-017: Mở buổi học disabled when GPS coordinates cleared", async () => {
    render(<SessionForm mode="create" />);

    await waitFor(() => {
      expect(screen.getByTestId("session-save-and-open")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Vĩ độ/), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText(/Kinh độ/), { target: { value: "" } });

    expect(screen.getByTestId("session-save-and-open")).toBeDisabled();
  });

  it("TC-FR-04-016: Mở buổi học creates then opens session", async () => {
    const onOpened = vi.fn();
    vi.mocked(createSession).mockResolvedValue({
      ok: true,
      data: {
        id: "draft-id",
        instructorId: "inst",
        classId,
        subjectId,
        title: "Buổi mới",
        roomName: "A201",
        roomLatitude: 10.762622,
        roomLongitude: 106.660172,
        gpsRadiusMeters: 100,
        scheduledStart: "2026-06-30T08:00:00.000Z",
        status: SessionStatus.Draft,
        openedAt: null,
        closedAt: null,
      },
    });
    vi.mocked(openSession).mockResolvedValue({
      ok: true,
      data: {
        id: "draft-id",
        instructorId: "inst",
        classId,
        subjectId,
        title: "Buổi mới",
        roomName: "A201",
        roomLatitude: 10.762622,
        roomLongitude: 106.660172,
        gpsRadiusMeters: 100,
        scheduledStart: "2026-06-30T08:00:00.000Z",
        status: SessionStatus.Active,
        openedAt: "2026-06-29T08:00:00.000Z",
        closedAt: null,
      },
    });

    render(<SessionForm mode="create" onOpened={onOpened} />);

    await waitFor(() => {
      expect(screen.getByLabelText(/Tên buổi học/)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/Tên buổi học/), {
      target: { value: "Buổi mới" },
    });
    fireEvent.change(screen.getByLabelText(/Phòng học/), {
      target: { value: "A201" },
    });
    fireEvent.click(screen.getByTestId("session-save-and-open"));

    await waitFor(() => {
      expect(openSession).toHaveBeenCalledWith("draft-id");
    });
    expect(onOpened).toHaveBeenCalled();
  });

  it("TC-BR-07-016: edit mode saves GPS via PATCH on Lưu", async () => {
    const onSaved = vi.fn();
    const sessionId = "30000000-0000-4000-8000-000000000302";
    vi.mocked(updateSession).mockResolvedValue({
      ok: true,
      data: {
        id: sessionId,
        instructorId: "inst",
        classId,
        subjectId,
        title: "Buổi 5",
        roomName: "Phòng A201",
        roomLatitude: 10.762622,
        roomLongitude: 106.660172,
        gpsRadiusMeters: 100,
        scheduledStart: "2026-06-30T08:00:00.000Z",
        status: SessionStatus.Draft,
        openedAt: null,
        closedAt: null,
      },
    });

    render(
      <SessionForm
        mode="edit"
        session={{
          id: sessionId,
          instructorId: "inst",
          classId,
          subjectId,
          title: "Buổi 5",
          roomName: "Phòng A201",
          roomLatitude: null,
          roomLongitude: null,
          gpsRadiusMeters: 100,
          scheduledStart: "2026-06-30T08:00:00.000Z",
          status: SessionStatus.Draft,
          openedAt: null,
          closedAt: null,
        }}
        classCode="HESD-01"
        subjectCode="SWE-101"
        onSaved={onSaved}
      />,
    );

    expect(screen.getByTestId("gps-map-picker")).toBeInTheDocument();
    expect(screen.getByTestId("session-save-settings")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Vĩ độ/), {
      target: { value: "10.762622" },
    });
    fireEvent.change(screen.getByLabelText(/Kinh độ/), {
      target: { value: "106.660172" },
    });
    fireEvent.click(screen.getByTestId("session-save-settings"));

    await waitFor(() => {
      expect(updateSession).toHaveBeenCalledWith(
        sessionId,
        expect.objectContaining({
          roomLatitude: 10.762622,
          roomLongitude: 106.660172,
        }),
      );
    });
    expect(onSaved).toHaveBeenCalled();
  });
});
