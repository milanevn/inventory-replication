"""Thư viện client dùng chung cho CLI, GUI và test.

Mọi lệnh ghi đi vào bản chính. req_id sinh 1 lần cho mỗi phiếu và GIỮ NGUYÊN khi gửi lại
=> nếu lần gửi đầu đã ghi nhưng mất phản hồi, lần gửi lại không ghi trùng.
"""
from __future__ import annotations

import threading
import time
import uuid

import grpc

from .config import ClusterConfig
from .domain import Line
from .rpc import dstock_pb2 as pb
from .rpc import dstock_pb2_grpc as pbg
from .rpc.channels import make_channel


def parse_lines(items: list[str]) -> list[Line]:
    """["SP01:10", "SP02:5"] -> [Line("SP01", 10), Line("SP02", 5)]"""
    out = []
    for it in items:
        for part in it.replace(",", " ").split():
            sku, _, qty = part.partition(":")
            if not qty:
                raise ValueError(f"dòng hàng {part!r} phải có dạng MA:SOLUONG")
            out.append(Line(sku.strip(), int(qty)))
    return out


class ClusterClient:
    def __init__(self, cfg: ClusterConfig, timeout: float = 2.0):
        self.cfg = cfg
        self.timeout = timeout
        self._channels: dict[str, grpc.Channel] = {}
        self._lock = threading.Lock()      # GUI gọi từ nhiều thread -> không tạo trùng kênh
        self.primary = cfg.primary         # bản chính đang biết; đổi khi được nâng thủ công

    def _ch(self, node_id: str) -> grpc.Channel:
        with self._lock:
            if node_id not in self._channels:
                self._channels[node_id] = make_channel(self.cfg.nodes[node_id].address)
            return self._channels[node_id]

    def inventory(self, node_id: str) -> pbg.InventoryStub:
        return pbg.InventoryStub(self._ch(node_id))

    def admin(self, node_id: str) -> pbg.AdminStub:
        return pbg.AdminStub(self._ch(node_id))

    def close(self) -> None:
        with self._lock:
            for ch in self._channels.values():
                ch.close()
            self._channels.clear()

    # ------------------------------------------------------------------ nghiệp vụ
    def find_primary(self) -> str | None:
        """Hỏi mọi node, chọn node tự nhận PRIMARY có epoch LỚN NHẤT (bản chính cũ lạc hậu có
        thể vẫn tự nhận là PRIMARY nhưng epoch nhỏ hơn)."""
        best: tuple[str, int] | None = None
        for nid in self.cfg.nodes:
            try:
                st = self.status(nid, timeout=0.5)
            except grpc.RpcError:
                continue
            if st.role == "PRIMARY" and (best is None or st.epoch > best[1]):
                best = (nid, st.epoch)
        if best:
            self.primary = best[0]
        return best[0] if best else None

    def write(self, kind: str, code: str, lines: list[Line], note: str = "",
              req_id: str | None = None, retries: int = 1,
              product_name: str = "", unit: str = "") -> pb.WriteReply:
        v = pb.Voucher(
            req_id=req_id or uuid.uuid4().hex, kind=kind, code=code, note=note,
            lines=[pb.Line(sku=l.sku, qty=l.qty) for l in lines],
            product_name=product_name, unit=unit,
        )
        for attempt in range(retries + 1):
            try:
                r = self.inventory(self.primary).Write(v, timeout=self.timeout)
            except grpc.RpcError:
                if attempt == retries:
                    raise
                time.sleep(0.3)                # gửi lại CÙNG req_id (at-least-once + idempotent)
                self.find_primary()
                continue
            if not r.ok and r.error.startswith("NOT_PRIMARY") and attempt < retries:
                self.primary = r.primary_hint or self.find_primary() or self.primary
                continue
            return r
        raise AssertionError("unreachable")

    def khai_bao(self, ma: str, ten: str, dvt: str = "") -> pb.WriteReply:
        """Khai báo / sửa sản phẩm."""
        return self.write("SANPHAM", ma, [], product_name=ten, unit=dvt)

    def nhap(self, code: str, lines: list[Line], note: str = "") -> pb.WriteReply:
        return self.write("NHAP", code, lines, note)

    def xuat(self, code: str, lines: list[Line], note: str = "") -> pb.WriteReply:
        return self.write("XUAT", code, lines, note)

    def stock(self, node_id: str | None = None, skus: list[str] | None = None) -> pb.StockReply:
        # TODO: CHẾ ĐỘ CHỈ ĐỌC — node_id=None và bản chính lỗi gRPC -> CHUYỂN NGAY sang node
        #   còn sống có last_lsn lớn nhất; hòa thì theo thứ tự cfg.recovery_sources[primary].
        #   NHẤT QUÁN ĐỌC ĐỀU: nhớ lsn lớn nhất đã đọc; node tốt nhất còn lại cũ hơn => raise StaleRead.
        #   Đặc tả + test: tests/acceptance/test_readonly.py.
        return self.inventory(node_id or self.primary).GetStock(
            pb.StockQuery(skus=skus or []), timeout=self.timeout)

    # ------------------------------------------------------------------ quản trị
    def status(self, node_id: str, timeout: float | None = None) -> pb.NodeStatus:
        return self.admin(node_id).Status(pb.Empty(), timeout=timeout or self.timeout)

    def set_link_param(self, dst: str, param: float) -> pb.LinkInfo:
        """Đổi n của kênh đi VÀO `dst` (tự tìm node nguồn theo cấu hình)."""
        links = self.cfg.links_to(dst)
        if not links:
            raise ValueError(f"không có kênh nào đi vào {dst}")
        src = links[0].src
        return self.admin(src).SetLinkParam(pb.LinkParam(to_node=dst, param=param), timeout=self.timeout)

    def set_fault(self, src: str, dst: str, drop_rate: float = 0, delay_ms: int = 0,
                  partition: bool = False) -> None:
        self.admin(src).SetFault(
            pb.FaultRule(to_node=dst, drop_rate=drop_rate, delay_ms=delay_ms, partition=partition),
            timeout=self.timeout)

    def promote(self, node_id: str, exclude: list[str]) -> pb.NodeStatus:
        """NÂNG THỦ CÔNG node_id lên bản chính, loại các node `exclude` (đã chết thật) khỏi cụm."""
        st = self.admin(node_id).Promote(pb.PromoteRequest(exclude=exclude), timeout=self.timeout)
        self.primary = node_id
        return st

    def crash(self, node_id: str) -> None:
        try:
            self.admin(node_id).Crash(pb.Empty(), timeout=self.timeout)
        except grpc.RpcError:
            pass  # node chết ngay nên có thể không kịp trả lời
