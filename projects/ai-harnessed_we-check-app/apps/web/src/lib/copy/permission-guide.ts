import type { MobilePlatform } from "@/lib/detect-platform";

export type PermissionGuideType = "camera" | "gps";

export interface PermissionGuideContent {
  title: string;
  steps: string[];
}

const cameraSteps: Record<MobilePlatform, string[]> = {
  ios: [
    "Mở Cài đặt > Quyền riêng tư & Bảo mật > Camera",
    "Bật quyền Camera cho Safari",
    "Quay lại We Check và thử quét lại",
  ],
  android: [
    "Mở Cài đặt > Ứng dụng > Chrome",
    "Chọn Quyền > Camera > Cho phép",
    "Quay lại We Check và thử quét lại",
  ],
  unknown: [
    "Mở cài đặt trình duyệt và cho phép quyền Camera",
    "Làm mới trang We Check",
    "Thử quét mã QR lại",
  ],
};

const gpsSteps: Record<MobilePlatform, string[]> = {
  ios: [
    "Mở Cài đặt > Quyền riêng tư & Bảo mật > Dịch vụ vị trí",
    "Bật Dịch vị trí và cho phép Safari \"Khi dùng ứng dụng\"",
    "Quay lại We Check và thử điểm danh lại",
  ],
  android: [
    "Mở Cài đặt > Vị trí và bật GPS",
    "Trong Chrome, chọn Quyền > Vị trí > Cho phép",
    "Quay lại We Check và thử điểm danh lại",
  ],
  unknown: [
    "Bật GPS trên thiết bị",
    "Cho phép trình duyệt truy cập vị trí khi được hỏi",
    "Quay lại We Check và thử điểm danh lại",
  ],
};

const titles: Record<PermissionGuideType, string> = {
  camera: "Hướng dẫn bật quyền Camera",
  gps: "Hướng dẫn bật quyền định vị",
};

/** NFR-19 — platform-specific Vietnamese permission recovery steps */
export function getPermissionGuideContent(
  type: PermissionGuideType,
  platform: MobilePlatform,
): PermissionGuideContent {
  const steps = type === "camera" ? cameraSteps[platform] : gpsSteps[platform];
  return { title: titles[type], steps };
}
