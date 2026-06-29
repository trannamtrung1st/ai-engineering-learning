import { useCallback, useEffect, useState } from "react";
import { Camera } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { parseCheckInQrPayload } from "@/lib/qr-deeplink";
import { PREVIEW_SESSION_IDS, PREVIEW_TOKEN_IDS } from "@/lib/preview-fixtures";
import { readCameraSimMode } from "@/lib/preview-sim";

export interface QrScannerViewProps {
  onScan?: (token: string) => void;
  onCameraDenied?: () => void;
  onOpenCameraGuide?: () => void;
  disabled?: boolean;
  /** When false, getUserMedia is not invoked (NFR-19 camera consent) */
  cameraConsented?: boolean;
}

/** Student QR scanner — camera viewfinder per ui-ux §2.1 (FR-07, NFR-18) */
export function QrScannerView({
  onScan,
  onCameraDenied,
  onOpenCameraGuide,
  disabled,
  cameraConsented = true,
}: QrScannerViewProps) {
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraDenied, setCameraDenied] = useState(false);

  useEffect(() => {
    if (!cameraConsented) {
      setCameraReady(false);
      setCameraDenied(false);
      return;
    }

    if (readCameraSimMode() === "deny") {
      setCameraDenied(true);
      onCameraDenied?.();
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraDenied(true);
      onCameraDenied?.();
      return;
    }

    let cancelled = false;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then((stream) => {
        if (cancelled) return;
        setCameraReady(true);
        setCameraDenied(false);
        for (const track of stream.getTracks()) {
          track.stop();
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCameraDenied(true);
          onCameraDenied?.();
        }
      });

    return () => {
      cancelled = true;
    };
  }, [cameraConsented, onCameraDenied]);

  const simulateScan = useCallback(() => {
    const payload = `wecheck://check-in?token=${PREVIEW_TOKEN_IDS.valid}&session=${PREVIEW_SESSION_IDS.active}`;
    onScan?.(payload);
  }, [onScan]);

  const handleManualPayload = useCallback(
    (payload: string) => {
      const parsed = parseCheckInQrPayload(payload);
      if (parsed) {
        onScan?.(payload);
        return;
      }
      onScan?.(payload);
    },
    [onScan],
  );

  return (
    <div
      data-testid="qr-scanner-view"
      className="flex flex-col items-center gap-4"
    >
      {cameraDenied ? (
        <div className="w-full max-w-sm" data-testid="camera-denied-alert">
          <Alert variant="danger" title="Không thể mở camera">
            Vui lòng cấp quyền camera để quét mã QR hoặc dán liên kết QR bên dưới.
          </Alert>
          <Button
            type="button"
            className="mt-3 w-full min-h-touch"
            onClick={onOpenCameraGuide}
            data-testid="camera-permission-guide-cta"
          >
            Hướng dẫn cấp quyền
          </Button>
          <p
            className="mt-3 text-small text-text-secondary"
            data-testid="manual-attendance-fallback"
          >
            Nếu vẫn không điểm danh được, vui lòng liên hệ giảng viên để được ghi nhận thủ công.
          </p>
        </div>
      ) : null}

      <div
        className="flex aspect-square w-full max-w-sm items-center justify-center rounded-lg border-2 border-dashed border-primary-500 bg-surface-raised"
        aria-hidden="true"
        data-testid={cameraReady ? "camera-ready" : "camera-loading"}
      >
        <Camera className="h-16 w-16 text-text-secondary" />
      </div>
      <p className="text-body text-text-secondary">
        {!cameraConsented
          ? "Vui lòng đồng ý sử dụng camera trước khi quét"
          : cameraDenied
            ? "Camera bị từ chối — xem hướng dẫn cấp quyền"
            : cameraReady
              ? "Đưa mã QR vào khung"
              : "Đang mở camera…"}
      </p>
      <Button
        type="button"
        disabled={disabled || !cameraConsented}
        onClick={simulateScan}
        aria-label="Quét mã QR"
        className="min-h-touch w-full max-w-sm"
      >
        Quét mã QR
      </Button>
      <label className="w-full max-w-sm text-small text-text-secondary">
        Hoặc dán liên kết QR
        <input
          type="text"
          className="mt-1 w-full min-h-touch rounded-md border border-border bg-surface px-3 py-2 text-body"
          placeholder="wecheck://check-in?token=…"
          disabled={disabled}
          data-testid="qr-manual-input"
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              handleManualPayload((event.target as HTMLInputElement).value);
            }
          }}
        />
      </label>
    </div>
  );
}
