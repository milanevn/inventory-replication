"""Chuyển đổi giữa dataclass nội bộ và message protobuf."""
from __future__ import annotations

from ..domain import Line, Voucher
from ..oplog import Entry
from . import dstock_pb2 as pb


def lines_to_pb(lines) -> list[pb.Line]:
    return [pb.Line(sku=l.sku, qty=l.qty) for l in lines]


def lines_from_pb(lines) -> list[Line]:
    return [Line(l.sku, int(l.qty)) for l in lines]


def voucher_from_pb(v: pb.Voucher) -> Voucher:
    return Voucher(req_id=v.req_id, kind=v.kind, code=v.code, lines=lines_from_pb(v.lines), note=v.note,
                   product_name=v.product_name, unit=v.unit)


def voucher_to_pb(v: Voucher) -> pb.Voucher:
    return pb.Voucher(req_id=v.req_id, kind=v.kind, code=v.code, lines=lines_to_pb(v.lines), note=v.note,
                      product_name=v.product_name, unit=v.unit)


def entry_to_pb(e: Entry) -> pb.Entry:
    return pb.Entry(
        lsn=e.lsn, req_id=e.req_id, kind=e.kind, code=e.code, lines=lines_to_pb(e.lines),
        note=e.note, ts=e.ts, prev_hash=e.prev_hash, hash=e.hash,
        product_name=e.product_name, unit=e.unit, epoch=e.epoch,
    )


def entry_from_pb(m: pb.Entry) -> Entry:
    return Entry(
        lsn=m.lsn, req_id=m.req_id, kind=m.kind, code=m.code, lines=tuple(lines_from_pb(m.lines)),
        note=m.note, ts=m.ts, prev_hash=m.prev_hash, hash=m.hash,
        product_name=m.product_name, unit=m.unit, epoch=m.epoch,
    )
