"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type {
  ManualAttendanceStatus,
  RosterEntry,
} from "@/domain/manual-attendance";

const statusOptions: Array<{
  value: ManualAttendanceStatus;
  label: string;
}> = [
  { value: "manual_present", label: "Manual Present" },
  { value: "late", label: "Late" },
  { value: "absent", label: "Absent" },
  { value: "excused", label: "Excused" },
];

const statusLabels: Record<string, string> = {
  present: "Present",
  manual_present: "Manual Present",
  late: "Late",
  absent: "Absent",
  excused: "Excused",
};

const errorMessages: Record<string, string> = {
  invalid_request: "Choose a valid status.",
  invalid_reason: "A reason is required.",
  forbidden: "You are not allowed to change this session.",
  not_owner: "You do not own this class section.",
  not_enrolled: "That student is not enrolled in this section.",
  session_not_found: "Session not found.",
};

export function ManualAttendancePanel({
  classSessionId,
  roster,
}: {
  classSessionId: string;
  roster: RosterEntry[];
}) {
  const router = useRouter();
  const [pendingId, setPendingId] = useState("");
  const [closing, setClosing] = useState(false);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [statuses, setStatuses] = useState<
    Record<string, ManualAttendanceStatus>
  >({});
  const [message, setMessage] = useState("");

  async function setAttendance(studentId: string) {
    const reason = (reasons[studentId] ?? "").trim();
    const status = statuses[studentId] ?? "manual_present";
    if (!reason) {
      setMessage(errorMessages.invalid_reason);
      return;
    }

    setPendingId(studentId);
    setMessage("");
    try {
      const response = await fetch(
        `/api/sessions/${encodeURIComponent(classSessionId)}/manual`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ studentId, status, reason }),
        },
      );
      if (response.status === 401) {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname)}`,
        );
        return;
      }
      if (!response.ok) {
        const body = (await response.json()) as { error?: string };
        setMessage(
          errorMessages[body.error ?? ""] ?? "Could not update attendance.",
        );
        return;
      }
      setMessage(`Marked ${statusLabels[status]}.`);
      router.refresh();
    } catch {
      setMessage("Network error. Please try again.");
    } finally {
      setPendingId("");
    }
  }

  async function close() {
    setClosing(true);
    setMessage("");
    try {
      const response = await fetch(
        `/api/sessions/${encodeURIComponent(classSessionId)}/close`,
        { method: "POST" },
      );
      if (response.status === 401) {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname)}`,
        );
        return;
      }
      const body = (await response.json()) as {
        absentCount?: number;
        error?: string;
      };
      if (!response.ok) {
        setMessage(
          errorMessages[body.error ?? ""] ?? "Could not close attendance.",
        );
        return;
      }
      setMessage(
        `Attendance closed. ${body.absentCount ?? 0} student(s) marked Absent.`,
      );
      router.refresh();
    } catch {
      setMessage("Network error. Please try again.");
    } finally {
      setClosing(false);
    }
  }

  return (
    <section>
      <h2>Attendance controls</h2>
      <button type="button" onClick={close} disabled={closing}>
        {closing ? "Closing attendance…" : "Close attendance"}
      </button>
      {message ? (
        <p role="status" aria-live="polite">
          {message}
        </p>
      ) : null}
      <h3>Roster</h3>
      {roster.length ? (
        <ul>
          {roster.map((entry) => (
            <li key={entry.studentId}>
              <span>
                {entry.name} —{" "}
                {entry.status
                  ? (statusLabels[entry.status] ?? entry.status)
                  : "Not checked in"}
              </span>
              <select
                aria-label={`Status for ${entry.name}`}
                value={statuses[entry.studentId] ?? "manual_present"}
                onChange={(event) =>
                  setStatuses((prev) => ({
                    ...prev,
                    [entry.studentId]: event.target
                      .value as ManualAttendanceStatus,
                  }))
                }
              >
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <input
                aria-label={`Reason for ${entry.name}`}
                placeholder="Reason"
                value={reasons[entry.studentId] ?? ""}
                onChange={(event) =>
                  setReasons((prev) => ({
                    ...prev,
                    [entry.studentId]: event.target.value,
                  }))
                }
              />
              <button
                type="button"
                onClick={() => setAttendance(entry.studentId)}
                disabled={pendingId === entry.studentId}
              >
                {pendingId === entry.studentId ? "Saving…" : "Set status"}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p>No enrolled students.</p>
      )}
    </section>
  );
}
