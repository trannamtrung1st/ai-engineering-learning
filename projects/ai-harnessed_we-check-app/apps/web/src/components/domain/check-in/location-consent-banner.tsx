import { MapPin } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export interface LocationConsentBannerProps {
  onAccept: () => void;
  onDismiss?: () => void;
}

/** NFR-17 / NFR-12 — GPS consent copy before first check-in */
export function LocationConsentBanner({ onAccept, onDismiss }: LocationConsentBannerProps) {
  return (
    <Alert
      variant="info"
      icon={MapPin}
      title="Quyền truy cập vị trí"
      className="mb-4"
    >
      <p className="mb-3">
        We Check cần quyền định vị để xác minh bạn đang ở trong phòng học. Dữ liệu
        vị trí chỉ dùng cho điểm danh và không được lưu trữ lâu dài.
      </p>
      <div className="flex gap-2">
        <Button type="button" size="sm" onClick={onAccept}>
          Đồng ý
        </Button>
        {onDismiss ? (
          <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
            Bỏ qua
          </Button>
        ) : null}
      </div>
    </Alert>
  );
}
