"use client";

import { useState } from "react";
import type { FormEvent } from "react";

const rejectionMessages: Record<string, string> = {
  attendance_not_open: "Attendance is not open for this session.",
  invalid_token: "This QR code is invalid. Please scan the current code.",
  expired_token: "This QR code expired. Please scan the refreshed code.",
  wrong_session: "This QR code belongs to a different class session.",
  not_enrolled: "You are not enrolled in this class section.",
  outside_attendance_windows:
    "The check-in window has closed. Ask your lecturer to mark you manually.",
  already_checked_in: "You have already checked in for this session.",
  forbidden: "Only student accounts can use self check-in.",
};

export function CheckInForm({
  initialSessionId,
  initialToken,
}: {
  initialSessionId: string;
  initialToken: string;
}) {
  const [classSessionId, setClassSessionId] = useState(initialSessionId);
  const [token, setToken] = useState(initialToken);
  const [message, setMessage] = useState("");
  const [success, setSuccess] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setMessage("");

    try {
      const response = await fetch("/api/check-in", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ classSessionId, token }),
      });
      if (response.status === 401) {
        window.location.assign(
          `/login?next=${encodeURIComponent(
            `${window.location.pathname}${window.location.search}`,
          )}`,
        );
        return;
      }
      const body = (await response.json()) as {
        error?: string;
        status?: "present" | "late";
      };
      if (!response.ok) {
        setSuccess(false);
        setMessage(
          rejectionMessages[body.error ?? ""] ??
            "Check-in could not be completed. Please try again.",
        );
        return;
      }

      setSuccess(true);
      setMessage(
        `Check-in successful. You are marked ${
          body.status === "late" ? "Late" : "Present"
        }.`,
      );
    } catch {
      setSuccess(false);
      setMessage("Network error. Please try again or ask your lecturer for help.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <label>
        Session
        <input
          value={classSessionId}
          onChange={(event) => setClassSessionId(event.target.value)}
          required
        />
      </label>
      <label>
        QR token
        <input
          value={token}
          onChange={(event) => setToken(event.target.value)}
          required
        />
      </label>
      <button type="submit" disabled={submitting}>
        {submitting ? "Checking in…" : "Check in"}
      </button>
      {message ? (
        <p role="status" aria-live="polite" data-success={success}>
          {message}
        </p>
      ) : null}
    </form>
  );
}
