"use client";

import Image from "next/image";
import QRCode from "qrcode";
import { useCallback, useEffect, useState } from "react";

type QrState = {
  token: string;
  expiresAt: string;
  checkInUrl: string;
  imageUrl: string;
};

export function QrDisplay({ classSessionId }: { classSessionId: string }) {
  const [qr, setQr] = useState<QrState | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const requestQr = useCallback(
    async (method: "GET" | "POST") => {
      const suffix = method === "POST" ? "open" : "qr";
      const response = await fetch(
        `/api/sessions/${encodeURIComponent(classSessionId)}/${suffix}`,
        { method },
      );
      if (response.status === 401) {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname)}`,
        );
        return;
      }
      const body = (await response.json()) as {
        token?: string;
        expiresAt?: string;
        error?: string;
      };
      if (!response.ok || !body.token || !body.expiresAt) {
        throw new Error(body.error ?? "Unable to load QR");
      }

      const url = new URL("/check-in", window.location.origin);
      url.searchParams.set("session", classSessionId);
      url.searchParams.set("token", body.token);
      const checkInUrl = url.toString();
      const imageUrl = await QRCode.toDataURL(checkInUrl, {
        errorCorrectionLevel: "M",
        margin: 2,
        width: 320,
      });
      setQr({
        token: body.token,
        expiresAt: body.expiresAt,
        checkInUrl,
        imageUrl,
      });
      setError("");
    },
    [classSessionId],
  );

  async function open() {
    try {
      await requestQr("POST");
      setRunning(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to open attendance");
    }
  }

  useEffect(() => {
    if (!running) return;
    const interval = window.setInterval(() => {
      requestQr("GET").catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : "Unable to refresh QR");
      });
    }, 1_000);
    return () => window.clearInterval(interval);
  }, [requestQr, running]);

  return (
    <section>
      <button type="button" onClick={open} disabled={running}>
        {running ? "Attendance open" : "Open attendance"}
      </button>
      {error ? <p role="alert">{error}</p> : null}
      {qr ? (
        <div>
          <Image
            src={qr.imageUrl}
            width={320}
            height={320}
            unoptimized
            alt="Scan to check in"
            priority
          />
          <p>
            QR expires at <time>{new Date(qr.expiresAt).toLocaleTimeString()}</time>
          </p>
          <details>
            <summary>Manual check-in link</summary>
            <a href={qr.checkInUrl}>{qr.checkInUrl}</a>
          </details>
        </div>
      ) : null}
    </section>
  );
}
