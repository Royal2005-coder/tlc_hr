# Vận hành, kiểm thử, bàn giao

Repo hạ tầng: `tlc-hr-platform` gồm `apps.json`, `scripts/`, `deploy/k8s`, `deploy/jobs` và `uat/`. Môi trường thử chạy trên k3s, namespace `tlc-hr`, site `tlc-hr.local`.

## Build và triển khai

```
cd tlc-hr-platform
scripts/build.sh                  # image = frappe_docker layered + apps.json (frappe/erpnext version-16, fork hrms, erpnextvn, tlc_hr main)
kubectl apply -k deploy/k8s       # mọi pod (backend, worker, scheduler, frontend, websocket) dùng cùng tag
scripts/job.sh migrate            # bench migrate → áp YAML customizing
scripts/job.sh test               # bench run-tests --app tlc_hr
```

Thử nhanh một thay đổi mà chưa build image: chạy `~/tlc-hr/hot-sync.sh`. Lệnh này chép `tlc_hr` vào các pod backend, worker, scheduler và frontend. Mọi pod chạy Python đều phải nhận code mới. Nếu sót pod scheduler, cache hook bị dựng lại bằng code cũ và desk mất `tlc_workflow.js` (lỗi đã gặp ngày 21/10).

## Kiểm tra sau mỗi thay đổi

```
kubectl -n tlc-hr exec deploy/backend -- bench --site tlc-hr.local tlc config validate # kiểm tra schema contract
kubectl -n tlc-hr exec deploy/backend -- bench --site tlc-hr.local tlc config plan     # phải: Không có thay đổi
kubectl -n tlc-hr exec deploy/backend -- bench --site tlc-hr.local tlc config export <kind> [name] # xuất cấu hình ra YAML
kubectl -n tlc-hr exec deploy/backend -- bench --site tlc-hr.local tlc doctor        # phải: toàn OK
```

## Test

- **Unit (không cần site).** `python -m unittest discover -s tlc_hr/tests/unit -t .`, chạy trong thư mục repo `tlc_hr`. CI GitHub (`.github/workflows/ci.yml`) chạy bước này kèm ruff.
- **Tích hợp.** `bench --site tlc-hr.local run-tests --app tlc_hr`, chạy trên site đã seed demo.
- **UAT có video.** Chạy `tlc-hr-platform/uat/run_uat.sh --reset` (`ONLY=leave,overtime,attendance` để chạy một số phân hệ).
  - Kết quả nằm trong `uat/out/<RUN_ID>/`: `results.json`, Excel, video MP4 và `UAT_TLC_HRM_<RUN_ID>_offline.html`. File HTML này tự chứa đủ, gửi đi xem offline được.
  - Thứ tự reset demo: nghỉ phép → kỳ công → tăng ca. Phải reset kỳ công trước, vì tháng đã khoá sẽ chặn dữ liệu tăng ca mẫu.

## Dữ liệu demo

- **Seed.** `bench --site <site> tlc seed run` tạo công ty, phòng ban, 60 người, tài khoản, lịch nghỉ, ca, chấm công từ đầu tháng trước và tăng ca mẫu. Lệnh idempotent.
- **Mật khẩu demo.** Lấy từ biến môi trường `DEMO_PASSWORD` (Secret `tlc-hr`, key `demo-password`); không có trong git.
- **Reset.** Các lệnh `reset-*` chỉ chạy trên site có `allow_tests`.

## Lỗi đã gặp và cách xử lý

| Hiện tượng | Nguyên nhân | Xử lý |
|---|---|---|
| Từ chối đơn không hỏi lý do, server báo "Thiếu lý do" | Cache hook bị pod chạy code cũ dựng lại, nên thiếu `tlc_workflow.js` | Build image cho mọi pod. Khi hot-sync phải gồm scheduler, rồi `bench clear-cache` |
| Duyệt giải trình báo trùng chấm công | Form app không có ca nên HRMS tạo bảng công mới | Đã sửa: giải trình tự lấy ca của ngày đó (`events.attendance_request_validate`) |
| Seed tháng trước toàn "Có mặt" | Số ngẫu nhiên lệch khi chạy lại seed | Đã sửa: kết quả cố định theo người và ngày |
| Thẻ workspace trống | Khối nội dung phải gọi theo nhãn dòng con (tên thẻ bỏ "TLC ") | Applier workspace đã xử lý |
| Lỗi DDL khi apply schema | MariaDB ngầm commit DDL (Custom Field, DocType), rollback không khôi phục cột SQL | Phục hồi site từ bản snapshot/backup trước khi chạy lại migrate |

## Bảo mật

- Repo `tlc_hr` và `tlc-hr-platform` để **public**: không commit mật khẩu, khoá API, dữ liệu thật hay catalogue BRD nội bộ. Catalogue chỉ để ở máy chạy báo cáo (`TLC_CATALOG`).
- Khoá Mistral (W7) chỉ để trong Secret `tlc-hr-ai`.
## Ma trận phân quyền và điều hướng vai trò vận hành

Hồ sơ chuẩn hóa chi tiết về ma trận vai trò, ứng dụng mặc định, URL workspace, thẩm quyền phê duyệt và quy trình JML (Joiner - Mover - Leaver) được ban hành tại:
- **Tài liệu chuẩn hóa chính thức:** `auto/OPERATING_ROLE_MATRIX.md` (hoặc `tlc_hr/docs/OPERATING_ROLE_MATRIX.md`).
- **Nguyên tắc cốt lõi:**
  1. **Tách bạch HR & IT:** HR sở hữu phê duyệt phân quyền và cơ cấu tổ chức; IT thực thi kỹ thuật tài khoản User và Role, không có thẩm quyền ký duyệt nghiệp vụ nhân sự/lương.
  2. **Bảo vệ dữ liệu tiền lương:** Cán bộ không có vai trò nghiệp vụ lương (`TLC Payroll`, `TLC HR Lead`, `TLC Director`, `System Manager`) không có quyền đọc trường lương mức 1 (`ctc`, `tlc_monthly_wage`, `vn_insurance_salary`). Giám đốc đọc đối chiếu tổng chi phí và phiếu lương, không tạo/sửa trực tiếp phân bổ lương `Salary Structure Assignment (SSA)`.
  3. **Ranh giới đặc quyền kỹ thuật:** Không tuyên bố sai lệch rằng `System Manager` bị chặn hoàn toàn về mặt kỹ thuật; thay vào đó áp dụng cơ chế giám sát qua `Access Log`, xác thực 2 lớp và phân tách vai trò tác nghiệp định kỳ `TLC Role Admin`.