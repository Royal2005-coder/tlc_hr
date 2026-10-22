# TLC HRM — Bảng ma trận vai trò vận hành, phân quyền và điều hướng Desk

**Tài liệu chuẩn hóa chính thức (Canonical Operating Role Matrix & Governance)**  
*Mã tài liệu:* `auto/OPERATING_ROLE_MATRIX.md` (đồng bộ tại `tlc_hr/docs/OPERATING_ROLE_MATRIX.md` và `tlc_hr/docs/OPERATIONS.md`)  
*Ngày ban hành:* 2026-10-22  
*Hệ thống:* TLC HRM trên nền Frappe HR v16 / ERPNext v16 / erpnextvn

---

## 1. Nguyên tắc cốt lõi về phân quyền và ranh giới quản trị

1. **Least Privilege (Quyền tối thiểu) & Phân định trách nhiệm thực chất (Segregation of Duties):**
   - **Nhân sự (HR):** Chịu trách nhiệm về mặt tổ chức nghiệp vụ, hồ sơ nhân sự, định biên, cây phê duyệt, kỳ công và khởi tạo đề xuất lương/quyết định nhân sự.
   - **Tổng Giám đốc (CEO / TLC Director):** Phê duyệt cấp cao và ký duyệt các văn kiện then chốt (kỳ công, bảng lương, kết quả thử việc, đề xuất điều chuyển/bổ nhiệm). **Tuyệt đối không cấp quyền tạo/sửa trực tiếp cấu trúc phân bổ lương (`Salary Structure Assignment - SSA`) cho CEO** để lách kiểm thử.
   - **Kế toán (Accounts User / Accounts Manager):** Đọc đối chiếu bảng lương đã ký và hạch toán/chi trả thực tế qua chứng từ `Payment Entry`, đối soát sổ phụ tạm ứng/quyết toán chi phí. Không tham gia vào nghiệp vụ nội bộ của HR.
   - **Quản trị kỹ thuật (IT / TLC Role Admin / System Manager):** Khởi tạo tài khoản `User`, phân vai trò kỹ thuật `Role`, hạ tầng và giám sát nhật ký kỹ thuật. **IT không sở hữu quyền phê duyệt nghiệp vụ nhân sự hay chi trả.**

2. **Ranh giới kỹ thuật trung thực (No Misleading Technical Admin Segregation Claim):**
   - Vai trò `System Manager` và `Administrator` trong Frappe Framework về mặt kiến trúc phần mềm sở hữu đặc quyền tối cao (`bypass` hoặc quyền truy cập toàn bộ `DocType`, `desk_access` và chạy script qua giao diện).
   - Hệ thống TLC **không đưa ra tuyên bố sai lệch** rằng `System Manager` hay quản trị IT thuần túy bị chặn kỹ thuật hoàn toàn khỏi việc đọc dữ liệu nếu nền tảng Frappe cho phép.
   - Thay vào đó, TLC áp dụng cơ chế:
     - Tách riêng vai trò tác nghiệp vận hành định kỳ `TLC Role Admin` (chỉ quản lý User, phân Role theo văn bản HR phê duyệt, theo dõi nhật ký Access Log/Error Log).
     - Ghi nhận `System Manager` là tài khoản quản trị hạ tầng / quy trình khẩn cấp (break-glass privilege), mọi truy cập và xuất dữ liệu đều lưu vết qua `Access Log`.

3. **Cơ chế bảo vệ dữ liệu lương (Salary Confidentiality & Row Scope):**
   - Trưởng nhà máy (`TLC Line Manager`) và Trưởng phòng ban chỉ nhìn thấy danh sách nhân sự thuộc cây phân cấp báo cáo của mình (`reporting tree`) thông qua hook kiểm soát phạm vi `role_experience.py`.
   - Các trường tiền lương trên `Employee` (`ctc`, `vn_insurance_salary`, `tlc_monthly_wage`) được khóa ở cấp độ quyền trường `permlevel = 1`. Chỉ có `TLC Payroll`, `TLC HR Lead`, `TLC Director` (chỉ đọc) và `System Manager` mới có quyền đọc ở mức này. Cán bộ HR nghiệp vụ chung (`TLC HR Officer`) hoặc Trưởng phòng ban **hoàn toàn không được phân quyền mức 1 trên các trường tiền lương**.
   - Chứng từ phiếu lương `Salary Slip` bị chặn ở tầng server qua hook `payroll_permissions.py`: người dùng không thuộc vai trò nghiệp vụ lương chỉ được đọc phiếu lương của chính mình ở trạng thái đã nộp (`docstatus = 1`).

4. **Khảo sát ẩn danh (Anonymous Survey Boundaries):**
   - Dữ liệu phản hồi khảo sát (`TLC Survey Campaign`) được tổng hợp độc lập trực tiếp vào bảng tần suất `TLC Survey Aggregate`.
   - Không lưu vết định danh nhân viên (`user_id`, `employee`), không lưu bộ câu trả lời kèm người gửi. Quản lý chỉ được xem kết quả tổng hợp khi khảo sát đã đóng và đạt ngưỡng tối thiểu $\ge 5$ phản hồi.

---

## 2. Ma trận vai trò, ứng dụng và ranh giới nghiệp vụ (Role Matrix)

| STT | Vai trò nghiệp vụ / Nhóm người dùng | Vai trò Frappe / TLC tương ứng | Ứng dụng mặc định (App) | URL / Workspace mặc định | Phạm vi dữ liệu dòng (Row Scope) | Quyền tác nghiệp được phép | Giới hạn lương & Khảo sát ẩn danh | Thẩm quyền phê duyệt / Cấp quyền |
|:---:|---|---|---|---|---|---|---|---|
| **1** | **Công nhân nhà máy (Worker)** | `Employee`, `Employee Self Service`, `TLC Self Service` | **Frappe HR** (`hrms`) | `/hrms/home` (Frappe HR App) | Bản thân (`Employee = own`) | Nộp đơn nghỉ phép, gửi giải trình chấm công, xác nhận đồng ý tăng ca, xem phiếu lương của mình, gửi yêu cầu dịch vụ nội bộ, tham gia khảo sát ẩn danh | Chỉ xem phiếu lương cá nhân đã ký; không xem lương người khác; chỉ gửi biểu quyết ẩn danh | HR khởi tạo khi tuyển dụng; IT tạo tài khoản User/Employee link |
| **2** | **Nhân viên văn phòng (Office Employee)** | `Employee`, `Employee Self Service`, `TLC Self Service` | **Frappe HR** (`hrms`) | `/hrms/home` (Frappe HR App) | Bản thân (`Employee = own`) | Tương tự công nhân; nộp công tác, tạm ứng, quyết toán chi phí, đặt phòng họp, mượn sách thư viện | Chỉ xem phiếu lương cá nhân đã phát hành; tham gia khảo sát trong phạm vi | HR khởi tạo khi tuyển dụng; IT kích hoạt tài khoản |
| **3** | **Trưởng Nhà máy 1 / 2 / 3 (Factory Heads)** | `TLC Line Manager`, `Leave Approver`, `Expense Approver`, `Employee Self Service` | **TLC HR** (`tlc_hr`) | `/desk/tlc-hr/tlc-quản-lý` (TLC Quản lý) | Nhân sự thuộc cây báo cáo của nhà máy (`reporting-tree scope`) | Duyệt đơn nghỉ phép, duyệt giải trình công, đề xuất tăng ca, xác nhận chốt kỳ công cấp cơ sở, phân ca sản xuất, duyệt yêu cầu công tác/chi phí đội ngũ | **Tuyệt đối không xem dữ liệu lương** của công nhân hay đồng nghiệp (chỉ xem lương bản thân); chỉ xem báo cáo khảo sát tổng hợp khi $\ge 5$ mẫu và đã đóng | Giám đốc / Ban Điều hành bổ nhiệm; HR lập hồ sơ; IT gán Role |
| **4** | **Trưởng phòng Hành chính (Office Manager)** | `TLC Line Manager`, `Leave Approver`, `Expense Approver`, `Employee Self Service` | **TLC HR** (`tlc_hr`) | `/desk/tlc-hr/tlc-quản-lý` (TLC Quản lý) | Nhân sự phòng Hành chính & dịch vụ phụ trách | Duyệt công việc, đơn nghỉ của nhân viên phòng; quản lý điều phối phòng họp, xe công tác, danh mục cấp phát văn phòng phẩm | Không truy cập dữ liệu tiền lương; chỉ xem lương của chính mình | Giám đốc bổ nhiệm; IT cấp quyền theo đề nghị của HR |
| **5** | **Chuyên viên Nhân sự (HR Officer)** | `TLC HR Officer`, `HR User`, `Employee Self Service` | **TLC HR** (`tlc_hr`) | `/desk/tlc-hr/tlc-nhân-sự` (TLC Nhân sự) & `TLC HR Hạn xử lý` | Toàn công ty (`Company-wide` cho hồ sơ nhân sự, công, phép, vòng đời) | Lập hồ sơ nhân viên, onboarding, separation, bảo hiểm, hợp đồng, theo dõi hạn xử lý công việc ToDo, kiểm soát chốt công | **Không có quyền truy cập trường lương mức 1** (`ctc`, `tlc_monthly_wage`, `vn_insurance_salary`); không lập/tính lương; quản trị chiến dịch khảo sát nhưng không xem phiếu bầu cá nhân | Trưởng phòng Nhân sự đề xuất; HR Lead duyệt; IT thực thi gán Role |
| **6** | **Trưởng bộ phận Nhân sự (HR Lead)** | `TLC HR Lead`, `HR Manager`, `HR User`, `Leave Approver`, `Employee Self Service` | **TLC HR** (`tlc_hr`) | `/desk/tlc-hr/tlc-nhân-sự` (TLC Nhân sự) & `TLC HR Hạn xử lý` | Toàn công ty (`Company-wide`) | Duyệt vòng 2 nghỉ phép, kiểm duyệt hồ sơ nhân sự, xác nhận giảm trừ gia cảnh, rà soát biến động lương, ký đối soát kỳ công, phối hợp lập bảng lương | **Có quyền xem và sửa trường lương mức 1**; đồng thẩm định biến động bảng lương; quản trị danh mục khảo sát | Ban Giám đốc bổ nhiệm; IT thực thi User/Role theo quyết định |
| **7** | **Chuyên viên Lương (Payroll Officer)** | `TLC Payroll`, `HR User`, `Employee Self Service` | **TLC HR** (`tlc_hr`) | `/desk/tlc-hr/tlc-tác-nghiệp-lương` (TLC Tác nghiệp lương) | Toàn công ty cho dữ liệu tính lương; tra cứu Employee | Khởi tạo bảng lương `Payroll Entry`, tính lương, nộp phân bổ cấu trúc lương (`SSA`), tạo khoản phụ cấp/giảm trừ `Additional Salary`, gửi bảng lương cho Giám đốc ký | **Quyền toàn diện trên phân hệ lương** (`rwcsx`); không duyệt hồ sơ kỷ luật hay bổ nhiệm nhân sự; không can thiệp phiếu khảo sát ẩn danh | Trưởng phòng Nhân sự đề xuất; Ban Giám đốc phê duyệt; IT gán Role |
| **8** | **Tổng Giám đốc (CEO / TLC Director)** | `TLC Director`, `Leave Approver`, `Expense Approver`, `Employee Self Service` | **TLC HR** (`tlc_hr`) | `/desk/tlc-hr/tlc-điều-hành` (TLC Điều hành) & `TLC CEO Chi phí` | Toàn công ty (`Company-wide`) | Ký duyệt kỳ công toàn công ty, **ký duyệt bảng lương** (`Payroll Entry`), phê duyệt kết quả thử việc, duyệt quyết định nhân sự cấp cao, xem biểu đồ chi phí | Đọc tổng thể chi phí lương gross/net và phiếu lương; **không có quyền tạo/sửa trực tiếp phân bổ lương SSA** (ngăn chặn thao túng chứng từ gốc) | Hội đồng Quản trị bổ nhiệm; IT khởi tạo tài khoản bảo mật cao |
| **9** | **Kế toán thanh toán / Kế toán trưởng (Accounts)** | `Accounts User` / `Accounts Manager`, `Employee Self Service` | **TLC HR** (`tlc_hr`) | `/desk/tlc-hr/tlc-kế-toán-chi-trả` (TLC Kế toán chi trả) | Toàn công ty đối với nghiệp vụ thanh toán, tài khoản và tạm ứng | Đọc bảng lương đã được Giám đốc ký, đối chiếu số liệu, tạo chứng từ thanh toán `Payment Entry`, quản lý tạm ứng nhân viên `Employee Advance` và quyết toán `Expense Claim` | Xem bảng lương và phiếu lương ở trạng thái xác nhận chi trả; không chỉnh sửa hồ sơ nhân sự hay chính sách lương | Giám đốc Tài chính / Ban Giám đốc đề xuất; IT cấp quyền kỹ thuật |
| **10** | **Quản trị hệ thống & Cấp quyền kỹ thuật (IT Admin)** | `TLC Role Admin`, `System Manager` | **TLC HR** (`tlc_hr`) | `/desk/tlc-hr/tlc-quản-trị-kỹ-thuật` (TLC Quản trị kỹ thuật) | Toàn bộ hệ thống kỹ thuật | Quản lý tài khoản `User`, phân vai trò kỹ thuật `Role`, quản lý `User Permission`, cấu hình hệ thống, theo dõi `Access Log`, khắc phục sự cố | **Không tham gia quy trình phê duyệt nghiệp vụ** (nghỉ phép, kỳ công, bảng lương, chi phí); quyền hạn dữ liệu là đặc quyền kỹ thuật (technical break-glass) | Ban Giám đốc phê duyệt bổ nhiệm nhân sự IT; thực thi theo Ticket HR |

---

## 3. Ma trận Phân định Trách nhiệm (RACI Matrix) giữa Nhân sự (HR) và Công nghệ Thông tin (IT)

Để đảm bảo tuân thủ kiểm soát nội bộ và an toàn thông tin, trách nhiệm giữa HR và IT được quy định chặt chẽ:

| Quy trình / Nhiệm vụ quản trị | Nhân sự (HR Lead / HR Officer) | Quản trị viên Kỹ thuật (IT Admin / Role Admin) | Người sử dụng / Trưởng bộ phận | Ban Giám đốc (CEO / CFO) | Ghi chú kiểm soát |
|---|:---:|:---:|:---:|:---:|---|
| **Yêu cầu tuyển dụng và tiếp nhận nhân viên mới (Joiner)** | **A / R** | **C / I** | C | I | HR lập hồ sơ Onboarding, xác định chức danh, phòng ban và cấp phê duyệt. IT nhận thông báo để cấp email và tài khoản. |
| **Khởi tạo tài khoản người dùng (User Provisioning)** | C | **A / R** | I | I | IT thực hiện tạo tài khoản `User` trên Frappe dựa trên mã nhân viên và email chính thức đã được HR xác nhận. |
| **Phân quyền vai trò nghiệp vụ (Role Assignment)** | **A** | **R** | I | I | **HR sở hữu thẩm quyền nghiệp vụ:** quyết định vai trò nào được gán cho nhân viên. **IT là người thực thi kỹ thuật**, không tự ý gán thêm quyền khi chưa có phê duyệt của HR/Giám đốc. |
| **Điều chuyển phòng ban, vị trí và thay đổi cấp duyệt (Mover)** | **A / R** | **R** (kỹ thuật) | C | I | HR ban hành quyết định điều chuyển `Employee Transfer` và cập nhật báo cáo trực tiếp `reports_to`/`TLC Organization Reporting Line`. IT điều chỉnh nhóm phân quyền nếu có thay đổi phạm vi hệ thống. |
| **Thay đổi thông tin nhạy cảm của nhân viên (CCCD, Ngân hàng, Mã số thuế)** | **A / R** | I | C | I | Thực hiện qua phiếu `TLC Employee Change Request` kèm chứng từ gốc. Hệ thống tự động chặn sửa trực tiếp trên form `Employee`. |
| **Nghỉ việc và thu hồi quyền truy cập (Leaver / Revocation)** | **A / R** | **R** (kỹ thuật) | C | I | Khi hoàn tất thủ tục nghỉ việc `Employee Separation` tại ngày làm việc cuối cùng: HR xác nhận hoàn tất; hệ thống tự động vô hiệu hóa tài khoản `User` (`enabled = 0`) và xóa phiên làm việc (`clear_sessions`). IT thu hồi thiết bị phần cứng và tài khoản ngoài hệ thống. |
| **Phê duyệt phân bổ cấu trúc lương (`Salary Structure Assignment`)** | **A / R** (HR Lead) | I | I | I | Chuyên viên lương lập, HR Lead duyệt. Tuyệt đối không cho phép IT hoặc CEO sửa trực tiếp cấu trúc lương. |
| **Ký duyệt bảng lương tháng (`Payroll Entry`)** | C / R (Lập bảng) | I | I | **A** (Ký duyệt) | Chuyên viên lương lập, HR Lead rà soát sai lệch; CEO ký số/ký điện tử. IT không có quyền can thiệp dữ liệu bảng lương. |
| **Thực hiện chi trả ngân hàng và kế toán lương** | I | I | I | **A / R** (Kế toán/CFO) | Kế toán kiểm tra chứng từ đã được CEO duyệt để lập lệnh thanh toán và nhập bằng chứng chi trả. |
| **Kiểm toán quyền truy cập định kỳ (Access Review Audit)** | **A** (Chủ trì nghiệp vụ) | **R** (Xuất báo cáo & đối soát) | C | I | Định kỳ hàng quý: IT xuất danh sách User và vai trò hiện hữu (`Access Log`, `Has Role`); HR Lead rà soát đối chiếu với danh sách nhân sự hiện hành để thu hồi quyền thừa. |

*Chú thích RACI:*
- **R (Responsible):** Người trực tiếp thực hiện công việc.
- **A (Accountable):** Người chịu trách nhiệm phê duyệt cuối cùng và sở hữu nghiệp vụ.
- **C (Consulted):** Người được tham vấn ý kiến hai chiều.
- **I (Informed):** Người được nhận thông báo thông tin kết quả.

---

## 4. Quy trình Vận hành Vòng đời Tài khoản (Joiner - Mover - Leaver & Audit)

### 4.1. Quy trình tiếp nhận (Joiner Process)
1. **Thiết lập hồ sơ:** HR tạo mới bản ghi `Employee` với các trường thông tin cơ bản: mã nhân viên, phòng ban, chức danh, quản lý trực tiếp (`reports_to`), người duyệt nghỉ phép (`leave_approver`), người duyệt công tác/chi phí.
2. **Kích hoạt tài khoản:**
   - Hệ thống tự động (hoặc IT thực hiện) tạo tài khoản `User` với email công vụ của nhân viên.
   - Vai trò mặc định cho mọi nhân sự mới: `Employee`, `Employee Self Service`, `TLC Self Service`.
   - Điều hướng đăng nhập: người dùng được chuyển mặc định vào ứng dụng **Frappe HR** (`/hrms/home`) để tự phục vụ.
3. **Cấp quyền vai trò quản lý / chuyên trách:** Nếu nhân sự đảm nhiệm vai trò quản lý (Trưởng nhà máy, Trưởng phòng, Chuyên viên HR, Kế toán), HR Lead gửi phiếu đăng ký vai trò; IT Admin gán vai trò tương ứng trong danh mục `TLC Roles`. Sau khi gán, hệ thống tự động cập nhật `default_app = 'tlc_hr'` và điều hướng về Desk Workspace tương ứng.

### 4.2. Quy trình điều chuyển & thay đổi vai trò (Mover Process)
1. **Điều chuyển tổ chức:** HR lập chứng từ `Employee Transfer` hoặc `TLC Organization Change`. Khi chứng từ có hiệu lực, các thông tin về phòng ban, cấp quản lý phê duyệt và phạm vi cây báo cáo được cập nhật đồng bộ.
2. **Cập nhật quyền hạn:**
   - Nếu nhân viên chuyển từ quản lý về nhân viên thông thường: HR gửi yêu cầu thu hồi vai trò `TLC Line Manager`. Hệ thống tự động chuyển `default_app` về `hrms` và xóa liên kết workspace quản lý.
   - Nếu nhân viên thăng chức lên quản lý: IT gán bổ sung `TLC Line Manager` và cấp duyệt theo quyết định bổ nhiệm của HR/CEO.
   - Không phát sinh mã nhân viên mới khi điều chuyển nội bộ TLC (đảm bảo tính toàn vẹn dữ liệu xuyên suốt).

### 4.3. Quy trình nghỉ việc và thu hồi quyền (Leaver / Access Revocation)
1. **Quy trình hồ sơ:** HR lập chứng từ `Employee Separation` ghi rõ ngày làm việc cuối cùng và ngày có hiệu lực nghỉ việc.
2. **Cơ chế thu hồi quyền tự động được kiểm soát (Automated Hardened Revocation):**
   - Khi HR bấm nút **Hoàn tất thủ tục nghỉ việc** trên giao diện Desk:
     - Trạng thái `Employee` chuyển thành `Left`.
     - Tài khoản `User` liên kết bị vô hiệu hóa ngay lập tức: `frappe.db.set_value("User", user_id, "enabled", 0)`.
     - Toàn bộ phiên đăng nhập hiện hữu của tài khoản bị hủy ngay lập tức trên Redis/Database qua hàm `frappe.sessions.clear_sessions(user=user_id, keep_current=False)`.
   - Cơ chế này đảm bảo người lao động không thể tiếp tục truy cập vào cả cổng ESS lẫn giao diện Desk sau khi đã bàn giao nghỉ việc.

### 4.4. Quy trình kiểm toán và rà soát đặc quyền (Privilege Audit & Logging)
1. **Theo dõi truy cập (`Access Log`):** Mọi hành động xuất dữ liệu (Export CSV/Excel), xem báo cáo tổng hợp khảo sát hay mở danh sách nhạy cảm đều được ghi nhận vào `Access Log` với đầy đủ định danh người thực hiện, thời gian, loại tệp và bộ lọc.
2. **Rà soát định kỳ hàng quý:**
   - HR Lead phối hợp cùng IT Admin kiểm tra danh sách tài khoản đang hoạt động (`User.enabled = 1`) so khớp với bảng lương tháng gần nhất.
   - Bất kỳ tài khoản nào không có tên trên danh sách nhân sự hiện hành phải được khóa ngay lập tức.
   - Kiểm tra các tài khoản có vai trò đặc quyền (`System Manager`, `TLC Role Admin`, `TLC Director`), yêu cầu văn bản phê duyệt bổ nhiệm có giá trị hiệu lực.

---

## 5. Hiện trạng kiểm soát kỹ thuật và các điểm cần lưu ý (Enforced vs Remaining Gaps)

Để đảm bảo tính minh bạch, các biện pháp kiểm soát được phân định rõ ràng giữa **Cơ chế kỹ thuật tự động đã thực thi** và **Quy trình kiểm soát hành chính cần giám sát**:

| Cơ chế kiểm soát | Trạng thái kỹ thuật | Cách thức vận hành hiện tại |
|---|:---:|---|
| **Khóa trường tiền lương trên `Employee` (`ctc`, `wage`, `insurance`)** | **ĐÃ THỰC THI (Enforced)** | Cấu hình `Property Setter` chuyển các trường nhạy cảm sang `permlevel = 1`. Cán bộ không có vai trò nghiệp vụ lương (`TLC Payroll`, `TLC HR Lead`, `TLC Director`, `System Manager`) hoàn toàn không đọc/xuất được các trường này qua API lẫn giao diện form/list. |
| **Giới hạn phạm vi dữ liệu nhân viên theo Nhà máy / Phòng ban** | **ĐÃ THỰC THI (Enforced)** | Hook `role_experience.py` chặn tầng SQL query (`query_conditions`) và kiểm tra từng bản ghi (`has_permission`). Trưởng nhà máy chỉ thấy nhân sự trong cây báo cáo của mình; không thể mở hay xem nhân viên nhà máy khác. |
| **Chặn đọc phiếu lương `Salary Slip`** | **ĐÃ THỰC THI (Enforced)** | Hook `payroll_permissions.py` kiểm soát chặt: người dùng thông thường chỉ đọc phiếu lương của chính mình ở trạng thái `docstatus = 1`. Quản lý nhà máy không đọc được phiếu lương công nhân. |
| **Điều hướng ứng dụng và Workspace theo vai trò** | **ĐÃ THỰC THI (Enforced)** | Module `role_navigation.py` tự động áp dụng `default_app` và `default_workspace` khi người dùng đăng nhập hoặc khi seed dữ liệu. Nhân viên thông thường vào thẳng cổng Frappe HR; cấp quản lý và chuyên trách vào đúng Desk Workspace được phân quyền. |
| **Thu hồi quyền tức thì khi hoàn tất nghỉ việc** | **ĐÃ THỰC THI (Enforced)** | Hook `lifecycle.complete_boarding` tự động khóa User và xóa toàn bộ session khi hồ sơ `Employee Separation` được HR xác nhận hoàn tất. |
| **Bảo vệ tính ẩn danh của khảo sát nội bộ** | **ĐÃ THỰC THI (Enforced)** | Module `survey.py` tổng hợp trực tiếp vào bộ đếm không định danh; không lưu liên kết phiếu bầu; áp dụng ngưỡng bảo vệ quyền riêng tư $\ge 5$ phản hồi. |
| **Quy trình phê duyệt cấp tài khoản và gán Role** | **QUY TRÌNH HÀNH CHÍNH (Administrative Control)** | Cần biên bản đề nghị từ HR Lead gửi IT Admin trước khi IT thao tác gán Role trên giao diện User. Về mặt kỹ thuật, Frappe cho phép IT Admin gán Role trực tiếp nếu đã có quyền ghi trên `User`; do đó kiểm soát này phụ thuộc vào quy trình phê duyệt ngoài hệ thống (ticket / văn bản) và kiểm toán định kỳ qua `Access Log`. |
| **Ngăn ngừa lạm dụng quyền của tài khoản `System Manager`** | **GIÁM SÁT HẬU KIỂM (Audit Logging)** | `System Manager` là đặc quyền framework cao nhất, không thể khóa bằng permission thông thường mà không làm gãy các tác vụ bảo trì hệ thống. Kiểm soát duy nhất là hạn chế tối đa số lượng tài khoản cấp quyền `System Manager`, bắt buộc bật xác thực 2 lớp (2FA) và định kỳ rà soát `Access Log`. |
