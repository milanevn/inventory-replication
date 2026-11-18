# Đóng góp

## Nhánh

`main` lúc nào cũng phải chạy được và test xanh. Không ai push thẳng lên `main`; mọi thay đổi vào qua pull request.

Mỗi việc làm trên một nhánh tách từ `main`, đặt tên theo mẫu `<loại>/<phạm-vi>-<mô-tả-ngắn>`:

- viết thường, không dấu, các từ nối bằng dấu gạch ngang;
- có issue thì thêm số issue sau loại, ví dụ `feat/12-membership-ping`;
- phạm vi nên trùng tên module: `membership`, `failover`, `triggers`, `client`, `recovery`, `faults`, `gui`, `cli`, `link`, `store`, `proto`, `docs`.

| Loại | Dùng khi | Ví dụ |
|---|---|---|
| `feat` | thêm chức năng | `feat/membership-ping-quorum` |
| `fix` | sửa lỗi | `fix/link-heartbeat-timeout` |
| `test` | chỉ thêm hoặc sửa test | `test/recovery-mat-duoi-nhat-ky` |
| `docs` | tài liệu, báo cáo | `docs/operations-lan` |
| `refactor` | sửa cấu trúc code, không đổi hành vi | `refactor/store-tach-meta` |
| `chore` | cấu hình, CI, script | `chore/ci-cache-pip` |

Nhánh nên sống ngắn, vài ngày là merge, merge xong thì xóa. Trước khi mở PR, rebase lên `main` mới nhất:

```bash
git switch main && git pull
git switch -c feat/triggers-interval-count
# code, commit
git fetch origin
git rebase origin/main
git push -u origin feat/triggers-interval-count
```

## Commit

Theo Conventional Commits: `<loại>(<phạm vi>): <mô tả>`. Mô tả viết tiếng Việt, bắt đầu bằng chữ thường, không có dấu chấm cuối, dưới 72 ký tự.

```
feat(membership): ping song song mọi node mỗi 0.5 giây
fix(link): giữ acked_lsn khi đích trả UNAVAILABLE
test(recovery): thêm ca bản chính mất đuôi nhật ký
docs(operations): thêm cách mở firewall trên LAN
```

PR được merge kiểu squash, nên tiêu đề PR sẽ thành commit trên `main`. Đặt tiêu đề PR theo đúng mẫu trên.

## Pull request

1. Chạy `pytest` trên máy mình, toàn bộ phải xanh. CI sẽ chạy lại `pytest` trên GitHub.
2. Mở PR vào `main` và điền mẫu PR.
3. Cần một người khác duyệt. Không tự duyệt PR của mình.
4. CI đỏ thì không merge.
5. Giữ PR nhỏ, khoảng dưới 300 dòng thay đổi. Việc lớn thì chia thành nhiều PR.

Một phần việc được coi là xong khi:

- test chấp nhận của phần đó xanh (đã xóa dòng `pytestmark = pytest.mark.todo(...)`), chạy 3 lần liên tiếp không lần nào đỏ, và toàn bộ `pytest` vẫn xanh;
- demo được bằng GUI hoặc CLI;
- PR đã được duyệt và merge;
- đã viết phần báo cáo của mình.

## File dùng chung

Mỗi người chủ yếu sửa module của mình. Docstring đầu mỗi module và các comment `TODO(TVx)` ghi rõ phần nào của ai. Những file dưới đây nhiều phần cùng dựa vào, nên báo trong nhóm trước khi sửa:

- `proto/dstock.proto`: chỉ thêm field hoặc RPC, không đổi và không xóa cái cũ. Sửa xong chạy `python scripts/gen_proto.py`, commit cả file sinh ra trong `dstock/rpc/`, PR gắn nhãn `contract`.
- `store.py`, `oplog.py`, `node.py`, `domain.py`, `schema.sql`: phần lõi.
- `services.py`, `replication/link.py`, `client.py`: mỗi file có đoạn của vài người khác nhau, chỉ sửa đúng đoạn `TODO` của mình.

Đổi một quyết định thiết kế thì bàn trong nhóm trước, rồi sửa mục "Quyết định thiết kế" trong [docs/architecture.md](docs/architecture.md) ngay trong PR đó, gắn nhãn `decision`.

## Test

```bash
pytest                         # test lõi, phải xanh (45 passed, 42 skipped)
pytest --run-todo -k tv3       # test chấp nhận của phần TV3
pytest --run-optional          # thêm test của phần tùy chọn
pytest -x -q tests/test_store.py::test_req_id_trung_khong_ghi_lai
```

Viết test mới thì dùng fixture `make_cluster` (`tests/harness.py`). Fixture này dựng 4 node ngay trong pytest với cổng ngẫu nhiên, không đụng tới cụm đang chạy trên máy.

## Lưu ý khi viết code

- Thread chạy nền phải tạo bằng `node.spawn()` và thoát khi `node.stopping` được bật. Nếu không, lúc tắt node có thể đóng kênh gRPC đúng khi thread khác đang gọi qua nó, làm treo cả tiến trình.
- Code sửa `epoch`, `primary` hoặc `members` trong meta phải giữ `node.role_lock`.
- Ngay sau khi node khởi động lại, lời gọi gRPC đầu tiên có thể trả `UNAVAILABLE`. Code và test nên thử lại thay vì kết luận node đã chết.
- Trong GUI, chỉ thread chính được đụng vào widget Tkinter.

## Cài đặt GitHub (làm một lần)

- Branch protection cho `main`: bật "Require a pull request before merging" với 1 approval, và "Require status checks to pass" với job `test`.
- Settings, General: chỉ bật "Allow squash merging", bật "Automatically delete head branches".
- Xong mỗi mốc thì gắn tag trên `main` (`m1`, `m2`, ...) để quay lại được bản demo của mốc đó.

## Trên Windows

- Nên clone vào đường dẫn không dấu, ví dụ `D:\dstock`.
- Cổng 7001 đến 7004 bị chiếm thì chạy `python scripts/stop_cluster.py`, hoặc `netstat -ano | findstr 700` để tìm tiến trình cũ.
- Các lệnh cần chạy mỗi lần mở lại dự án và cách làm lại từ đầu: xem mục "Mở lại dự án" và "Làm lại từ đầu" trong [README](README.md).
