# Kiến trúc

## Bài toán

Đề tài 8: xây dựng ứng dụng cập nhật lan truyền, dữ liệu là quản lý nhập - xuất - tồn hàng hóa.

```
Client <-> N1 ---- ngay lập tức ----> N2 ---- sau n lần cập nhật ----> N4
            \
             +---- sau n giây ------> N3
```

Client chỉ ghi qua N1, đọc ở node nào cũng được. Dữ liệu đi theo đúng các cạnh trên; n của hai kênh 1→3 và 2→4 đổi được khi đang chạy. Khi dữ liệu ở một node bị tổn hại, node đó phải tự phát hiện và phục hồi.

## Nghiệp vụ

Có ba loại thao tác: khai báo sản phẩm (`SANPHAM`: mã, tên, đơn vị tính), phiếu nhập (`NHAP`) và phiếu xuất (`XUAT`). Phiếu có thể có nhiều dòng. Số phiếu không được trùng và không được xuất quá tồn. Nhập một mã chưa khai báo thì hệ thống tự tạo sản phẩm, tên tạm lấy bằng mã. Phần này nằm trong `dstock/domain.py`, là Python thuần, không đụng tới mạng hay đĩa.

## Các thành phần

Mỗi node là một tiến trình, chạy bằng `python -m dstock.node --id N1`.

```
+------------------------------- node N1 -------------------------------+
|                                                                       |
|  gRPC server ---> InventoryService ---+                               |
|  (cổng 7001)      ReplicationService -+--> NodeStore ---> SQLite      |
|                   AdminService -------+       |        data/N1/dstock.db
|                                               | có entry mới          |
|                                               v                       |
|               ReplicationLink N1->N2    ReplicationLink N1->N3        |
|                                                                       |
|   MembershipMonitor   failover   recovery   FaultInterceptor          |
+-----------------------------------------------------------------------+
```

| Module | Việc |
|---|---|
| `domain.py` | Nghiệp vụ: kiểm phiếu, tồn kho trong RAM |
| `oplog.py` | Đọc ghi `change_log` và các bảng suy ra trong SQLite, chuỗi hash |
| `store.py` | Trạng thái của một node: ghi ở bản chính, áp dụng entry ở bản sao, trạng thái `CORRUPT` |
| `node.py`, `services.py` | Lắp ghép tiến trình, ba service gRPC, vai trò và epoch |
| `replication/` | Kênh nhân bản và điều kiện gửi |
| `membership.py` | PING, luật đa số, nhận lại node quay về |
| `failover.py` | Nâng bản chính bằng tay, hạ cấp bản chính cũ |
| `recovery.py` | Phục hồi khi dữ liệu bị hỏng |
| `faults.py` | Gây lỗi mạng để demo và test |
| `client.py`, `cli.py`, `gui/` | Phía client |

GUI và CLI chỉ là client: gọi `Inventory` để ghi và đọc, gọi `Admin` để xem trạng thái và điều khiển.

## Đường đi của một lệnh ghi

1. Client gửi `Write(phiếu, req_id)` tới bản chính. Client tìm bản chính theo thứ tự: `primary` trong cấu hình, rồi `primary_hint` trong lỗi trả về, cuối cùng là hỏi `Status` từng node.
2. Node nhận lệnh không phải bản chính thì trả `NOT_PRIMARY` kèm `primary_hint`. Bản chính không thấy đủ đa số thì trả `NO_QUORUM`.
3. Bản chính giữ khóa của store. Nếu `req_id` đã có thì trả lại LSN cũ. Nếu chưa, kiểm phiếu, cấp `lsn = last + 1`, gắn epoch và hash, rồi ghi `change_log` cùng các bảng suy ra trong một transaction.
4. Bản chính báo cho các kênh đi ra rồi trả lời client ngay.
5. Kênh N1→N2 gửi ngay. N2 áp dụng xong thì báo cho kênh N2→N4 của nó, kênh này gom đủ n thao tác mới gửi. Kênh N1→N3 gửi khi entry chờ cũ nhất đã đủ n giây.

## Kênh nhân bản

Mỗi cạnh của sơ đồ là một `ReplicationLink` chạy trong thread riêng. Ba cạnh dùng chung code, chỉ khác trigger (`replication/triggers.py`). Kênh không có hàng đợi: nó giữ `acked_lsn` (đích đã có tới đâu, lấy từ phản hồi của đích) và đọc dữ liệu thẳng từ nhật ký của nguồn.

```
acked_lsn = -1
lặp:
    chờ có entry mới, hoặc hết trigger.wait_timeout()
    nếu chưa biết đích ở đâu, hoặc khoảng 1 s chưa liên lạc:
        gửi Append rỗng để hỏi
    pending = last_lsn(nguồn) - acked_lsn
    nếu pending > 0 và trigger.due(pending, giây từ lần gửi trước, tuổi entry chờ cũ nhất):
        gửi Append(các entry, epoch) cho tới khi acked_lsn bằng last_lsn lúc bắt đầu gửi
        mỗi phản hồi: kiểm đầu chuỗi, cập nhật acked_lsn
    lỗi gRPC: state = DOWN, giữ nguyên acked_lsn, nghỉ một lúc rồi thử lại
```

Kiểm đầu chuỗi: nếu đích có LSN lớn hơn nguồn, hoặc cùng LSN mà khác hash, kênh chuyển `DIVERGED` và ngừng gửi. Nếu nguồn là bản chính thì nó tự chuyển `CORRUPT`.

Phía nhận (`NodeStore.apply_replicated`) xử lý từng entry:

| Trường hợp | Xử lý |
|---|---|
| epoch của nguồn nhỏ hơn epoch của đích | trả `STALE_EPOCH`, không áp dụng |
| `lsn <= last` | đã có: cùng hash thì bỏ qua, khác hash thì `DIVERGED` |
| `lsn == last + 1` | kiểm `prev_hash` và `hash`, ghi trong một transaction; sai thì `HASH_MISMATCH` |
| `lsn > last + 1` | trả `GAP` cùng `last_lsn` để nguồn gửi lại từ đó |
| node đang `CORRUPT` | từ chối cho tới khi phục hồi xong |

## Lưu trữ

Schema đầy đủ ở `dstock/schema.sql`.

| Bảng | Nội dung |
|---|---|
| `change_log` | Nguồn sự thật. Mỗi dòng một thao tác: `lsn, req_id, kind, code, lines, note, product_name, unit, epoch, ts, prev_hash, hash` |
| `san_pham`, `phieu`, `phieu_ct`, `ton_kho` | Suy ra từ nhật ký, ghi cùng transaction |
| `meta` | `epoch`, `primary`, `members` |

`hash` là sha256 của JSON chuẩn hóa mọi cột trừ cột `hash`; entry đầu tiên có `prev_hash` là 64 số 0.

Khi khởi động, `NodeStore.open`:

1. Mở CSDL. Không mở được thì chuyển `CORRUPT`.
2. Kiểm chuỗi hash của `change_log`. Chuỗi vỡ thì giữ phần còn tốt và chuyển `CORRUPT`.
3. Chạy lại nhật ký để dựng trạng thái trong RAM.
4. So với `san_pham` và `ton_kho`; lệch thì dựng lại hai bảng này.
5. Nếu là bản chính thì hỏi các node khác: có node đi trước thì chuyển `CORRUPT`; thấy bản chính có epoch lớn hơn thì tự hạ cấp.

## Vai trò, đa số và epoch

Danh sách thành viên và bản chính nằm trong bảng `meta`, mặc định là cả 4 node và N1. Mỗi node PING tất cả các node khoảng 0.5 giây một lần; trả lời trong 1.5 giây gần nhất thì coi là còn sống. Bản chính chỉ ghi khi thấy đa số thành viên còn sống, tính cả chính nó.

Không có bầu cử tự động. Muốn đổi bản chính thì người quản trị nâng bằng tay, mỗi lần nâng tăng epoch. Ví dụ N1 và N2 cùng chết:

```
cli promote N3 --exclude N1 N2
    N3 kiểm: N1, N2 không trả lời; không node sống nào mới hơn N3; N3 không hỏng
    epoch 0 -> 1, members = [N3, N4], primary = N3
    N3 thành bản chính, đẩy thẳng tới N4

N1 bật lại, thấy N3 là bản chính với epoch 1 > 0
    entry của N1 sau điểm chung ghi ra data/N1/orphans-<ts>.jsonl
    nhật ký của N1 thay bằng bản của N3, N1 thành bản sao
N3 thấy N1 sống và nằm ngoài danh sách thành viên
    nhận N1 vào cụm lại, đẩy dữ liệu cho N1
```

Sơ đồ 1→2→4, 1→3 chỉ dùng khi bản chính là N1 và đủ 4 thành viên. Các trường hợp khác bản chính đẩy thẳng tới mọi thành viên. Code sửa `epoch`, `primary`, `members` phải giữ `node.role_lock`. Cách xử lý cho từng tình huống node chết xem [operations.md](operations.md#khi-node-chết).

## Hợp đồng gRPC

File `proto/dstock.proto`:

| Service | RPC | Ai gọi |
|---|---|---|
| `Inventory` | `Write`, `GetStock` | CLI, GUI |
| `Replication` | `Append` (đẩy một lô entry, lô rỗng để hỏi thăm), `FetchSince` (stream, dùng khi phục hồi và hạ cấp) | node với node |
| `Admin` | `Status`, `SetLinkParam`, `SetFault`, `Crash`, `Promote` | GUI, CLI, PING, test |

Trạng thái hiển thị: `health` của node là `OK`, `CORRUPT` hoặc `RECOVERING`; `role` là `PRIMARY` hoặc `REPLICA` kèm `epoch`, `has_quorum`, `members`; `state` của kênh là `UNKNOWN`, `OK`, `LAGGING`, `DOWN` hoặc `DIVERGED`.

## Quyết định thiết kế

Muốn đổi điều nào dưới đây thì bàn trong nhóm trước, rồi sửa mục này trong cùng PR với code (PR gắn nhãn `decision`).

### Một bản chính, lan truyền theo thao tác

Chỉ N1 nhận ghi, nên không bao giờ có hai node cùng xuất một lô hàng rồi phải gộp xung đột. Thứ được gửi đi là từng thao tác có LSN, không phải cả bảng tồn kho. Bên nhận áp dụng đúng thứ tự, bỏ qua entry đã có và báo `GAP` khi thiếu, nên RPC chỉ cần at-least-once. Mỗi lệnh có `req_id` để client gửi lại không bị ghi hai lần. Cái giá là bản chính chết thì ngừng ghi. (Bài 14: giao thức dựa trên bản chính; binlog của MySQL.)

### Kênh 1→2 đẩy ngay nhưng không chờ xác nhận

"Tức thời" có thể hiểu là đồng bộ (N1 chờ N2 ghi xong mới trả lời client). Nhưng như vậy N2 chết là N1 cũng không ghi được. Nhóm chọn đẩy ngay mà không chờ: bình thường N2 chỉ chậm vài mili giây, N2 chết thì N1 vẫn ghi. Đổi lại, N1 sập ngay sau khi ghi có thể mất vài entry chưa sang N2. Vì vậy N2 không chắc là bản sao mới nhất.

### Kênh theo n giây và theo n lần

"Sau n giây" tính từ lúc entry chờ cũ nhất được ghi, không tính từ lần gửi trước. Nếu tính từ lần gửi trước thì sau một lúc rảnh, phiếu mới sẽ đi ngay, sai ý đề. "Một lần cập nhật" là một thao tác (một phiếu hoặc một lần khai báo sản phẩm). Đổi n có hiệu lực ngay: đang gom 5 mà đổi n xuống 3 thì gửi luôn. N4 chỉ nhận từ N2, nên N2 chết thì N4 đứng yên. N3 lệch tối đa khoảng n giây, N4 lệch tối đa n thao tác; đây là hai kiểu độ lệch của nhất quán liên tục. (Bài 14; `linger.ms` và `batch.size` của Kafka.)

### SQLite, `change_log` là nguồn sự thật

SQLite có sẵn trong Python, không phải cài server CSDL trên 4 máy, và mở được bằng DB Browser để demo sửa dữ liệu. Các bảng tồn kho được suy ra từ nhật ký và ghi cùng transaction, nên không bao giờ lệch nhau giữa chừng; ai sửa tay `ton_kho` thì lần khởi động sau bảng tự đúng lại. Phiếu xuất dùng `UPDATE` thay vì UPSERT, vì SQLite kiểm `CHECK (sl >= 0)` trước khi xét xung đột của UPSERT.

### Phát hiện hỏng bằng chuỗi hash và so đầu chuỗi

Chuỗi hash bắt được dòng bị sửa, bị xóa hoặc bị chèn. Mất mấy dòng cuối hoặc mất cả file thì một node tự nhìn không thấy, nên mọi phản hồi `Append` đều mang `last_lsn` và `last_hash` của đích để bên gửi so. Đích đi trước nguồn, hoặc cùng LSN mà khác hash, thì không ghi đè gì mà báo `DIVERGED`. Bản chính không bao giờ cấp lại một LSN mà bản sao đã có. Hash không có khóa nên không chống được người cố tình sửa rồi tính lại hash. (Git; kiểm tra khớp log trong Raft.)

### Phục hồi theo chiều cạnh

Node hỏng cách ly file (đổi tên, không xóa), rồi kéo nhật ký về bằng `FetchSince`: N2, N3 kéo từ N1; N4 chỉ kéo từ N2; N1 kéo từ bản sao có LSN lớn nhất (vì N2 có thể thiếu so với N3). Nhật ký kéo về phải kiểm chuỗi xong mới thay vào. Không nguồn nào sống thì giữ `CORRUPT` và thử lại sau.

Nhóm chia dữ liệu tổn hại thành bốn loại và xử lý ba loại đầu:

1. Node sập làm bản sao tụt lại: lên lại thì kéo phần thiếu (khắc phục tiến).
2. Dữ liệu đang lưu bị hỏng (sửa tay, mất dòng, mất file, file hỏng): dựng lại từ nguồn (khắc phục lùi).
3. Bản sao lệch nhau do mất, trùng, sai thứ tự gói: kênh tự xử lý.
4. Thao tác sai của người dùng (gõ 1000 thay vì 10): ngoài phạm vi.

(Bài 12: khắc phục tiến và khắc phục lùi.)

### Chỉ ghi khi có đa số

Nếu mạng bị chia cắt mà N1 bị cô lập vẫn ghi, trong khi phía bên kia đã nâng bản chính mới, thì cụm có hai bản chính (split-brain). Bản chính chỉ ghi khi thấy ít nhất `floor(m/2) + 1` thành viên còn sống, nên hai phía không thể cùng ghi. Với 4 node, cụm chịu được một node chết; hai node chết thì ngừng ghi nhưng vẫn cho đọc. Đây là chọn nhất quán thay vì sẵn sàng trong CAP. (Bài 12; quorum của Raft, ZooKeeper.)

### Không bầu cử tự động

Muốn tự bầu thì phải phát hiện bản chính chết bằng timeout. Nhưng timeout không phân biệt được node chết với mạng chậm hay mạng đứt; bầu sai là có hai bản chính. Nhóm chọn để người quản trị xác nhận rồi nâng bằng tay, kể cả khi N1 chết mà vẫn còn đa số. Lệnh `promote` chỉ chạy khi các node bị loại thật sự không trả lời, không có node sống nào mới hơn, node được nâng không hỏng và còn ít nhất 2 thành viên. Epoch chặn bản chính cũ quay lại ghi tiếp. Cái giá là thời gian ngừng ghi phụ thuộc vào con người, và phần chưa kịp lan tới node được nâng chỉ còn trong file entry mồ côi. Bầu cử Bully để ở phần tùy chọn. (Bài 7; term của Raft, epoch của Kafka.)

### gRPC giữa các node

So với tự viết socket hay HTTP + JSON, gRPC cho sẵn timeout, stream và một hợp đồng viết bằng IDL mà cả nhóm cùng dựa vào. Code sinh ra được commit sẵn nên không ai phải cài `protoc`. Backoff kết nối lại mặc định của gRPC lên tới khoảng 120 giây; repo đã hạ xuống 1 giây (`rpc/channels.py`) để node vừa bật lại được nhận ra ngay. (Bài 2, bài 15; etcd, CockroachDB.)

### Hai cách chạy, không dùng Docker

`cluster.toml` chạy cả 4 node trên một máy, dùng khi code, test và quay video. `cluster.lan.toml` chạy mỗi máy một node, dùng khi demo trên LAN. Code giống hệt nhau. Máy của cả nhóm đều là Windows; Docker Desktop nặng và dễ lỗi, nên chỉ dùng Python và venv.

### Giao diện Tkinter, gây lỗi bằng interceptor

GUI viết bằng Tkinter vì có sẵn trong Python và đồ án không tập trung vào web. GUI chỉ là client, tắt đi thì cụm vẫn chạy. Lỗi mạng được gây ra bằng một interceptor gRPC ở phía gửi, đặt theo từng cặp node: cắt kênh là bắt buộc, bỏ x% gói và gây trễ là tùy chọn. Cách này lặp lại được trong test, khác với việc rút dây mạng khi demo.

## Giới hạn

- N1 sập ngay sau khi ghi có thể làm mất vài entry chưa tới N2.
- Khi nâng bằng tay, phần chưa lan tới node được nâng sẽ mất (chỉ còn trong file entry mồ côi).
- Còn ít hơn đa số thì không ghi được. Bản chính chết thì ngừng ghi cho tới khi có người nâng tay, kể cả khi còn đa số.
- Hệ thống chỉ tự chịu được một bản sao chết. Còn một node thì chỉ đọc.
- Khóa ghi khóa cả node, chưa khóa theo dòng.
- N1 mất đuôi file đúng lúc mọi bản sao đều tắt và có lệnh ghi: kênh báo `DIVERGED`, phải xử lý tay.
- Không xử lý thao tác sai của người dùng, lỗi Byzantine, mã hóa hay xác thực.
