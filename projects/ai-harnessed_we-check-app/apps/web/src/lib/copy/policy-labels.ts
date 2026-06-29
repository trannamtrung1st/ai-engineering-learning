/** FR-16 / AC-16 / BR-05 — attendance policy admin copy */
export const policyCopy = {
  pageTitle: "Chính sách điểm danh",
  pageDescription:
    "Cấu hình ngưỡng vắng mặt và cảnh báo tự động cho sinh viên và giảng viên.",
  fieldThreshold: "Ngưỡng vắng (%)",
  fieldThresholdHint:
    "Sinh viên vượt ngưỡng sẽ nhận cảnh báo cùng giảng viên phụ trách",
  fieldAutoWarning: "Gửi cảnh báo tự động",
  fieldAutoWarningHint:
    "Khi bật, hệ thống gửi thông báo sau mỗi lần đóng buổi học nếu tỷ lệ vắng vượt ngưỡng",
  saveButton: "Lưu chính sách",
  saveSuccess: "Đã lưu chính sách điểm danh",
  saveError: "Không thể lưu chính sách. Vui lòng thử lại.",
  loadError: "Không thể tải chính sách. Vui lòng thử lại.",
  retryButton: "Thử lại",
  thresholdRequired: "Ngưỡng vắng là bắt buộc",
  thresholdRange: "Giá trị phải là số nguyên từ 1 đến 100",
} as const;
