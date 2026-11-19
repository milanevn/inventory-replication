"""Một node = 1 tiến trình: server gRPC + NodeStore + các kênh nhân bản đi ra
+ theo dõi thành viên (membership.py) + nâng bản chính thủ công (failover.py).

    python -m dstock.node --id N1
    python -m dstock.node --id N3 --config cluster.toml
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from concurrent import futures

import grpc

from . import failover, recovery
from .config import ClusterConfig, LinkConfig, load_config
from .faults import FaultInjector, FaultInterceptor
from .membership import MembershipMonitor
from .replication import ReplicationLink
from .rpc import dstock_pb2 as pb
from .rpc import dstock_pb2_grpc as pbg
from .rpc.channels import make_channel
from .services import AdminService, InventoryService, ReplicationService
from .store import HEALTH_CORRUPT, HEALTH_OK, NodeStore

log = logging.getLogger("dstock.node")


class Node:
    def __init__(self, node_id: str, cfg: ClusterConfig):
        if node_id not in cfg.nodes:
            raise ValueError(f"không có node {node_id} trong cấu hình")
        self.id = node_id
        self.cfg = cfg
        self.addr = cfg.nodes[node_id]
        self.store = NodeStore(node_id, cfg.node_data_dir(node_id), node_id == cfg.primary)
        self.faults = FaultInjector()
        self.membership = MembershipMonitor(self)
        self._channels: dict[str, grpc.Channel] = {}
        self._links_lock = threading.Lock()
        # Giữ khóa này khi đổi epoch / primary / members trong meta (failover.py hạ cấp, membership.py nhận lại node)
        self.role_lock = threading.RLock()
        self.links: list[ReplicationLink] = []
        self.stopping = threading.Event()        # bật khi node đang dừng — mọi vòng nền phải thoát
        self._threads: list[threading.Thread] = []
        self.server: grpc.Server | None = None
        self.store.add_listener(self._on_commit)

    # ------------------------------------------------------------------ vai trò (đọc từ meta)
    @property
    def primary_id(self) -> str:
        return self.store.get_meta("primary", self.cfg.primary)

    @property
    def members(self) -> list[str]:
        raw = self.store.get_meta("members")
        return json.loads(raw) if raw else list(self.cfg.nodes)

    @property
    def is_primary(self) -> bool:
        return self.store.is_primary

    def _link_configs(self) -> list[LinkConfig]:
        """Kênh đi ra theo vai trò hiện tại.
        - CHẾ ĐỘ BÌNH THƯỜNG (bản chính là cfg.primary VÀ đủ mọi thành viên): đúng sơ đồ đề trong
          cluster.toml (1->2 ngay, 2->4 sau n lần, 1->3 sau n giây).
        - CHẾ ĐỘ SỰ CỐ (đã nâng node khác lên, hoặc đã loại node khỏi cụm): bản chính ĐẨY NGAY tới
          mọi thành viên còn lại — sơ đồ cạnh không còn giữ được (vd: N2 bị loại thì N4 mất nguồn).
          Node bị loại quay lại và được nhận lại đủ thành viên => tự trở về chế độ bình thường."""
        normal = self.primary_id == self.cfg.primary and set(self.members) == set(self.cfg.nodes)
        if normal:
            return self.cfg.links_from(self.id)
        if self.primary_id == self.id:
            return [LinkConfig(self.id, m, "sync", 1) for m in self.members if m != self.id]
        return []

    def apply_role(self) -> None:
        """Đọc lại vai trò từ meta, đặt store.is_primary và dựng lại các kênh nhân bản đi ra."""
        self.store.is_primary = self.primary_id == self.id
        with self._links_lock:
            old, self.links = self.links, [
                ReplicationLink(lc, self.store, self.replication_stub(lc.dst), role=self._role)
                for lc in self._link_configs()
            ]
        for link in old:
            link.stop()
        for link in self.links:
            link.start()

    def _role(self) -> tuple[str, list[str]]:
        """(primary_id, members) gửi kèm mỗi Append, để đích biết đúng bản chính kể cả khi nhận qua
        node trung gian."""
        return self.primary_id, self.members

    def _on_commit(self, lsn: int) -> None:
        for link in list(self.links):
            link.notify(lsn)

    def spawn(self, target, name: str) -> threading.Thread:
        """Chạy `target` ở thread nền DO NODE QUẢN LÝ. Vòng lặp trong target phải kiểm tra
        `node.stopping` (vd: `while not node.stopping.wait(0.5): ...`). stop() chờ các thread này
        thoát rồi mới đóng kênh gRPC — đóng kênh khi thread khác đang gọi qua nó có thể làm treo
        cả tiến trình. PING (membership.py) và phục hồi, scrub (recovery.py) PHẢI dùng hàm này."""
        t = threading.Thread(target=target, name=f"{self.id} {name}", daemon=True)
        self._threads.append(t)
        t.start()
        return t

    # ------------------------------------------------------------------ điểm móc thành viên
    def has_quorum(self) -> bool:
        """Xem dstock/membership.py."""
        return self.membership.has_quorum()

    def on_peer_status(self, nid: str, status: pb.NodeStatus) -> None:
        """Membership gọi sau mỗi PING thành công."""
        self.membership.record_seen(nid)
        failover.on_peer_status(self, nid, status)     # bản chính cũ tự hạ cấp
        self.membership.readmit(nid, status)           # nhận lại node quay về

    def promote(self, exclude: list[str]) -> None:
        """Xem dstock/failover.py."""
        failover.promote(self, exclude)

    # ------------------------------------------------------------------ kênh tới node khác
    def channel_to(self, dst: str) -> grpc.Channel:
        """Kênh gRPC tới node `dst`, đi qua lớp gây lỗi (FaultInterceptor) của node này."""
        if dst not in self._channels:
            self._channels[dst] = make_channel(
                self.cfg.nodes[dst].address, (FaultInterceptor(self.faults, dst),)
            )
        return self._channels[dst]

    def replication_stub(self, dst: str) -> pbg.ReplicationStub:
        return pbg.ReplicationStub(self.channel_to(dst))

    def link_to(self, dst: str) -> ReplicationLink | None:
        return next((l for l in self.links if l.cfg.dst == dst), None)

    # ------------------------------------------------------------------ vòng đời
    def start(self) -> "Node":
        self.store.open()
        self.store.is_primary = self.primary_id == self.id
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix=self.id))
        pbg.add_InventoryServicer_to_server(InventoryService(self), self.server)
        pbg.add_ReplicationServicer_to_server(ReplicationService(self), self.server)
        pbg.add_AdminServicer_to_server(AdminService(self), self.server)
        try:
            port = self.server.add_insecure_port(self.addr.address)
        except RuntimeError as exc:   # grpc >= 1.6x ném lỗi thay vì trả 0
            log.debug("bind lỗi: %s", exc)
            port = 0
        if port == 0:
            raise RuntimeError(f"không mở được cổng {self.addr.address} — có tiến trình khác đang dùng? "
                               f"(Windows: netstat -ano | findstr {self.addr.port})")
        self._primary_startup_check()     # TRƯỚC khi server nhận lời gọi Write đầu tiên
        self.server.start()
        recovery.on_startup(self)
        self.membership.start()
        self.apply_role()
        log.info("[%s] chạy tại %s | %s (epoch %d) | lsn=%d | health=%s | kênh: %s",
                 self.id, self.addr.address, "PRIMARY" if self.is_primary else "REPLICA",
                 self.store.epoch, self.store.last_lsn, self.store.health,
                 ", ".join(f"{l.name}({l.cfg.mode}={l.cfg.param:g})" for l in self.links) or "-")
        return self

    def stop(self, grace: float = 0) -> None:
        self.stopping.set()
        self.membership.stop()
        for link in self.links:
            link.stop()
        if self.server:
            self.server.stop(grace).wait()
        for t in self._threads:                 # chờ các vòng nền thoát TRƯỚC khi đóng kênh
            t.join(timeout=4)
        for ch in self._channels.values():
            ch.close()
        self.store.close()

    # ------------------------------------------------------------------ quan sát
    def status(self) -> pb.NodeStatus:
        snap = self.store.snapshot()          # đọc mọi số liệu tại CÙNG một thời điểm
        return pb.NodeStatus(
            node_id=self.id,
            role="PRIMARY" if self.is_primary else "REPLICA",
            health=snap.health,
            last_lsn=snap.last_lsn,
            last_hash=snap.last_hash,
            state_digest=snap.digest,
            stock=snap.stock,
            links=[l.info(self.faults.describe(l.cfg.dst)) for l in self.links],
            last_apply_ts=snap.last_apply_ts,
            detail=snap.detail,
            epoch=snap.epoch,
            primary_id=self.primary_id,
            has_quorum=self.has_quorum() if self.is_primary else False,
            members=self.members,
            products={k: f"{ten}|{dvt}" for k, (ten, dvt) in snap.products.items()},
        )

    def _primary_startup_check(self) -> None:
        """Bản chính vừa khởi động: hỏi MỌI bản sao trước khi nhận ghi.

        Có bản sao ĐI TRƯỚC (last_lsn lớn hơn) => bản chính đã mất dữ liệu (mất đuôi / mất file —
        chuỗi hash của phần còn lại vẫn hợp lệ nên store.open() không tự thấy) => CORRUPT, từ chối
        ghi cho tới khi phục hồi (recovery.py). Nếu không cấp lại một LSN mà bản sao đã có.
        Không liên lạc được bản sao nào (vd: khởi động cả cụm) thì vẫn chạy; kênh nhân bản sẽ kiểm
        tra lại đầu chuỗi ở lần liên lạc đầu tiên (ReplicationLink._check_head).
        """
        if not self.is_primary:
            return
        others = [nid for nid in self.cfg.nodes if nid != self.id]
        results: dict[str, pb.NodeStatus] = {}

        def ask(nid: str) -> None:
            try:
                results[nid] = pbg.AdminStub(self.channel_to(nid)).Status(pb.Empty(), timeout=0.5)
                self.membership.record_seen(nid)      # đã thấy sống => tính vào đa số ngay
            except grpc.RpcError:
                pass

        threads = [threading.Thread(target=ask, args=(nid,), daemon=True) for nid in others]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=1.0)
        # Cho failover xem trước: có node khác là bản chính với epoch LỚN HƠN => mình là bản
        # chính CŨ, phải tự hạ cấp (chứ không phải "mất dữ liệu").
        for nid, st in sorted(results.items()):
            self.on_peer_status(nid, st)
        if not self.is_primary or self.store.health != HEALTH_OK:
            return
        ahead = {nid: st.last_lsn for nid, st in results.items()
                 if st.last_lsn > self.store.last_lsn and st.epoch <= self.store.epoch}
        if ahead:
            self.store.mark(HEALTH_CORRUPT, f"bản sao đi trước bản chính {ahead} (bản chính ở lsn "
                                            f"{self.store.last_lsn}): bản chính đã mất dữ liệu — cần phục hồi")
            log.error("[%s] %s", self.id, self.store.detail)


def setup_logging(node_id: str = "", level: int = logging.INFO) -> None:
    for stream in (sys.stdout, sys.stderr):  # console Windows mặc định cp1252 -> lỗi tiếng Việt
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=level,
        format=f"%(asctime)s.%(msecs)03d {node_id:<3} %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Chạy một node")
    ap.add_argument("--id", required=True, help="N1 | N2 | N3 | N4")
    ap.add_argument("--config", default="cluster.toml")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args(argv)
    setup_logging(args.id, logging.DEBUG if args.debug else logging.INFO)
    node = Node(args.id, load_config(args.config)).start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("[%s] dừng", args.id)
        node.stop()


if __name__ == "__main__":
    main()
