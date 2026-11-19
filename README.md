# inventory-replication

Đồ án môn Các hệ thống phân tán, đề tài 8: xây dựng ứng dụng cập nhật lan truyền với dữ liệu là quản lý nhập - xuất - tồn hàng hóa.

```
Client <-> N1 ---- ngay lập tức ----> N2 ---- sau n lần cập nhật ----> N4
            \
             +---- sau n giây ------> N3
```

- N1 là bản chính và nhận mọi lệnh ghi. Mỗi phiếu được kiểm tra, đánh số thứ tự LSN và ghi vào SQLite trong một transaction.
- Thứ được lan truyền là từng thao tác (mỗi dòng của bảng `change_log`), không phải cả trạng thái.
- Nhật ký được nối bằng chuỗi hash nên sửa hay xóa dòng nào cũng bị phát hiện. Node bị hỏng dữ liệu kéo lại từ node đứng trước nó trong sơ đồ.
- N1 chỉ ghi khi liên lạc được với đa số (3/4 node), nên cụm chịu được một node chết. Không có bầu cử tự động; mất bản chính thì cụm chỉ cho đọc cho tới khi người quản trị nâng bản chính bằng tay.
- Các node gọi nhau qua gRPC, hợp đồng ở [`proto/dstock.proto`](proto/dstock.proto).

Tài liệu: [kiến trúc và các quyết định thiết kế](docs/architecture.md), [vận hành](docs/operations.md), [kịch bản demo](docs/demo.md). Cách đóng góp code xem [CONTRIBUTING.md](CONTRIBUTING.md).

## Cài đặt lần đầu

Cài trước: [Python](https://www.python.org/downloads/) từ 3.11 tới 3.14, khuyên dùng 3.12 (khi cài nhớ tích "Add python.exe to PATH"), và [Git for Windows](https://git-scm.com/download/win). CI chạy test trên cả 4 bản này. Kiểm tra trong PowerShell:

```powershell
py -0                           # liệt kê các bản Python đã cài; cần có một bản từ 3.11 tới 3.14
git --version
```

Máy đã có sẵn 3.11, 3.13 hoặc 3.14 thì dùng luôn, không cần cài thêm 3.12: ở các lệnh dưới, thay `-3.12` bằng bản đang có (ví dụ `py -3.13`). Dưới 3.11 thì không chạy được.

Khai báo tên và email cho commit, làm một lần trên mỗi máy. Không muốn lộ email thật thì dùng email dạng `...@users.noreply.github.com` trong GitHub, mục Settings > Emails.

```powershell
git config --global user.name "Ten Cua Ban"
git config --global user.email "email-dung-cho-github@example.com"
```

Clone vào thư mục có đường dẫn không dấu, ví dụ `D:\inventory-replication`: đường dẫn tiếng Việt dễ làm hỏng các lệnh Python và gRPC.

```powershell
cd D:\
git clone https://github.com/milanevn/inventory-replication.git
cd inventory-replication
py -3.12 -m venv .venv          # ghi rõ bản Python để .venv không lấy nhầm bản khác trên máy
.venv\Scripts\Activate.ps1      # đầu dòng lệnh hiện (.venv) là được
pip install -r requirements.txt
pytest                          # đúng khi không có test nào failed; skipped là phần chưa làm
```

- PowerShell báo `running scripts is disabled` ở bước kích hoạt: chạy một lần `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` rồi kích hoạt lại.
- macOS/Linux: tạo bằng `python3.12 -m venv .venv` (hoặc bản 3.11–3.14 đang có), kích hoạt bằng `source .venv/bin/activate`.
- `requirements.txt` cố định phiên bản thư viện để cả nhóm chạy giống nhau; các bản này đều có sẵn bản cài cho Windows từ Python 3.10 trở lên. Riêng Python thì phải từ 3.11 vì code dùng `tomllib`.
- Lần `git push` đầu tiên, Git mở trình duyệt để đăng nhập GitHub; đăng nhập đúng tài khoản đã được mời vào repo.
- Không cần cài `protoc`: code sinh từ file `.proto` đã có sẵn trong `dstock/rpc/`. Muốn xem CSDL thì cài thêm DB Browser for SQLite.

Cài xong thì chạy thử ở mục dưới, rồi đọc [CONTRIBUTING.md](CONTRIBUTING.md) (nhánh, commit, PR), [docs/architecture.md](docs/architecture.md) và docstring đầu module của phần mình.

## Chạy thử

```bash
python scripts/run_cluster.py --clean --gui     # bật 4 node trên máy này và mở bảng điều khiển
```

Ở một terminal khác:

```bash
python -m dstock.cli seed                        # khai báo 3 sản phẩm và nhập tồn đầu kỳ
python -m dstock.cli xuat PX001 SP01:30
python -m dstock.cli xuat PX002 SP03:999         # bị từ chối vì xuất quá tồn
python -m dstock.cli status                      # vai trò, epoch, LSN, kênh của 4 node
python -m dstock.cli crash N3                    # tắt N3
python -m dstock.node --id N3                    # bật lại, N3 tự bắt kịp
```

Chạy mỗi máy một node, các lệnh khác và cách xử lý sự cố: xem [docs/operations.md](docs/operations.md).

## Mở lại dự án

Mỗi lần mở terminal mới (PowerShell), đứng ở thư mục `inventory-replication` rồi chạy:

```powershell
.venv\Scripts\Activate.ps1                       # đầu dòng lệnh hiện (.venv) là được
git pull                                         # lấy code mới của nhóm
pip install -r requirements.txt                  # chỉ cần khi requirements.txt vừa đổi
python scripts/run_cluster.py --gui              # không có --clean: giữ nguyên dữ liệu lần trước
```

Mọi terminal dùng để gõ `python ...` đều phải kích hoạt `.venv` trước. Nếu PowerShell báo `running scripts is disabled`, chạy một lần `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, hoặc bỏ qua bước kích hoạt và gọi thẳng `.venv\Scripts\python.exe` thay cho `python`.

## Làm lại từ đầu

Chọn mức nhẹ nhất đủ dùng:

| Tình huống | Lệnh |
|---|---|
| Muốn kho trống, chạy lại demo | `python scripts/stop_cluster.py` rồi `python scripts/run_cluster.py --clean --gui` |
| Lỡ đóng terminal, node còn chạy ngầm, cổng 7001–7004 bị chiếm | `python scripts/stop_cluster.py` |
| `.venv` hỏng, đổi phiên bản Python, hoặc vừa chuyển thư mục dự án sang chỗ khác | xóa `.venv` (`Remove-Item -Recurse -Force .venv`) rồi làm lại từ bước `py -3.12 -m venv .venv` ở mục Cài đặt lần đầu |
| Code trên máy lộn xộn, muốn quay về `main` | `git stash` (cất thay đổi, lấy lại bằng `git stash pop`), rồi `git switch main` và `git pull` |

`--clean` chỉ xóa thư mục `data/` (CSDL, checkpoint, log của các node), không đụng tới code. `.venv` gắn với đường dẫn lúc tạo, nên chuyển thư mục dự án là phải tạo lại.

## Cấu trúc thư mục

```
proto/dstock.proto        hợp đồng gRPC giữa các node
cluster.toml              cấu hình chạy cả cụm trên một máy
cluster.lan.toml          cấu hình chạy mỗi máy một node
dstock/
  domain.py               nghiệp vụ sản phẩm, nhập, xuất, tồn
  schema.sql, oplog.py    lưu trữ SQLite, chuỗi hash
  store.py                trạng thái một node
  node.py, services.py    tiến trình node và các service gRPC
  replication/            kênh nhân bản và điều kiện gửi
  membership.py           PING, luật đa số
  failover.py             nâng bản chính bằng tay
  recovery.py             phục hồi khi dữ liệu bị hỏng
  faults.py               gây lỗi mạng
  client.py, cli.py, gui/ phía client
  rpc/                    code sinh từ .proto (không sửa tay)
tests/
  harness.py              dựng cụm 4 node ngay trong pytest
  test_*.py               test lõi
  acceptance/             test chấp nhận cho từng phần
scripts/                  chạy, tắt cụm; sinh lại code gRPC
docs/                     tài liệu
```

## Test

```bash
pytest                    # test lõi, luôn phải xanh
pytest --run-todo -q      # thêm test chấp nhận của các phần đang làm
pytest --run-optional -q  # thêm test của phần tùy chọn
```
