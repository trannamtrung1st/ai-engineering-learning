"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { RosterEntry } from "@/domain/manual-attendance";

const errorMessages: Record<string, string> = {
  invalid_reason: "A reason is required.",
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
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");

  async function markPresent(studentId: string) {
    const reason = (reasons[studentId] ?? "").trim();
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
          body: JSON.stringify({ studentId, reason }),
        },
      );
      if (!response.ok) {
        const body = (await response.json()) as { error?: string };
        setMessage(errorMessages[body.error ?? ""] ?? "Could not mark present.");
        return;
      }
      setMessage("Marked Manual Present.");
      router.refresh();
    } catch {
      setMessage("Network error. Please try again.");
    } finally {
      setPendingId("");
    }
  }

  if (!roster.length) return null;

  return (
    <section>
      <h2>Manual fallback</h2>
      {message ? (
        <p role="status" aria-live="polite">
          {message}
        </p>
      ) : null}
      <ul>
        {roster.map((entry) => (
          <li key={entry.studentId}>
            <span>
              {entry.name} — {entry.status ?? "not checked in"}
            </span>
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
              onClick={() => markPresent(entry.studentId)}
              disabled={pendingId === entry.studentId}
            >
              Mark Present
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
