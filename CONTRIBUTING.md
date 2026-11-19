# Đóng góp

## Nhánh

`main` lúc nào cũng phải chạy được và test xanh. Không ai push thẳng lên `main`; mọi thay đổi vào qua pull request.

Mỗi việc một nhánh ngắn: tạo từ `main` mới nhất, mở PR, merge xong thì nhánh tự bị xóa. Việc tiếp theo tạo nhánh mới, kể cả khi cùng module.

Tên nhánh: `<loại>/<phạm vi>-<mô tả>`, viết thường, không dấu, nối bằng gạch ngang.

- `<loại>` giống loại commit: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.
- `<phạm vi>` là module chính bị sửa: `failover`, `membership`, `link`, `triggers`, `client`, `recovery`, `faults`, `gui`, `proto`, `docs`, …
- `<mô tả>` 2–4 từ nói việc đó làm gì.

```
feat/failover-promote
feat/membership-ping
feat/link-heartbeat
feat/triggers-interval
fix/link-stale-epoch
test/recovery-mat-duoi
docs/demo-cat-kenh
```

Làm một việc:

```bash
git switch main && git pull
git switch -c feat/membership-ping
# code, commit
git push -u origin feat/membership-ping   # rồi mở PR trên GitHub
```

Trong lúc chờ duyệt mà `main` có thay đổi mới, hoặc PR báo xung đột:

```bash
git fetch origin
git merge origin/main          # lấy phần người khác đã merge, sửa xung đột nếu có
pytest
git push
```

Dùng `git merge`, không dùng `git rebase` trên nhánh đã push. Giữ nhánh ngắn: nhánh sống quá một tuần thì nên tách việc nhỏ hơn. PR đã merge thì về `main`, `git pull` rồi tạo nhánh mới cho việc sau; xóa nhánh cũ trên máy bằng `git branch -d <tên nhánh>`.

## Commit

Theo Conventional Commits: `<loại>(<phạm vi>): <mô tả>`. Mô tả viết tiếng Việt, bắt đầu bằng chữ thường, không có dấu chấm cuối, dưới 72 ký tự.

```
feat(membership): ping song song mọi node mỗi 0.5 giây
fix(link): giữ acked_lsn khi đích trả UNAVAILABLE
test(recovery): thêm ca bản chính mất đuôi nhật ký
docs(operations): thêm cách mở firewall trên LAN
```

PR được merge bằng merge commit, nên mọi commit trên nhánh đều đi vào lịch sử của `main`. Vì vậy commit nào cũng phải theo mẫu trên, và tiêu đề PR cũng vậy.

## Pull request

1. Chạy `pytest` trên máy mình, toàn bộ phải xanh. CI sẽ chạy lại `pytest` trên GitHub.
2. Mở PR từ nhánh của việc vào `main` và điền mẫu PR. Xong một việc là mở PR, không đợi làm hết module.
3. Cần một người khác duyệt. Không tự duyệt PR của mình.
4. CI đỏ thì không merge.
5. Giữ PR nhỏ, khoảng dưới 300 dòng thay đổi. Việc lớn thì chia thành nhiều PR.

Một phần việc được coi là xong khi:

- đã xóa dấu `@pytest.mark.todo` của các test chấp nhận thuộc phần việc đó, các test này chạy 3 lần liên tiếp không lần nào đỏ, và toàn bộ `pytest` vẫn xanh;
- demo được bằng GUI hoặc CLI;
- PR đã được duyệt và merge.

## File dùng chung

Docstring đầu mỗi module và các comment `TODO` ghi rõ phần nào còn phải làm. Những file dưới đây nhiều phần cùng dựa vào, nên báo trong nhóm trước khi sửa:

- `proto/dstock.proto`: chỉ thêm field hoặc RPC, không đổi và không xóa cái cũ. Sửa xong chạy `python scripts/gen_proto.py`, commit cả file sinh ra trong `dstock/rpc/`, PR gắn nhãn `contract`.
- `store.py`, `oplog.py`, `node.py`, `domain.py`, `schema.sql`: phần lõi.
- `services.py`, `replication/link.py`, `client.py`: mỗi file có đoạn `TODO` thuộc vài module khác nhau, chỉ sửa đúng đoạn của module mình đang làm.

Đổi một quyết định thiết kế thì bàn trong nhóm trước, rồi sửa mục "Quyết định thiết kế" trong [docs/architecture.md](docs/architecture.md) ngay trong PR đó, gắn nhãn `decision`.

## Test

```bash
pytest                         # phải xanh: không có test nào failed
pytest --run-todo -k triggers  # chỉ test chấp nhận của triggers
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
- Settings, General: chỉ bật "Allow merge commits", bật "Automatically delete head branches" để nhánh của việc tự bị xóa sau khi merge.

## Trên Windows

- Nên clone vào đường dẫn không dấu, ví dụ `D:\inventory-replication`.
- Cổng 7001 đến 7004 bị chiếm thì chạy `python scripts/stop_cluster.py`, hoặc `netstat -ano | findstr 700` để tìm tiến trình cũ.
- Các lệnh cần chạy mỗi lần mở lại dự án và cách làm lại từ đầu: xem mục "Mở lại dự án" và "Làm lại từ đầu" trong [README](README.md).
