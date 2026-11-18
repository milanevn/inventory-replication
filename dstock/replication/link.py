"""ReplicationLink — một kênh nhân bản một chiều nguồn -> đích, kiểu PUSH.

Chủ sở hữu: khung = TV1; heartbeat / backoff = TV2 (các chỗ TODO(TV2)). TV3 chỉ sửa triggers.py.

Kênh 1->2 (mode "sync") = ĐẨY NGAY, bản chính KHÔNG chờ xác nhận (đề: "tức thời").

Thuật toán (giống Redis/MySQL replication thu nhỏ):

    acked_lsn = -1                     # chưa biết đích có tới đâu
    vòng lặp (1 thread riêng):
        chờ có entry mới (notify) hoặc hết wait_timeout()
        nếu acked_lsn < 0: gửi Append rỗng (THĂM DÒ)
        nếu pending > 0 và trigger.due(pending, giây_từ_lần_gửi_trước, tuổi_entry_chờ_cũ_nhất):
            target = last_lsn(nguồn)
            lặp tới khi acked_lsn >= target: Append(oplog.since(acked_lsn))
        lỗi mạng -> state DOWN, GIỮ acked_lsn (lần gửi sau tự sửa con trỏ nhờ GAP/last_lsn)

Mỗi phản hồi Append mang (last_lsn, last_hash) của ĐÍCH => nguồn kiểm tra ĐẦU CHUỖI:
    - đích đi trước nguồn (last_lsn đích > last_lsn nguồn)  -> nguồn đã mất dữ liệu
    - hash tại last_lsn của đích khác hash của nguồn         -> hai chuỗi PHÂN KỲ
Cả hai: kênh chuyển DIVERGED và ngừng gửi; nếu nguồn là BẢN CHÍNH thì nguồn tự đánh dấu
CORRUPT (từ chối ghi) — không bao giờ cấp lại một LSN mà bản sao đã có.
"""
from __future__ import annotations

import logging
import threading
import time

import grpc

from ..config import LinkConfig
from ..rpc import dstock_pb2 as pb
from ..rpc.convert import entry_to_pb
from ..store import HEALTH_CORRUPT, NodeStore
from .triggers import make_trigger

log = logging.getLogger(__name__)

STATE_UNKNOWN = "UNKNOWN"
STATE_OK = "OK"
STATE_LAGGING = "LAGGING"     # đích tụt / từ chối tạm thời
STATE_DOWN = "DOWN"           # không gọi được đích
STATE_DIVERGED = "DIVERGED"   # đầu chuỗi hai bên không khớp — cần phục hồi (TV4), không tự gửi


class ReplicationLink:
    def __init__(
        self,
        cfg: LinkConfig,
        store: NodeStore,
        stub,                       # dstock_pb2_grpc.ReplicationStub tới đích
        max_batch: int = 200,
        rpc_timeout: float = 1.0,
        retry_delay: float = 0.5,
    ):
        self.cfg = cfg
        self.store = store
        self.stub = stub
        self.trigger = make_trigger(cfg)
        self.max_batch = max_batch
        self.rpc_timeout = rpc_timeout
        self.retry_delay = retry_delay

        self.acked_lsn = -1
        self.state = STATE_UNKNOWN
        self.last_error = ""
        self.last_flush_ts = 0.0                 # đồng hồ thường — để hiển thị
        self._last_flush_mono = time.monotonic()
        self._pending_since: float | None = None  # monotonic: lúc entry chờ CŨ NHẤT xuất hiện
        self._last_contact = 0.0                 # monotonic: lần cuối đích trả lời
        self._state_lock = threading.Lock()
        self._acked_cv = threading.Condition()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ vòng đời
    @property
    def name(self) -> str:
        return f"{self.cfg.src}->{self.cfg.dst}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"link {self.name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)

    def notify(self, lsn: int) -> None:
        """Store gọi khi có entry mới (NGOÀI khóa store)."""
        if self._pending_since is None:
            self._pending_since = time.monotonic()
        self._wake.set()

    # ------------------------------------------------------------------ điều khiển
    def set_param(self, value: float) -> None:
        self.trigger.set_param(value)
        self._wake.set()            # cho trigger đánh giá lại ngay với n mới

    @property
    def pending(self) -> int:
        """Số entry đích chưa xác nhận; -1 nếu chưa biết đích có tới đâu."""
        if self.acked_lsn < 0:
            return -1
        return max(0, self.store.last_lsn - self.acked_lsn)

    def oldest_pending_age(self) -> float:
        """Số giây entry chờ cũ nhất đã chờ (0 nếu không có gì chờ)."""
        since = self._pending_since
        return 0.0 if since is None else time.monotonic() - since

    def set_state(self, new: str, error: str = "") -> None:
        """MỌI chuyển trạng thái đi qua đây (thread kênh và thread gRPC Write cùng gọi)."""
        with self._state_lock:
            old, self.state = self.state, new
            self.last_error = error
        if old != new:
            lvl = logging.INFO if new == STATE_OK else logging.WARNING
            log.log(lvl, "[%s] %s -> %s%s", self.name, old, new, f" ({error})" if error else "")

    def wait_acked(self, lsn: int, timeout: float) -> bool:
        """Chờ tới khi đích xác nhận >= lsn hoặc hết timeout. Trả True nếu đã xác nhận."""
        with self._acked_cv:
            return self._acked_cv.wait_for(lambda: self.acked_lsn >= lsn, timeout=timeout)

    # ------------------------------------------------------------------ vòng lặp
    def _run(self) -> None:
        log.info("[%s] kênh bắt đầu (mode=%s, param=%s)", self.name, self.cfg.mode, self.trigger.param)
        while not self._stop.is_set():
            self._wake.wait(self.trigger.wait_timeout())
            self._wake.clear()
            if self._stop.is_set():
                break
            if self.state == STATE_DIVERGED:
                # Không gửi gì cho tới khi phục hồi xong; thỉnh thoảng thăm dò xem đã khớp lại chưa.
                self._stop.wait(1.0)
            try:
                if self.acked_lsn < 0 or self.state == STATE_DIVERGED:
                    self._send([])                      # thăm dò
                # TODO(TV2): HEARTBEAT — ~1s không liên lạc (self._last_contact) thì gửi Append rỗng,
                #   để phát hiện đích sập / đích mất dữ liệu ngay cả khi không có ghi mới.
                if self.state == STATE_DIVERGED:
                    continue
                pending = self.pending
                if pending > 0 and self._pending_since is None:
                    self._pending_since = time.monotonic()   # vd: đích vừa lên lại, còn thiếu
                since = time.monotonic() - self._last_flush_mono
                if pending > 0 and self.trigger.due(pending, since, self.oldest_pending_age()):
                    self._flush()
            except grpc.RpcError as exc:
                self._on_rpc_error(exc)
                # TODO(TV2): backoff tăng dần 0.5 -> 1 -> 2 -> tối đa 5s, về 0.5s khi gọi thành công.
                self._stop.wait(self.retry_delay)

    def _flush(self) -> None:
        # Chỉ gửi phần đang chờ TẠI LÚC kích hoạt; entry tới trong lúc gửi để lần kích hoạt sau
        # (nếu không, kênh interval/count sẽ "rò" entry mới đi sớm).
        started = time.monotonic()
        target = self.store.last_lsn
        while 0 <= self.acked_lsn < target and not self._stop.is_set() and self.state != STATE_DIVERGED:
            before = self.acked_lsn
            batch = self.store.oplog.since(self.acked_lsn, min(self.max_batch, target - self.acked_lsn))
            if not batch:
                break
            self._send(batch)
            if self.acked_lsn == before:                # đích không tiến => tránh lặp vô hạn
                break
        self._last_flush_mono = time.monotonic()
        self.last_flush_ts = time.time()
        # Entry tới trong lúc gửi: coi như bắt đầu chờ từ lúc bắt đầu lần gửi này.
        self._pending_since = started if self.pending > 0 else None

    def _send(self, batch) -> None:
        req = pb.AppendRequest(from_node=self.cfg.src, entries=[entry_to_pb(e) for e in batch],
                               epoch=self.store.epoch)
        reply = self.stub.Append(req, timeout=self.rpc_timeout)
        self._last_contact = time.monotonic()
        if not self._check_head(reply):
            return
        with self._acked_cv:
            self.acked_lsn = reply.last_lsn
            self._acked_cv.notify_all()
        if reply.ok or reply.error == "GAP":
            # GAP: đích thiếu phần trước -> acked_lsn vừa được đặt lại, lần gửi sau sẽ lấp.
            # Đang LAGGING thì chỉ về OK khi đích đã BẮT KỊP hẳn.
            if self.state == STATE_LAGGING and self.pending > 0:
                self.set_state(STATE_LAGGING)
            else:
                self.set_state(STATE_OK)
        else:
            self.set_state(STATE_LAGGING, reply.error)

    def _check_head(self, reply: pb.AppendReply) -> bool:
        """Kiểm tra đầu chuỗi của đích so với nguồn. False = phân kỳ (đã xử lý)."""
        st = self.store
        with st.lock:
            my_last = st.last_lsn
            my_hash = st.oplog.entries[reply.last_lsn - 1].hash if 0 < reply.last_lsn <= my_last else ""
        if reply.last_lsn > my_last:
            why = f"đích ở lsn {reply.last_lsn} > nguồn {my_last}: nguồn đã mất dữ liệu"
        elif reply.last_lsn > 0 and reply.last_hash and reply.last_hash != my_hash:
            why = f"hash tại lsn {reply.last_lsn} khác nhau"
        else:
            return True
        self.set_state(STATE_DIVERGED, why)
        if st.is_primary and reply.last_lsn > my_last and st.health != HEALTH_CORRUPT:
            st.mark(HEALTH_CORRUPT, f"bản sao {self.cfg.dst} đi trước bản chính ({why}) — cần phục hồi")
            log.error("[%s] %s", self.cfg.src, st.detail)
        return False

    def _on_rpc_error(self, exc: grpc.RpcError) -> None:
        code = exc.code() if hasattr(exc, "code") else None
        # GIỮ acked_lsn: lần gửi sau đích sẽ trả GAP/last_lsn nếu nó đã mất dữ liệu.
        self.set_state(STATE_DOWN, str(code))

    # ------------------------------------------------------------------ quan sát
    def info(self, fault: str = "") -> pb.LinkInfo:
        return pb.LinkInfo(
            from_node=self.cfg.src,
            to_node=self.cfg.dst,
            mode=self.cfg.mode,
            param=self.trigger.param,
            acked_lsn=self.acked_lsn,
            pending=self.pending,
            state=self.state,
            last_flush_ts=self.last_flush_ts,
            fault=fault,
            detail=self.last_error,
        )
