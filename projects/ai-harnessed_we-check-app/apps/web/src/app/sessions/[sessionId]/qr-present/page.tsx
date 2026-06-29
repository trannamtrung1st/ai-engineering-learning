import { useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { QrFullscreenPresentation } from "@/components/instructor/qr-fullscreen-presentation";
import { resolvePreviewId } from "@/lib/preview-fixtures";

/** AC-06 / NFR-20 — fullscreen QR presenter route at /sessions/:sessionId/qr-present */
export function QrPresentPage() {
  const { sessionId: routeId } = useParams<{ sessionId: string }>();
  const sessionId = resolvePreviewId(routeId) ?? routeId;
  const navigate = useNavigate();

  const handleExit = useCallback(() => {
    if (sessionId) {
      navigate(`/sessions/${sessionId}?tab=qr`);
      return;
    }
    navigate(-1);
  }, [sessionId, navigate]);

  if (!sessionId) {
    return null;
  }

  return <QrFullscreenPresentation sessionId={sessionId} onExit={handleExit} />;
}
