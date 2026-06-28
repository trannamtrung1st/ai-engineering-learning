# Business Requirements Document

## Vision and Objectives
## Vision
- Xây dựng hệ thống điểm danh số hóa cho workshop Harness Engineering for Software Development, thay thế quy trình thủ công, phục vụ 100–150 học sinh/sinh viên mỗi đợt tổ chức định kỳ.

## Objectives
| goal | user/business value | metric | target | timeframe |
| --- | --- | --- | --- | --- |
| Tự động hóa check-in | Tiết kiệm thời gian, giảm sai sót so với điểm danh thủ công | Thời gian hoàn tất điểm danh toàn bộ người tham dự | < 5 phút | Mỗi buổi workshop |
| Quản lý danh sách người tham dự | Ban tổ chức kiểm soát được danh sách đăng ký và thực tế tham dự mỗi đợt | Tỷ lệ xác thực danh tính thành công khi check-in | ≥ 98% | Mỗi đợt workshop |
| Báo cáo & theo dõi tỷ lệ tham dự | Ban tổ chức đánh giá được hiệu quả từng đợt workshop và lưu trữ lịch sử | Thời gian xuất báo cáo sau khi buổi học kết thúc | < 10 phút | Mỗi buổi workshop |

## Success Metrics
| goal | user/business value | metric | target | timeframe |
| --- | --- | --- | --- | --- |
| Độ chính xác điểm danh | Dữ liệu tham dự đáng tin cậy, không cần đối soát thủ công | Tỷ lệ check-in thành công / tổng người tham dự | ≥ 99% | Mỗi buổi workshop |
| Độ ổn định hệ thống | Không làm gián đoạn buổi workshop, đảm bảo trải nghiệm người tham dự | Thời gian downtime trong mỗi buổi | 0 phút | Mỗi buổi workshop |
## Problem Statement
## Problem Statement
- Ban tổ chức workshop HESD hiện phải điểm danh thủ công (gọi tên / ký giấy) cho 100–150 sinh viên mỗi buổi, dẫn đến hai hệ quả nghiêm trọng: (1) tiêu tốn 15–30 phút thời gian buổi học chỉ để hoàn tất điểm danh, và (2) không có cơ chế xác thực danh tính, tạo điều kiện cho sinh viên điểm danh hộ nhau.

## Affected Users
- Ban tổ chức / Admin workshop HESD: chịu gánh nặng vận hành điểm danh thủ công và tổng hợp báo cáo sau mỗi buổi.
- Giảng viên / Facilitator: bị gián đoạn nội dung giảng dạy do phải chờ hoàn tất điểm danh thủ công trước mỗi buổi.
- Sinh viên / Người tham dự (100–150 người/đợt): mất thời gian chờ đợi trong quy trình điểm danh thủ công; một bộ phận có thể lợi dụng sơ hở để điểm danh hộ.

## Impact
- Dữ liệu tham dự không chính xác do gian lận điểm danh hộ → ban tổ chức không thể đánh giá đúng hiệu quả workshop, ảnh hưởng đến quyết định cải tiến nội dung và báo cáo với nhà tài trợ/ban lãnh đạo.
- Mỗi buổi workshop mất 15–30 phút cho điểm danh thủ công → thời gian học thực tế bị rút ngắn, trải nghiệm người tham dự giảm sút, và ban tổ chức tốn thêm thời gian tổng hợp báo cáo thủ công sau buổi học.

## Root Cause / Contributing Factors
- Nguyên nhân gốc rễ: HESD chưa có hệ thống điểm danh số hóa → toàn bộ quy trình phụ thuộc vào con người (gọi tên, ký giấy) → không thể mở rộng quy mô lên 100–150 người mà vẫn đảm bảo tốc độ và tính chính xác.
## Stakeholder Register
## Stakeholders
| role | responsibility | decision authority | needs/concerns | involvement |
| --- | --- | --- | --- | --- |
| Sinh viên | Quét QR code động (xoay mỗi 30 giây) để điểm danh mỗi buổi học; xem lịch sử chuyên cần cá nhân |  |  | Người dùng cuối — tương tác trực tiếp mỗi buổi học |
| Giảng viên | Tạo/mở buổi học; hiển thị QR code động trên lớp; theo dõi điểm danh theo thời gian thực; chỉnh sửa điểm danh thủ công khi có ngoại lệ; xuất báo cáo chuyên cần theo lớp/môn |  |  | Người dùng chính — tương tác mỗi buổi học và khi xem báo cáo định kỳ |
| Phòng Đào Tạo (Admin) | Quản trị hệ thống toàn trường; cấu hình chính sách chuyên cần (ngưỡng vắng, hình thức xử lý); xuất dữ liệu điểm danh cho các mục đích học vụ; quản lý tài khoản giảng viên và sinh viên |  |  | Quản trị viên cấp cao — thiết lập hệ thống, giám sát định kỳ, xử lý ngoại lệ và khiếu nại |
| Phòng CNTT | Vận hành hạ tầng máy chủ; đảm bảo uptime hệ thống; xử lý sự cố kỹ thuật; bảo trì định kỳ; hỗ trợ tích hợp với hệ thống CNTT hiện có của trường |  |  | Vận hành nền — không tương tác trực tiếp với nghiệp vụ điểm danh; can thiệp khi có sự cố hoặc nâng cấp |
## Scope and Capabilities
## Scope
- Trong phạm vi: Tạo buổi học (giảng viên), QR code động xoay mỗi 30 giây, điểm danh qua mobile, chống gian lận vị trí (GPS spoofing), chống điểm danh hộ, báo cáo chuyên cần theo lớp/môn, xuất dữ liệu CSV cho phòng đào tạo.
- Hệ thống chạy trên nền web + mobile web; sinh viên không cần cài ứng dụng riêng — chỉ cần trình duyệt điện thoại hỗ trợ camera và GPS. ⟨needs_confirmation⟩
- Ngưỡng bán kính GPS hợp lệ mặc định là 100m tính từ tọa độ phòng học; giảng viên có thể điều chỉnh ngưỡng này khi tạo buổi học. ⟨needs_confirmation⟩

## Capabilities
| capability | priority | rationale | dependency |
| --- | --- | --- | --- |
| Tạo & quản lý buổi học | Must | Điều kiện tiên quyết để sinh ra QR và ghi nhận điểm danh | Xác thực tài khoản giảng viên |
| Sinh QR code động (30 giây) | Must | Cơ chế điểm danh cốt lõi — QR xoay liên tục ngăn chụp màn hình/chia sẻ mã | CAP-01 (buổi học đã tạo) |
| Điểm danh qua mobile (quét QR) | Must | Kênh điểm danh chính của sinh viên — không cần cài app riêng, dùng camera điện thoại | CAP-02 (QR động đang hiển thị) |
| Chống gian lận vị trí (GPS spoofing) | Must | Đảm bảo sinh viên thực sự có mặt trong lớp — so sánh GPS thiết bị với tọa độ phòng học, từ chối nếu lệch quá ngưỡng cho phép | CAP-03 (điểm danh mobile), CAP-01 (tọa độ phòng học) |
| Chống điểm danh hộ | Must | Mỗi tài khoản sinh viên chỉ được ghi nhận 1 lần/buổi; kết hợp xác thực tài khoản + vị trí + token QR một lần dùng để loại bỏ khả năng chia sẻ mã cho người khác điểm danh hộ | CAP-03 (điểm danh mobile), CAP-02 (QR động) |
| Báo cáo chuyên cần theo lớp/môn | Should | Giảng viên theo dõi tỷ lệ tham dự từng sinh viên theo buổi/môn; phòng đào tạo nắm tổng quan toàn trường | CAP-03 (dữ liệu điểm danh đã ghi nhận) |
| Xuất dữ liệu CSV | Should | Phòng đào tạo cần xuất dữ liệu điểm danh để tích hợp vào hệ thống quản lý học vụ hiện có | CAP-06 (dữ liệu báo cáo chuyên cần) |

## Out of Scope
- Ngoài phạm vi (giai đoạn đầu): Tích hợp nhận diện khuôn mặt, thanh toán học phí, quản lý lịch thi.
## Business Rules
## Business Rules
| rule id | condition | trigger | outcome | scope | exception |
| --- | --- | --- | --- | --- | --- |
| BR-01 | Thời điểm quét QR > (giờ mở buổi + 10 phút) | Sinh viên quét QR code | Từ chối điểm danh; ghi nhận trạng thái Vắng cho sinh viên chưa điểm danh | Tất cả sinh viên đăng ký môn học | Giảng viên có thể gia hạn thủ công (needs_confirmation) |
| BR-02 | Khoảng cách GPS thiết bị sinh viên > 50m so với tọa độ phòng học | Sinh viên gửi yêu cầu điểm danh | Từ chối điểm danh; ghi log cảnh báo giả mạo vị trí | Tất cả sinh viên đăng ký môn học | Giảng viên có thể điều chỉnh bán kính khi tạo buổi học (needs_confirmation) |
| BR-03 | Thời điểm quét QR > (thời điểm sinh mã + 30 giây) | Sinh viên quét QR code | Từ chối điểm danh; hiển thị thông báo 'Mã QR đã hết hạn, vui lòng quét mã mới' | Tất cả sinh viên đăng ký môn học | Không có ngoại lệ — mã hết hạn là tuyệt đối để chống chia sẻ mã |
| BR-04 | Tài khoản sinh viên đã có bản ghi điểm danh thành công trong buổi học hiện tại | Sinh viên gửi yêu cầu điểm danh lần 2 trở lên trong cùng buổi | Từ chối điểm danh; hiển thị thông báo 'Bạn đã điểm danh buổi học này rồi' | Tất cả sinh viên đăng ký môn học | Không có ngoại lệ — ngăn điểm danh hộ |
| BR-05 | Số buổi vắng / Tổng số buổi đã diễn ra > 20% | Hệ thống cập nhật bản ghi điểm danh sau mỗi buổi học | Gửi cảnh báo tự động đến sinh viên và giảng viên phụ trách môn | Tất cả sinh viên đăng ký môn học | Vắng có phép (được giảng viên xác nhận) không tính vào tỷ lệ (needs_confirmation) |
| BR-06 | Thiết bị gửi yêu cầu điểm danh không có phiên đăng nhập hợp lệ | Sinh viên truy cập trang điểm danh / quét QR | Chuyển hướng đến trang đăng nhập; từ chối ghi nhận điểm danh | Tất cả sinh viên | Không có ngoại lệ — xác thực danh tính là bắt buộc |
| BR-07 | Buổi học được tạo nhưng chưa có tọa độ GPS phòng học hợp lệ | Giảng viên kích hoạt buổi học / bật QR code | Hệ thống chặn kích hoạt; hiển thị thông báo yêu cầu cấu hình vị trí phòng học | Giảng viên tạo buổi học | Không có ngoại lệ — tọa độ là bắt buộc để xác minh GPS sinh viên |
| BR-08 | Người dùng yêu cầu xem báo cáo chuyên cần không phải giảng viên phụ trách môn đó và không phải admin | Người dùng truy cập trang báo cáo chuyên cần | Từ chối truy cập; hiển thị thông báo 'Bạn không có quyền xem báo cáo này' | Giảng viên, phòng đào tạo (admin) | Admin có quyền xem tất cả — không bị giới hạn theo môn |
| BR-09 | Người dùng yêu cầu xuất CSV không có vai trò admin (phòng đào tạo) | Người dùng nhấn nút Xuất dữ liệu CSV | Từ chối xuất; hiển thị thông báo 'Chỉ phòng đào tạo mới có quyền xuất dữ liệu' | Tất cả người dùng hệ thống | Không có ngoại lệ — kiểm soát dữ liệu tập trung tại phòng đào tạo |
| BR-10 | Giảng viên yêu cầu chỉnh sửa trạng thái điểm danh sau khi buổi học kết thúc, trong vòng 24 giờ | Giảng viên thao tác chỉnh sửa thủ công trên giao diện quản lý điểm danh | Cập nhật trạng thái điểm danh; ghi audit log (ai sửa, lúc nào, từ trạng thái nào sang trạng thái nào) | Giảng viên phụ trách môn học | Sau 24 giờ, chỉ admin (phòng đào tạo) mới có quyền chỉnh sửa (needs_confirmation) |
| BR-11 | Token QR đã được một sinh viên quét thành công | Sinh viên thứ hai quét cùng token QR trong vòng 30 giây hiệu lực | Từ chối điểm danh; ghi log cảnh báo nghi ngờ chia sẻ mã | Tất cả sinh viên đăng ký môn học | Không có ngoại lệ — mỗi token là one-time-use |
| BR-12 | Thiết bị sinh viên tắt GPS hoặc từ chối cấp quyền định vị cho trình duyệt | Sinh viên gửi yêu cầu điểm danh | Từ chối điểm danh; hiển thị thông báo 'Vui lòng bật GPS và cấp quyền định vị để điểm danh' | Tất cả sinh viên đăng ký môn học | Không có ngoại lệ — GPS là bắt buộc để xác minh vị trí |
## Constraints and Assumptions
## Constraints
| constraint/assumption | impact | owner/source | validation |
| --- | --- | --- | --- |
|  | Toàn bộ UI/UX và API phải tương thích cross-platform; không dùng tính năng native độc quyền |  | Kiểm thử trên thiết bị thực iOS 15+ và Android 10+ trước khi pilot |
|  | Bắt buộc có cơ chế đồng ý (consent), giới hạn thu thập dữ liệu GPS chỉ ở mức cần thiết, server đặt tại VN, có API xóa dữ liệu theo yêu cầu |  | Audit checklist NĐ 13/2023 trước khi go-live; review bởi tư vấn pháp lý |
|  | Phạm vi tính năng phải được ưu tiên nghiêm ngặt (Must-have trước); không thể phát triển tích hợp sâu hoặc tính năng phức tạp trong giai đoạn pilot |  | Xác nhận ngân sách và timeline với sponsor trước khi bắt đầu sprint đầu tiên |
|  | Nếu người dùng từ chối quyền, không thể quét QR hoặc xác minh vị trí — luồng điểm danh bị chặn hoàn toàn |  | Kiểm thử trên Safari iOS và Chrome Android; thiết kế UX hướng dẫn cấp quyền rõ ràng |

## Assumptions
| constraint/assumption | impact | owner/source | validation |
| --- | --- | --- | --- |
|  | Nếu sinh viên không có smartphone phù hợp, không thể điểm danh — cần phương án dự phòng (giảng viên điểm danh thủ công) |  | Khảo sát sinh viên trước pilot; xác nhận tỷ lệ sở hữu smartphone ≥ 95% |
|  | Nếu mạng không ổn định, sinh viên không thể gửi yêu cầu điểm danh real-time; cần cơ chế retry hoặc offline fallback |  | Kiểm tra chất lượng mạng tại các phòng học pilot trước khi triển khai |
|  | Nếu API giáo vụ không sẵn sàng hoặc định dạng dữ liệu không tương thích, giảng viên phải nhập tay danh sách lớp — tăng rủi ro sai sót và chậm tiến độ pilot |  | Xác nhận định dạng và phương thức cung cấp dữ liệu (API/CSV/Excel) với phòng CNTT trước sprint 1 |
|  | Nếu ngưỡng quá rộng → gian lận vị trí dễ qua mặt; quá hẹp → sinh viên ngồi cuối phòng bị từ chối oan |  | Thử nghiệm thực địa tại ≥ 3 phòng học có kích thước khác nhau trong tuần đầu pilot ⚠️ needs confirmation |
|  | Nếu trường chưa có SSO, cần xây dựng hệ thống xác thực riêng — tăng chi phí và thời gian phát triển trong giai đoạn pilot |  | Xác nhận phương thức xác thực với phòng CNTT trường trước sprint 1 ⚠️ needs confirmation |
|  | Giảm rủi ro vi phạm NĐ 13/2023; nếu lưu GPS lâu dài cần thêm cơ chế bảo vệ và đồng ý bổ sung |  | Review kiến trúc dữ liệu: xác nhận GPS không được persist sau khi điểm danh thành công ⚠️ needs confirmation |
|  | Không thể dùng cloud nước ngoài làm primary storage; tăng chi phí hạ tầng nếu phải tự vận hành server |  | Xác nhận nhà cung cấp hosting VN (VNG Cloud, FPT Cloud, v.v.) trước khi thiết kế hạ tầng |
|  | Nếu không kiểm soát, sinh viên có thể chia sẻ token QR cho người khác điểm danh hộ sau khi bản thân đã rời lớp |  | Kiểm thử: thử quét QR lần 2 từ cùng tài khoản — hệ thống phải trả lỗi 409 Conflict |

## Validation Plan
| constraint/assumption | impact | owner/source | validation |
| --- | --- | --- | --- |
|  | Xác nhận C01, C04 — nếu thất bại phải điều chỉnh stack trước pilot |  | Pass/Fail checklist trên ≥ 4 thiết bị thực trước sprint cuối |
|  | Xác nhận C02, A07 — nếu phát hiện vi phạm phải điều chỉnh kiến trúc trước go-live |  | Checklist 10 điểm theo NĐ 13/2023; ký biên bản xác nhận trước tuần 4 pilot |
|  | Xác nhận A03 — nếu API không sẵn sàng phải có phương án import thủ công |  | Biên bản xác nhận định dạng dữ liệu trước sprint 1 |
|  | Xác nhận A04 — ngưỡng 100m có phù hợp thực tế không; điều chỉnh trước khi mở rộng pilot |  | Đo GPS tại ≥ 3 phòng học kích thước khác nhau (nhỏ/vừa/lớn); ghi nhận độ lệch thực tế |
|  | Xác nhận cơ chế chống GPS spoofing và điểm danh hộ hoạt động đúng trước khi go-live |  | Tỷ lệ phát hiện gian lận ≥ 99% trong bộ test case; zero false positive trên sinh viên hợp lệ |
## Risks and Issues
## Risks
| risk | likelihood | impact | mitigation | status |
| --- | --- | --- | --- | --- |
| Sinh viên không có smartphone / hết pin / mất mạng | Trung bình | Cao — sinh viên bị ghi vắng oan, khiếu nại tăng | Giảng viên có quyền điểm danh thủ công dự phòng; thông báo chính sách mang sạc dự phòng | Open |
| Giả mạo vị trí GPS bằng fake location app | Cao | Cao — phá vỡ cơ chế chống gian lận cốt lõi, mất tin cậy hệ thống | Phát hiện mock location API (Android MockLocation flag, iOS không cho phép mock natively); kết hợp xác minh WiFi BSSID của phòng học; phân tích bất thường tọa độ (độ chính xác GPS quá hoàn hảo) | Open |
| Điểm danh hộ qua chia sẻ QR trong cửa sổ 30 giây | Cao | Cao — vô hiệu hóa mục tiêu chống gian lận, ảnh hưởng tính toàn vẹn dữ liệu chuyên cần | QR token một lần dùng (one-time-use per account/session); ghi nhận device fingerprint; giới hạn 1 lần quét/tài khoản/buổi học | Open |
| Quá tải server giờ cao điểm (nhiều lớp điểm danh đồng thời) | Cao | Cao — QR không tải được, sinh viên không điểm danh được, dữ liệu bị mất | Auto-scaling hạ tầng cloud; load test trước pilot với ≥ 500 concurrent users; queue request điểm danh với retry logic | Open |
| Lộ lọt dữ liệu cá nhân sinh viên (GPS, danh tính, lịch sử điểm danh) | Trung bình | Rất cao — vi phạm NĐ 13/2023, rủi ro pháp lý, mất uy tín trường | Mã hóa dữ liệu at-rest và in-transit (TLS 1.2+); không lưu GPS lâu dài sau khi xác minh; phân quyền truy cập theo vai trò (RBAC); audit log mọi truy cập dữ liệu nhạy cảm | Open |
| Giảng viên không biết sử dụng hệ thống / thao tác sai | Trung bình | Cao — giảng viên không tạo được buổi học, toàn bộ luồng điểm danh bị chặn | Thiết kế UX đơn giản, tài liệu hướng dẫn nhanh (quick-start guide), tổ chức tập huấn trước pilot | Open |
| Sinh viên từ chối cấp quyền GPS / Camera trên trình duyệt | Trung bình | Trung bình — sinh viên không điểm danh được, cần hỗ trợ thủ công | Hiển thị hướng dẫn cấp quyền rõ ràng khi onboarding; giảng viên có quyền ghi nhận thủ công dự phòng | Open |
| Tài khoản sinh viên bị đánh cắp / chia sẻ để điểm danh từ xa | Trung bình | Cao — vô hiệu hóa xác thực danh tính, gian lận khó phát hiện | Bắt buộc xác thực 2 yếu tố (2FA) hoặc SSO trường; cảnh báo đăng nhập từ thiết bị lạ; khóa phiên sau thời gian không hoạt động | Open |

## Issues
| risk | likelihood | impact | mitigation | status |
| --- | --- | --- | --- | --- |
| API giáo vụ chưa xác nhận — chưa có hợp đồng dữ liệu với phòng CNTT trường | Cao | Trung bình — chậm tiến độ pilot, tăng nhập liệu thủ công | Xác nhận định dạng dữ liệu (API/CSV/Excel) với phòng CNTT trước sprint 1; chuẩn bị phương án import thủ công dự phòng | Open ⚠️ needs_confirmation |
| Ngưỡng GPS 100m chưa kiểm thử thực địa | Cao | Trung bình — false positive (từ chối SV hợp lệ) hoặc false negative (gian lận lọt qua) | Thử nghiệm thực địa tại ≥ 3 phòng học khác kích thước; cho phép giảng viên điều chỉnh ngưỡng theo từng phòng | Open ⚠️ needs_confirmation |
| Phương thức xác thực tài khoản chưa xác nhận (SSO vs. hệ thống riêng) | Cao | Trung bình — nếu không có SSO phải xây thêm module xác thực, tăng chi phí và thời gian | Xác nhận với phòng CNTT trường trước sprint 1; chuẩn bị phương án xác thực email trường dự phòng | Open ⚠️ needs_confirmation |
| Chưa xác định chủ thể xử lý dữ liệu theo NĐ 13/2023 | Trung bình | Cao — vi phạm pháp lý nếu không ký hợp đồng xử lý dữ liệu trước go-live | Xác nhận vai trò pháp lý (controller vs. processor) với tư vấn pháp lý và ban lãnh đạo trường trước tuần 4 pilot | Open ⚠️ needs_confirmation |

## Mitigation Plan
| risk | likelihood | impact | mitigation | status |
| --- | --- | --- | --- | --- |
| R01 — Sinh viên không có smartphone / hết pin / mất mạng | Trung bình | Cao | 1. Giảng viên điểm danh thủ công dự phòng trên giao diện web. 2. Thông báo chính sách mang sạc dự phòng. 3. Hỗ trợ mã PIN ngắn hạn khi thiết bị hết pin ⚠️ needs_confirmation. | Open |
| R02 — Giả mạo vị trí GPS bằng fake location app | Cao | Cao | 1. Kiểm tra Android MockLocation flag qua API. 2. Phân tích độ chính xác GPS bất thường (accuracy < 5m → nghi ngờ). 3. Xác minh WiFi BSSID phòng học. 4. Ghi log cảnh báo để giảng viên xác nhận thủ công. | Open |
| R03 — Điểm danh hộ qua chia sẻ QR trong cửa sổ 30 giây | Cao | Cao | 1. QR token one-time-use gắn với session + tài khoản. 2. Ghi nhận device fingerprint (User-Agent, screen resolution). 3. Từ chối quét lần 2 từ cùng tài khoản (HTTP 409). 4. Cảnh báo giảng viên khi cùng token bị quét từ 2 thiết bị khác nhau. | Open |
| R04 — Quá tải server giờ cao điểm (nhiều lớp điểm danh đồng thời) | Cao | Cao | 1. Auto-scaling hạ tầng cloud (horizontal scaling). 2. Load test trước pilot với ≥ 500 concurrent users. 3. Queue request điểm danh với retry logic (tối đa 3 lần trong 30 giây). 4. CDN cho QR image. 5. Giám sát real-time với alert ngưỡng CPU/RAM > 80%. | Open |
| R05 — Lộ lọt dữ liệu cá nhân sinh viên | Trung bình | Rất cao | 1. Mã hóa TLS 1.2+ cho mọi kết nối. 2. Mã hóa at-rest (AES-256). 3. Không lưu GPS sau khi xác minh xong. 4. RBAC phân quyền theo vai trò. 5. Audit log mọi truy cập dữ liệu nhạy cảm. 6. Ký hợp đồng xử lý dữ liệu theo NĐ 13/2023 trước go-live. | Open |
## Research Basis
_No content._
