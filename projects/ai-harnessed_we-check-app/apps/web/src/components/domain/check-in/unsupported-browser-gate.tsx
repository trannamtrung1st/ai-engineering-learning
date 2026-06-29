import { AlertTriangle } from "lucide-react";
import { Alert } from "@/components/ui/alert";

/** NFR-18 — unsupported browser guidance without native app mandate */
export function UnsupportedBrowserGate() {
  return (
    <div data-testid="unsupported-browser-gate">
      <Alert
        variant="warning"
        icon={AlertTriangle}
        title="Trình duyệt không được hỗ trợ"
      >
        <p>
          We Check hoạt động tốt nhất trên Safari (iOS 15+) hoặc Chrome (Android 10+). Vui lòng
          mở liên kết điểm danh bằng một trong các trình duyệt này — không cần cài ứng dụng.
        </p>
      </Alert>
    </div>
  );
}
