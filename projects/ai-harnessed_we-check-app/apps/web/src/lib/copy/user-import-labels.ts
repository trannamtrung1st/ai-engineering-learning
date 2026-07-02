/** Vietnamese copy for admin user CSV import — FR-01 / AC-01 */
export const userImportCopy = {
  pageTitle: "Nhập CSV người dùng",
  pageDescription: "Tải lên tệp CSV để tạo hoặc cập nhật tài khoản theo mã SV / mã cán bộ",
  importButton: "Nhập CSV",
  backToUsers: "Quay lại danh sách",
  dropzoneHint: "Kéo thả tệp CSV hoặc nhấn để chọn",
  dropzoneMaxSize: "Tối đa 5 MB, định dạng .csv",
  selectedFile: "Đã chọn",
  previewButton: "Xem trước",
  confirmButton: "Xác nhận nhập",
  templateDownload: "Tải mẫu CSV",
  previewTitle: "Xem trước (10 dòng đầu)",
  validating: "Đang kiểm tra tệp…",
  importing: "Đang nhập người dùng…",
  invalidFileTitle: "Tệp không đúng định dạng",
  invalidFileMessage:
    "Tệp CSV phải có các cột: institutional_id, display_name, email, role, active.",
  invalidFileApi: "File CSV không hợp lệ hoặc quá lớn",
  validationSummary: (valid: number, errors: number) =>
    `${valid} dòng hợp lệ, ${errors} dòng lỗi`,
  importCompleteTitle: "Hoàn tất nhập",
  importCompleteSuccess: (created: number, updated: number, rejected: number) =>
    rejected > 0
      ? `Đã tạo ${created}, cập nhật ${updated}; ${rejected} dòng lỗi`
      : `Đã tạo ${created}, cập nhật ${updated}`,
  importSuccessToast: "Đã nhập người dùng thành công",
  errorListToggle: "Xem chi tiết lỗi",
  errorListHide: "Ẩn chi tiết lỗi",
  errorRowLabel: (row: number, message: string) => `Dòng ${row}: ${message}`,
  importAnother: "Nhập tệp khác",
  viewUsersLink: "Xem danh sách người dùng",
  colInstitutionalId: "Mã SV / Mã cán bộ",
  colDisplayName: "Họ và tên",
  colEmail: "Email",
  colRole: "Vai trò",
  colActive: "Trạng thái",
  colStatus: "Thao tác",
  statusCreate: "Tạo mới",
  statusUpdate: "Cập nhật",
  statusError: "Lỗi",
  loadError: "Không thể xử lý tệp nhập",
} as const;
