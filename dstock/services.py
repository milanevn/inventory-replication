"""Cài đặt 3 service gRPC của một node. Mỏng: chỉ chuyển đổi message rồi gọi Node/Store.

Chủ sở hữu: TV1. Điểm móc của thành viên (KHÔNG cần sửa file này):
  - quorum (TV2)        : node.has_quorum()         — dstock/membership.py
  - nâng bản chính (TV1): node.promote(exclude)     — dstock/failover.py
  - phục hồi (TV4)      : FetchSince đã có sẵn      — dstock/recovery.py
"""
from __future__ import annotations

import logging
import os
import threading

import grpc
from typing import TYPE_CHECKING

from .errors import DStockError
from .faults import Rule
from .rpc import dstock_pb2 as pb
from .rpc import dstock_pb2_grpc as pbg
from .rpc.convert import entry_from_pb, entry_to_pb, voucher_from_pb

if TYPE_CHECKING:
    from .node import Node

log = logging.getLogger(__name__)


class InventoryService(pbg.InventoryServicer):
    def __init__(self, node: "Node"):
        self.node = node

    def Write(self, request: pb.Voucher, context) -> pb.WriteReply:
        node = self.node
        if not node.store.is_primary:
            return pb.WriteReply(ok=False, error=f"NOT_PRIMARY: {node.id} không phải bản chính",
                                 primary_hint=node.primary_id)
        if not node.has_quorum():
            # Không thấy đa số thành viên => có thể đang bị CÔ LẬP khỏi phần lớn cụm: ghi tiếp thì
            # có nguy cơ hai bản chính (split-brain). Từ chối, chỉ cho đọc.
            return pb.WriteReply(ok=False, error=f"NO_QUORUM: {node.id} không thấy đa số thành viên "
                                                 f"{node.members} — tạm từ chối ghi")
        try:
            entry, dup = node.store.write(voucher_from_pb(request))
        except DStockError as exc:
            return pb.WriteReply(ok=False, error=f"{exc.code}: {exc}", primary_hint=node.primary_id)
        # 1->2 "tức thời": KHÔNG chờ N2 xác nhận. Store đã báo các kênh (notify) — kênh sync đẩy ngay.
        log.info("[%s] ghi %s %s -> lsn %d%s", node.id, request.kind, request.code,
                 entry.lsn, " (trùng req_id)" if dup else "")
        return pb.WriteReply(ok=True, lsn=entry.lsn, duplicate=dup)

    def GetStock(self, request: pb.StockQuery, context) -> pb.StockReply:
        snap = self.node.store.snapshot()
        stock = {k: snap.stock.get(k, 0) for k in request.skus} if request.skus else snap.stock
        return pb.StockReply(
            node_id=self.node.id,
            lsn=snap.last_lsn,
            stock=stock,
            last_apply_ts=snap.last_apply_ts,
            health=snap.health,          # CORRUPT => số liệu có thể thiếu, client phải cảnh báo
        )


class ReplicationService(pbg.ReplicationServicer):
    def __init__(self, node: "Node"):
        self.node = node

    def Append(self, request: pb.AppendRequest, context) -> pb.AppendReply:
        entries = [entry_from_pb(m) for m in request.entries]
        # TODO(TV1): CHẶN BẢN CHÍNH CŨ — request.epoch < self.node.store.epoch thì trả
        #   AppendReply(ok=False, error="STALE_EPOCH", epoch=store.epoch) và KHÔNG áp dụng gì.
        #   request.epoch > store.epoch: nhận bản chính mới (lưu epoch/primary vào meta).
        r = self.node.store.apply_replicated(entries)
        if entries and not r.error:
            log.debug("[%s] nhận %d entry từ %s -> lsn %d", self.node.id, len(entries), request.from_node,
                      r.last_lsn)
        return pb.AppendReply(ok=not r.error, last_lsn=r.last_lsn, error=r.error, last_hash=r.last_hash,
                              epoch=self.node.store.epoch)

    def FetchSince(self, request: pb.FetchRequest, context):
        # TV4 dùng khi phục hồi. Chỉ trả phần TỐT của oplog (store đã cắt phần hỏng khi load).
        for e in self.node.store.oplog.since(request.after_lsn):
            yield entry_to_pb(e)


class AdminService(pbg.AdminServicer):
    def __init__(self, node: "Node"):
        self.node = node

    def Status(self, request, context) -> pb.NodeStatus:
        return self.node.status()

    def SetLinkParam(self, request: pb.LinkParam, context) -> pb.LinkInfo:
        link = self.node.link_to(request.to_node)
        if link is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"{self.node.id} không có kênh tới {request.to_node}")
        try:
            link.set_param(request.param)
        except ValueError as exc:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        log.info("[%s] đổi tham số kênh %s = %s", self.node.id, link.name, request.param)
        return link.info(self.node.faults.describe(link.cfg.dst))

    def SetFault(self, request: pb.FaultRule, context) -> pb.Empty:
        rule = Rule(request.drop_rate, request.delay_ms, request.partition)
        self.node.faults.set_rule(request.to_node or "*", rule)
        log.warning("[%s] gây lỗi kênh tới %s: %s", self.node.id, request.to_node or "*",
                    rule.describe() or "(gỡ lỗi)")
        return pb.Empty()

    def Promote(self, request: pb.PromoteRequest, context) -> pb.NodeStatus:
        try:
            self.node.promote(list(request.exclude))
        except NotImplementedError as exc:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, str(exc))
        except DStockError as exc:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, f"{exc.code}: {exc}")
        return self.node.status()

    def Crash(self, request, context) -> pb.Empty:
        log.warning("[%s] nhận lệnh CRASH — tắt tiến trình", self.node.id)
        threading.Timer(0.1, os._exit, args=(1,)).start()
        return pb.Empty()
