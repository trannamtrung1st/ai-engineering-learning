import { Button } from "../ui/Button";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import styles from "./GpsPermissionPrompt.module.css";

export interface GpsPermissionPromptProps {
  onAllow: () => void;
  onDeny: () => void;
}

export function GpsPermissionPrompt({ onAllow, onDeny }: GpsPermissionPromptProps) {
  return (
    <div className={styles.prompt}>
      <FeedbackAlert variant="brand" title="Cần quyền vị trí để xác minh bạn đang ở lớp">
        Attendly chỉ dùng vị trí một lần khi bạn bấm điểm danh — không theo dõi liên tục. Điều
        này giúp giảm rủi ro gian lận, không đảm bảo chống giả mạo tuyệt đối.
      </FeedbackAlert>
      <div className={styles.actions}>
        <Button fullWidth onClick={onAllow}>
          Cho phép vị trí
        </Button>
        <Button fullWidth variant="secondary" onClick={onDeny}>
          Từ chối
        </Button>
      </div>
    </div>
  );
}
