"""Nâng bản chính thủ công và epoch. Đây là cách duy nhất để ghi tiếp khi bản chính chết
hoặc khi cụm mất đa số.

Phạm vi đã chốt (docs/architecture.md và docs/operations.md, mục "Khi node chết"):
  - Một bản sao chết hẳn: hệ thống tự chịu được (còn 3/4 là đa số, vẫn ghi).
  - Không có bầu cử tự động, trong mọi trường hợp.
  - Bản chính chết, hoặc mất đa số (2 node chết): cụm chỉ đọc. Nếu bắt buộc phải ghi tiếp thì
    người quản trị nâng thủ công (Admin.Promote, hoặc `cli promote N3 --exclude N1 N2`).
  - Còn ít hơn 2 node: không hỗ trợ ghi, Promote bị từ chối.

Vì sao làm thủ công: phần mềm không phân biệt được "node chết thật" với "mạng đứt". Người quản trị
xác nhận node đã chết rồi mới nâng thì không thể có hai bản chính. Phần dữ liệu chưa kịp lan tới
node được nâng (tối đa khoảng n giây ở N3, dưới n thao tác ở N4) sẽ mất; nó được lưu lại thành
entry mồ côi khi bản chính cũ quay về. Đây là giới hạn đã chấp nhận (docs/architecture.md, mục Giới hạn).

Node có sẵn:
    node.members / node.primary_id      đọc từ bảng meta (mặc định: mọi node / cfg.primary)
    node.store.set_meta(k, v)           lưu bền "epoch", "primary", "members" (JSON list)
    node.role_lock                      giữ khóa này khi sửa ba giá trị trên
    node.apply_role()                   đọc lại meta, đặt store.is_primary, dựng lại kênh nhân bản:
                                          bình thường (cfg.primary và đủ thành viên): kênh trong cluster.toml
                                          chế độ sự cố: "sync" tới mọi thành viên
    node.channel_to(nid), node.replication_stub(nid), node.store.snapshot(), node.store.replace_log(entries)
    Admin.Promote(exclude) -> node.promote(exclude) -> promote() bên dưới

Việc cần làm (TODO):
  promote(node, exclude): gọi trên node muốn làm bản chính. Có thể gọi trên chính bản chính hiện tại,
  khi đó là thu hẹp thành viên để ghi tiếp (hai bản sao chết, N1 còn sống).
    1. Từ chối (raise PromoteRefused) nếu:
         - node đang CORRUPT;
         - một node trong `exclude` vẫn trả lời Admin.Status (chưa chết thật, có nguy cơ hai bản chính);
         - có node còn sống, không bị exclude, có last_lsn lớn hơn node này (phải nâng node mới nhất);
         - có node KHÁC còn sống, không bị exclude, đang là PRIMARY (muốn trả vai trò thì tắt bản
           chính hiện tại trước rồi exclude nó; nếu không sẽ có lúc hai bản chính cùng ghi);
         - thành viên còn lại (mọi node trừ exclude) ít hơn 2.
    2. epoch = max(các epoch đang biết) + 1; members = mọi node trong cfg trừ exclude; primary = node.id.
       Lưu meta trong node.role_lock.
    3. node.apply_role(). Các node vừa trả lời Admin.Status ở bước 1 chắc chắn đang sống, nên gọi
       node.membership.record_seen(nid) cho chúng; như vậy lệnh ghi ngay sau khi nâng không bị
       NO_QUORUM chỉ vì vòng PING chưa kịp chạy.
  on_peer_status(node, nid, status): membership gọi sau mỗi PING thành công; node cũng gọi khi
  bản chính khởi động. Nếu status.epoch > epoch của mình, DÙ nid là PRIMARY hay REPLICA, thì mình
  là bản chính cũ hoặc đang lạc hậu (vd: N2 được nâng rồi cũng chết, N1 bật lại chỉ thấy N3, N4 ở
  epoch mới), phải hạ cấp ngay, trước khi nhận thêm lệnh ghi nào:
    a. store.is_primary = False (chặn ghi ngay); FetchSince(0) từ nid (nó đã ở nhiệm kỳ mới);
       điểm chung = tiền tố dài nhất có hash trùng nhau;
    b. entry của mình nằm sau điểm chung là entry mồ côi: ghi ra data/<id>/orphans-<ts>.jsonl
       (Entry.to_json) để người xem xét, rồi replace_log(nhật ký vừa kéo về);
    c. lưu epoch = status.epoch, primary = status.primary_id, members = status.members vào meta
       (giữ node.role_lock), gọi node.apply_role() để thành bản sao.
  (Nhận lại node quay về cụm nằm ở membership.readmit().)
  services.ReplicationService.Append: chặn bản chính cũ bằng STALE_EPOCH; nhận nhiệm kỳ mới và
  cập nhật primary / members (gửi kèm trong AppendRequest) — xem comment TODO ở đó.
  Test: tests/acceptance/test_failover.py
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import Node
    from .rpc import dstock_pb2 as pb


def promote(node: "Node", exclude: list[str]) -> None:
    raise NotImplementedError("nâng bản chính thủ công chưa được cài đặt (dstock/failover.py)")


def on_peer_status(node: "Node", nid: str, status: "pb.NodeStatus") -> None:
    pass   # TODO: hạ cấp khi thấy bản chính có epoch lớn hơn (xem docstring)
