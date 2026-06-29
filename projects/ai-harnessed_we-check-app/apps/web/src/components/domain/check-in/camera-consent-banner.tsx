import { Camera } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export interface CameraConsentBannerProps {
  onAccept: () => void;
}

/** NFR-19 / ui-ux-foundation §8 — camera consent before getUserMedia */
export function CameraConsentBanner({ onAccept }: CameraConsentBannerProps) {
  return (
    <div data-testid="camera-consent-banner">
      <Alert
        variant="info"
        icon={Camera}
        title="Quyền truy cập camera"
        className="mb-4"
      >
        <p className="mb-3">
          Camera chỉ dùng để quét mã QR điểm danh. Hình ảnh không được ghi lại hoặc tải lên
          máy chủ.
        </p>
        <Button type="button" size="sm" onClick={onAccept} className="min-h-touch">
          Đồng ý
        </Button>
      </Alert>
    </div>
  );
}
