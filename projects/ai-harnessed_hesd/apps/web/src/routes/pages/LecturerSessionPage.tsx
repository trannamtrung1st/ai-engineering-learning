import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { QrDisplayPanel, type QrDisplayData } from "../../components/domain/QrDisplayPanel";
import { SessionControlBar } from "../../components/domain/SessionControlBar";
import { TTL_SECONDS } from "../../components/domain/QrCountdownRing";
import { ContentSection } from "../../components/layout/ContentSection";
import type { SessionState } from "../../components/ui/StatusBadge";
import styles from "./LecturerSessionPage.module.css";

function buildToken(seed: number): QrDisplayData {
  const expiresAt = new Date(Date.now() + TTL_SECONDS * 1000).toISOString();
  return {
    qrPayload: `attendly://check-in/demo-${seed}`,
    expiresAt,
    tokenState: "Valid",
  };
}

export function LecturerSessionPage() {
  const { sessionId = "demo-open" } = useParams();
  const sessionState: SessionState = sessionId.includes("closed") ? "Closed" : "Open";
  const [rotation, setRotation] = useState(1);
  const [qrData, setQrData] = useState<QrDisplayData | null>(() =>
    sessionState === "Open" ? buildToken(1) : null,
  );

  const refreshQr = useCallback(() => {
    setRotation((value) => {
      const next = value + 1;
      setQrData(buildToken(next));
      return next;
    });
  }, []);

  useEffect(() => {
    if (sessionState !== "Open") {
      setQrData(null);
    }
  }, [sessionState]);

  const sectionCode = useMemo(() => "CSE101-A", []);
  const sessionName = useMemo(() => "Lập trình Web — Buổi 05", []);

  return (
    <div className={styles.page}>
      <SessionControlBar
        className={styles.controlBar}
        roomName="P.301"
        scheduledAt="Thứ 3 · 08:00"
        sessionState={sessionState}
      />

      <ContentSection title="Mã QR điểm danh" titleClassName={styles.sectionTitle}>
        <QrDisplayPanel
          sectionCode={sectionCode}
          sessionName={sessionName}
          sessionState={sessionState}
          qrData={qrData}
          projectionMode
          onRefresh={refreshQr}
          onExpire={refreshQr}
        />
        {sessionState === "Open" ? (
          <p className={styles.rotationMeta}>
            Token rotation #{rotation} · TTL {TTL_SECONDS}s · FR-14 / NFR-15
          </p>
        ) : null}
      </ContentSection>
    </div>
  );
}
