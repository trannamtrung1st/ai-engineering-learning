import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/page-header";
import { SessionForm } from "@/components/instructor/session-form";
import type { SessionDto } from "@/lib/sessions-api";

/** FR-04 / AC-04 — create session page */
export function CreateSessionPage() {
  const navigate = useNavigate();

  function handleSaved(session: SessionDto) {
    toast.success("Đã lưu thành công");
    navigate(`/sessions/${session.id}?tab=settings`);
  }

  function handleOpened(session: SessionDto) {
    toast.success("Đã mở buổi học");
    navigate(`/sessions/${session.id}?tab=monitor`);
  }

  return (
    <div data-testid="create-session-page">
      <PageHeader
        title="Tạo buổi học"
        description="Cấu hình thông tin buổi học và tọa độ GPS phòng học"
      />
      <SessionForm mode="create" onSaved={handleSaved} onOpened={handleOpened} />
    </div>
  );
}
