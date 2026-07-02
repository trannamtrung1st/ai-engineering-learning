import { ErrorCode, type ErrorCode as ErrorCodeType } from "@wecheck/domain";

export interface ErrorDetail {
  field: string;
  code: string;
  message: string;
}

export interface ApiErrorBody {
  errorCode: ErrorCodeType;
  message: string;
  details?: ErrorDetail[];
  requestId: string;
}

export class ApiError extends Error {
  readonly statusCode: number;
  readonly errorCode: ErrorCodeType;
  readonly details?: ErrorDetail[];

  constructor(
    statusCode: number,
    errorCode: ErrorCodeType,
    message: string,
    details?: ErrorDetail[],
  ) {
    super(message);
    this.name = "ApiError";
    this.statusCode = statusCode;
    this.errorCode = errorCode;
    this.details = details;
  }

  toBody(requestId: string): ApiErrorBody {
    return {
      errorCode: this.errorCode,
      message: this.message,
      ...(this.details?.length ? { details: this.details } : {}),
      requestId,
    };
  }
}

export function unauthenticated(): ApiError {
  return new ApiError(
    401,
    ErrorCode.Unauthenticated,
    ERROR_MESSAGES[ErrorCode.Unauthenticated],
  );
}

export function sessionExpired(): ApiError {
  return new ApiError(
    401,
    ErrorCode.SessionExpired,
    ERROR_MESSAGES[ErrorCode.SessionExpired],
  );
}

export function forbidden(message?: string): ApiError {
  return new ApiError(
    403,
    ErrorCode.Forbidden,
    message ?? ERROR_MESSAGES[ErrorCode.Forbidden],
  );
}

export function invalidCredentials(): ApiError {
  return new ApiError(
    401,
    ErrorCode.InvalidCredentials,
    ERROR_MESSAGES[ErrorCode.InvalidCredentials],
  );
}

export function accountDeactivated(): ApiError {
  return new ApiError(
    403,
    ErrorCode.AccountDeactivated,
    ERROR_MESSAGES[ErrorCode.AccountDeactivated],
  );
}

export function validationFailed(
  details: ErrorDetail[],
  message = ERROR_MESSAGES[ErrorCode.ValidationFailed],
): ApiError {
  return new ApiError(422, ErrorCode.ValidationFailed, message, details);
}

export function invalidFile(message?: string): ApiError {
  return new ApiError(
    422,
    ErrorCode.InvalidFile,
    message ?? ERROR_MESSAGES[ErrorCode.InvalidFile],
  );
}

export function notFound(message?: string): ApiError {
  return new ApiError(
    404,
    ErrorCode.NotFound,
    message ?? ERROR_MESSAGES[ErrorCode.NotFound],
  );
}

export function exportNotAllowed(): ApiError {
  return new ApiError(
    403,
    ErrorCode.ExportNotAllowed,
    ERROR_MESSAGES[ErrorCode.ExportNotAllowed],
  );
}

export function reportAccessDenied(): ApiError {
  return new ApiError(
    403,
    ErrorCode.ReportAccessDenied,
    ERROR_MESSAGES[ErrorCode.ReportAccessDenied],
  );
}

export function internalError(): ApiError {
  return new ApiError(
    500,
    ErrorCode.InternalError,
    ERROR_MESSAGES[ErrorCode.InternalError],
  );
}

export function serviceUnavailable(): ApiError {
  return new ApiError(
    503,
    ErrorCode.ServiceUnavailable,
    ERROR_MESSAGES[ErrorCode.ServiceUnavailable],
  );
}

export function roomGpsRequired(): ApiError {
  return new ApiError(
    422,
    ErrorCode.RoomGpsRequired,
    ERROR_MESSAGES[ErrorCode.RoomGpsRequired],
  );
}

export function invalidSessionState(): ApiError {
  return new ApiError(
    409,
    ErrorCode.InvalidSessionState,
    ERROR_MESSAGES[ErrorCode.InvalidSessionState],
  );
}

export function editWindowExpired(): ApiError {
  return new ApiError(
    403,
    ErrorCode.EditWindowExpired,
    ERROR_MESSAGES[ErrorCode.EditWindowExpired],
  );
}

export function invalidPagination(message?: string): ApiError {
  return new ApiError(
    400,
    ErrorCode.InvalidPagination,
    message ?? ERROR_MESSAGES[ErrorCode.InvalidPagination],
  );
}

/** Vietnamese default messages per docs/technical/09-error-handling.md §4 */
export const ERROR_MESSAGES: Readonly<Record<ErrorCodeType, string>> = {
  [ErrorCode.InvalidFormat]: "Định dạng trường không hợp lệ",
  [ErrorCode.InvalidEmail]: "Email không hợp lệ",
  [ErrorCode.PasswordTooShort]: "Mật khẩu phải có ít nhất 8 ký tự",
  [ErrorCode.InvalidLength]: "Độ dài dữ liệu không hợp lệ",
  [ErrorCode.InvalidInstitutionalId]: "Mã định danh không hợp lệ",
  [ErrorCode.InvalidTimestamp]: "Thời gian không hợp lệ",
  [ErrorCode.InvalidPagination]: "Tham số phân trang không hợp lệ",
  [ErrorCode.InvalidReturnUrl]: "Đường dẫn quay lại không hợp lệ",
  [ErrorCode.InvalidEnum]: "Giá trị enum không hợp lệ",
  [ErrorCode.InvalidFile]: "File CSV không hợp lệ hoặc quá lớn",
  [ErrorCode.ValidationFailed]: "Dữ liệu không hợp lệ",
  [ErrorCode.InvalidCredentials]: "Email hoặc mật khẩu không đúng",
  [ErrorCode.AccountDeactivated]: "Tài khoản đã bị vô hiệu hóa",
  [ErrorCode.Unauthenticated]: "Vui lòng đăng nhập để tiếp tục",
  [ErrorCode.SessionExpired]: "Phiên đăng nhập đã hết hạn",
  [ErrorCode.Forbidden]: "Bạn không có quyền thực hiện thao tác này",
  [ErrorCode.SessionNotActive]: "Buổi học chưa mở hoặc đã kết thúc",
  [ErrorCode.ExpiredQr]: "Mã QR đã hết hạn, vui lòng quét mã mới",
  [ErrorCode.OutOfRadius]:
    "Bạn đang ngoài phạm vi phòng học. Vui lòng di chuyển gần hơn hoặc liên hệ giảng viên.",
  [ErrorCode.DuplicateCheckIn]: "Bạn đã điểm danh buổi học này rồi",
  [ErrorCode.GpsDisabled]:
    "Vui lòng bật GPS và cấp quyền định vị để điểm danh",
  [ErrorCode.SpoofSuspected]:
    "Không thể xác minh vị trí. Liên hệ giảng viên.",
  [ErrorCode.NotEnrolled]:
    "Bạn không thuộc danh sách lớp của buổi học này",
  [ErrorCode.TokenNotFound]: "Mã QR không hợp lệ",
  [ErrorCode.TokenAlreadyUsed]: "Mã QR đã được sử dụng",
  [ErrorCode.RoomGpsRequired]:
    "Vui lòng cấu hình tọa độ GPS phòng học trước khi mở buổi",
  [ErrorCode.InvalidSessionState]:
    "Không thể thực hiện thao tác ở trạng thái buổi học hiện tại",
  [ErrorCode.EditWindowExpired]:
    "Đã quá thời hạn chỉnh sửa điểm danh (24 giờ)",
  [ErrorCode.RateLimitExceeded]: "Quá nhiều yêu cầu. Vui lòng thử lại sau.",
  [ErrorCode.NotFound]: "Không tìm thấy dữ liệu",
  [ErrorCode.Conflict]: "Dữ liệu đã thay đổi. Vui lòng tải lại.",
  [ErrorCode.InternalError]: "Đã xảy ra lỗi. Vui lòng thử lại.",
  [ErrorCode.ServiceUnavailable]: "Hệ thống tạm thời không khả dụng",
  [ErrorCode.ReportAccessDenied]: "Bạn không có quyền xem báo cáo này",
  [ErrorCode.ExportNotAllowed]:
    "Chỉ phòng đào tạo mới có quyền xuất dữ liệu",
  [ErrorCode.MalformedJson]: "Định dạng yêu cầu không hợp lệ",
  [ErrorCode.DuplicateClassCode]: "Mã lớp đã tồn tại",
  [ErrorCode.DuplicateSubjectCode]: "Mã môn học đã tồn tại",
  [ErrorCode.DuplicateEmail]: "Email đã tồn tại",
  [ErrorCode.SetupAlreadyComplete]:
    "Hệ thống đã hoàn tất thiết lập ban đầu. Vui lòng đăng nhập.",
};

export function duplicateClassCode(): ApiError {
  return new ApiError(
    422,
    ErrorCode.DuplicateClassCode,
    ERROR_MESSAGES[ErrorCode.DuplicateClassCode],
  );
}

export function duplicateSubjectCode(): ApiError {
  return new ApiError(
    422,
    ErrorCode.DuplicateSubjectCode,
    ERROR_MESSAGES[ErrorCode.DuplicateSubjectCode],
  );
}

export function setupAlreadyComplete(): ApiError {
  return new ApiError(
    403,
    ErrorCode.SetupAlreadyComplete,
    ERROR_MESSAGES[ErrorCode.SetupAlreadyComplete],
  );
}
