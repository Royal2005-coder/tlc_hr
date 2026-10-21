# Kiến trúc `tlc_hr`

`tlc_hr` là app Frappe chạy trên Frappe HR v16 (HRMS), ERPNext v16 và `erpnextvn`. App không sửa các app gốc. Phần nghiệp vụ TLC được tổ chức theo Clean Architecture, giống cách làm trong [TinyBigCorp](https://github.com/CkoThuw11/TinyBigCorp). Frappe đóng vai giao diện, cơ sở dữ liệu và workflow engine; luật nghiệp vụ của TLC nằm trong lớp riêng và test được mà không cần site.

## Các lớp

```
[ Desk / app /hrms / REST / bench tlc ]  -> interface/      controller doctype, doc_events, API, lệnh bench
                 ↓
           application/                     use case: <Phân hệ>Service(repo, notifier, clock)
                 ↓
             domain/                         entity, rule, DomainError, port (ABC) — thuần Python
                 ↑
         infrastructure/                     Frappe…Repository cài port; customizing applier
contracts/   Pydantic v2 strict: Command, Result, schema YAML
customizing/ YAML khai báo cấu hình (vai trò, trường, quyền, workflow, workspace, ca, tham số luật…)
```

| Lớp | Được import | Không được import |
|---|---|---|
| `domain` | thư viện chuẩn, `contracts` | `frappe`, `erpnext`, `hrms`, `application`, `infrastructure`, `interface`, `setup` |
| `application` | `domain`, `contracts` | `frappe`, `infrastructure`, `interface`, `setup` |
| `contracts` | `pydantic` | `frappe`, `infrastructure`, `interface` |
| `infrastructure` | tất cả, kể cả `frappe` | `interface` |
| `interface` | tất cả | — |

`tlc_hr/tests/unit/test_architecture.py` đọc mã nguồn (AST) và báo lỗi khi một lớp import sai.

## Nguyên tắc (SOLID áp vào Frappe)

- **SRP.** Mỗi controller chỉ chuyển Frappe Document thành Command, gọi service, rồi đổi lỗi domain thành lỗi Frappe. Luật nằm ở `domain`, phần ghi đọc nằm ở `infrastructure`.
- **OCP.** Thêm một loại cấu hình là thêm một `ResourceApplier` mới vào `engine.appliers()`, không sửa applier cũ. Thêm một phân hệ là thêm package mới trong từng lớp.
- **LSP / ISP.** Port nhỏ, viết theo nhu cầu của use case, ví dụ `IOvertimeRepository`, `INotifier`, `IClock`. Port không phải bản sao API của Frappe.
- **DIP.** Service nhận port qua `__init__`. Ở interface, bản cài Frappe được gắn vào; trong unit test, bản in-memory được gắn vào.
- **Data contract.** Đầu vào của use case là Command `strict=True` (không ép kiểu ngầm, không nhận khoá lạ). Domain không nhận Frappe Document.
- **Lỗi.** Domain ném `DomainError(code, message)`. Interface đổi lỗi đó thành `frappe.ValidationError`, và đổi `NotAllowed` thành `frappe.PermissionError`. Người dùng thấy thông báo tiếng Việt; mã lỗi dùng để tra cứu.

## Thêm một phân hệ (công thức)

1. **Story.** Viết `tlc-hr-platform/uat/stories/<phân_hệ>.yaml`, gồm vai trò, câu chuyện và AC Given/When/Then.
2. **Cấu hình.** Workflow, trường thêm, quyền, thẻ và workspace khai báo trong `tlc_hr/customizing/`. Chạy `bench --site <site> tlc config plan` để xem diff.
3. **Domain.** Tạo `domain/<phân_hệ>/` gồm `entities.py`, `rules.py`, `errors.py`, `ports.py`. Viết unit test luật trong `tests/unit/`.
4. **Application.** Tạo `application/<phân_hệ>.py` chứa service nhận port. Unit test dùng repository in-memory.
5. **Contracts.** Tạo `contracts/<phân_hệ>.py` cho Command và Result.
6. **Infrastructure.** Tạo `infrastructure/frappe/<phân_hệ>.py` cài đặt port bằng `frappe.get_all`, `frappe.get_doc`…
7. **Interface.** Hook trong `hooks.py` trỏ tới adapter `interface/<phân_hệ>.py`. Controller doctype chỉ gọi adapter.
8. **Test tích hợp.** Viết `tests/test_<phân_hệ>.py` (IntegrationTestCase trên site demo).
9. **UAT.** Viết `uat/journeys/<phân_hệ>.py` theo hành trình vai trò, có video.

## Kim tự tháp test

| Tầng | Ở đâu | Cần site | Chạy |
|---|---|---|---|
| Unit: luật, service, contract, kiến trúc | `tlc_hr/tests/unit/` | Không | `python -m unittest discover -s tlc_hr/tests/unit -t .` (cả trong CI GitHub) |
| Tích hợp | `tlc_hr/tests/test_*.py` | Có (seed demo) | `bench --site <site> run-tests --app tlc_hr` |
| E2E / UAT | `tlc-hr-platform/uat` | Có | `uat/run_uat.sh --reset` (Playwright, video, HTML offline) |

## Trạng thái chuyển đổi

- **A0 (đã xong).** Đã có khung lớp, cấu hình khai báo YAML, applier có plan/diff, lệnh `bench tlc` và test kiến trúc. `setup/*.py` chỉ còn hằng số.
- **A1.** Chuyển nghiệp vụ đã có sang `domain`/`application`/`infrastructure`: nghỉ phép, giải trình, tăng ca, chốt công. Hiện các phần này nằm trong `events.py`, `workflow_rules.py`, `attendance/*.py`, `vn/*.py` và controller doctype. Phần lương (W2) trở đi viết thẳng theo kiến trúc này.
