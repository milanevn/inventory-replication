"""Theo dõi thành viên và luật đa số: PING định kỳ để biết node nào còn sống.

Luật đã chốt (docs/architecture.md, mục Quyết định thiết kế):
    Bản chính chỉ nhận ghi khi thấy đa số thành viên còn sống, tính cả chính nó:
        cần >= len(members) // 2 + 1        (4 thành viên cần 3; 2 thành viên cần 2)
    Lý do: nếu bản chính bị cô lập mà vẫn ghi, trong khi phía bên kia đã nâng một bản chính mới,
    cụm sẽ có hai bản chính (split-brain). Bắt buộc có đa số thì tối đa một bên ghi được.
    Ví dụ: N2 chết thì N1 vẫn thấy {N1, N3, N4} = 3, ghi bình thường. N2 và N3 cùng chết thì
    chỉ còn {N1, N4} = 2 < 3, từ chối ghi.
    Module này không bầu cử. Nó chỉ trả lời "có đủ đa số hay không"; đổi bản chính là việc
    thủ công (failover.py). Bảng xử lý khi node chết: docs/operations.md.

Node có sẵn:
    node.members                       danh sách thành viên hiện tại (đổi khi nâng bản chính)
    node.channel_to(nid)               kênh gRPC tới nid (đi qua lớp gây lỗi trong faults.py)
    node.on_peer_status(nid, status)   gọi sau mỗi lần PING thành công; hàm này gọi record_seen(),
                                       failover, rồi readmit() bên dưới
    node.role_lock                     giữ khóa này khi sửa epoch / primary / members
    node.store.set_meta(k, v), node.apply_role()
    Node._primary_startup_check() cũng gọi on_peer_status() cho các node trả lời lúc khởi động.

Việc cần làm (TODO):
  1. start(): self.node.spawn(vòng_lặp, "ping"), vòng lặp `while not self.node.stopping.wait(0.5)`.
     Mỗi vòng gọi Admin.Status (timeout khoảng 0.4 s) song song tới mọi node trong cfg, kể cả node
     đã bị loại khỏi thành viên (để còn nhận lại khi nó quay về). Gọi thành công thì
     node.on_peer_status(nid, status). Đừng gọi tuần tự: 3 node chết x 0.4 s đã vượt cửa sổ 1.5 s.
     Chỉ spawn MỘT thread cho cả vòng lặp; các lời gọi song song trong mỗi vòng dùng một
     ThreadPoolExecutor tạo một lần (node.spawn mỗi lần PING sẽ làm danh sách thread phình mãi).
  2. has_quorum(): số node còn sống (trả lời trong 1.5 s gần nhất) + 1 (chính mình) >= majority.
     Mọi node đều chạy monitor, nhưng chỉ bản chính dùng has_quorum() để chặn ghi.
  3. readmit(): node bị loại (sau khi nâng tay) quay lại thì nhận nó vào cụm lại. Điều kiện:
     mình là bản chính, epoch > 0, nid không nằm trong members, status.role == "REPLICA",
     status.health == "OK" và status.epoch == epoch của mình. Epoch bằng nhau nghĩa là node đó đã
     tự hạ cấp theo nhiệm kỳ mới (failover.on_peer_status: lưu entry mồ côi, nhật ký đã giống
     mình); epoch còn nhỏ hơn thì CHƯA nhận, chờ vòng PING sau — nhận sớm thì nó có thể còn giữ
     entry mà mình không có. Khi đủ điều kiện, trong node.role_lock: thêm nid vào "members"
     (JSON list) rồi node.apply_role() để kênh đẩy dữ liệu tới nó. Các bản sao biết danh sách
     mới qua Append (cùng epoch, members khác: xem TODO trong services.ReplicationService.Append).
  Test: tests/acceptance/test_membership.py
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .node import Node

ALIVE_WINDOW = 1.5     # giây: thấy trả lời trong khoảng này thì coi là còn sống
PING_EVERY = 0.5


def majority(n_members: int) -> int:
    return n_members // 2 + 1


class MembershipMonitor:
    def __init__(self, node: "Node"):
        self.node = node
        self._lock = threading.Lock()
        self._last_seen: dict[str, float] = {}     # nid -> time.monotonic() lần cuối trả lời
        self._stop = threading.Event()

    def record_seen(self, nid: str) -> None:
        with self._lock:
            self._last_seen[nid] = time.monotonic()

    def alive(self) -> set[str]:
        now = time.monotonic()
        with self._lock:
            return {nid for nid, t in self._last_seen.items() if now - t <= ALIVE_WINDOW}

    def has_quorum(self) -> bool:
        # TODO: return len((self.alive() & set(members)) | {self.node.id}) >= majority(len(members))
        return True        # TẠM THỜI: luôn coi là đủ đa số

    def start(self) -> None:
        # TODO: khởi động thread PING (xem docstring đầu file).
        pass

    def readmit(self, nid: str, status) -> None:
        # TODO: nhận lại node quay về (xem mục 3 ở docstring đầu file).
        pass

    def stop(self) -> None:
        self._stop.set()
