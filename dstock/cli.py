"""CLI điều khiển cụm.

    python -m dstock.cli seed                       # khai báo + nhập sẵn vài mặt hàng
    python -m dstock.cli sanpham SP01 "Bút bi" --dvt cây   # khai báo / sửa sản phẩm
    python -m dstock.cli nhap PN001 SP01:10 SP02:5 --note "Nhập đầu kỳ"
    python -m dstock.cli xuat PX001 SP01:3
    python -m dstock.cli ton                        # đọc ở N1
    python -m dstock.cli ton --node N4
    python -m dstock.cli status                     # bảng tóm tắt 4 node
    python -m dstock.cli set-n N4 5                 # kênh N2->N4: gửi sau 5 lần
    python -m dstock.cli set-n N3 10                # kênh N1->N3: gửi sau 10 giây
    python -m dstock.cli fault N1 N3 --partition    # cắt kênh N1->N3   (TV5)
    python -m dstock.cli fault N1 N3                # gỡ lỗi
    python -m dstock.cli crash N3                   # giết tiến trình N3
    python -m dstock.cli promote N3 --exclude N1 N2 # NÂNG THỦ CÔNG N3 lên bản chính (N1, N2 đã chết)
"""
from __future__ import annotations

import argparse
import sys

import grpc

from .client import DStockClient, parse_lines
from .config import load_config


def _print_write(r) -> None:
    if r.ok:
        extra = " (trùng req_id — không ghi lại)" if r.duplicate else ""
        sync = " | N2 đã xác nhận" if r.replicated_sync else ""
        print(f"OK lsn={r.lsn}{sync}{extra}")
    else:
        print(f"LỖI {r.error}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="dstock.cli", description="Điều khiển cụm DStock")
    ap.add_argument("--config", default="cluster.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("nhap", "xuat"):
        p = sub.add_parser(name)
        p.add_argument("code")
        p.add_argument("lines", nargs="+", help="MA:SOLUONG ...")
        p.add_argument("--note", default="")
    sub.add_parser("seed")
    p = sub.add_parser("sanpham"); p.add_argument("ma"); p.add_argument("ten"); p.add_argument("--dvt", default="")
    p = sub.add_parser("promote"); p.add_argument("node"); p.add_argument("--exclude", nargs="+", default=[])
    p = sub.add_parser("ton"); p.add_argument("--node"); p.add_argument("skus", nargs="*")
    sub.add_parser("status")
    p = sub.add_parser("set-n"); p.add_argument("dst"); p.add_argument("value", type=float)
    p = sub.add_parser("fault")
    p.add_argument("src"); p.add_argument("dst")
    p.add_argument("--drop", type=float, default=0); p.add_argument("--delay", type=int, default=0)
    p.add_argument("--partition", action="store_true")
    p = sub.add_parser("crash"); p.add_argument("node")

    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    c = DStockClient(cfg)
    try:
        if args.cmd in ("nhap", "xuat"):
            _print_write(c.write(args.cmd.upper(), args.code, parse_lines(args.lines), args.note))
        elif args.cmd == "seed":
            for ma, ten, dvt in (("SP01", "Bút bi", "cây"), ("SP02", "Vở 200 trang", "quyển"),
                                 ("SP03", "Thước kẻ", "cái")):
                c.khai_bao(ma, ten, dvt)
            _print_write(c.nhap("PN-SEED", parse_lines(["SP01:100", "SP02:50", "SP03:20"]), "Tồn đầu kỳ"))
        elif args.cmd == "sanpham":
            _print_write(c.khai_bao(args.ma, args.ten, args.dvt))
        elif args.cmd == "promote":
            st = c.promote(args.node, args.exclude)
            print(f"{st.node_id} là bản chính, epoch {st.epoch}, thành viên {list(st.members)}")
        elif args.cmd == "ton":
            r = c.stock(args.node, args.skus)
            print(f"{r.node_id} @ lsn {r.lsn}")
            for sku in sorted(r.stock):
                print(f"  {sku:<10} {r.stock[sku]:>8}")
        elif args.cmd == "status":
            for nid in cfg.nodes:
                try:
                    s = c.status(nid, timeout=0.5)
                    links = "  ".join(f"->{l.to_node}[{l.mode}={l.param:g} acked={l.acked_lsn} "
                                      f"chờ={l.pending if l.pending >= 0 else '?'} {l.state}]"
                                      for l in s.links)
                    q = (" quorum=" + ("có" if s.has_quorum else "KHÔNG")) if s.role == "PRIMARY" else ""
                    print(f"{nid} {s.role:<8} {s.health:<10} epoch={s.epoch} lsn={s.last_lsn:<5} "
                          f"digest={s.state_digest[:8]}{q}  {links}")
                except grpc.RpcError:
                    print(f"{nid} DOWN")
        elif args.cmd == "set-n":
            info = c.set_link_param(args.dst, args.value)
            print(f"kênh {info.from_node}->{info.to_node} ({info.mode}) param={info.param:g}")
        elif args.cmd == "fault":
            c.set_fault(args.src, args.dst, args.drop, args.delay, args.partition)
            print("đã đặt luật gây lỗi" if (args.drop or args.delay or args.partition) else "đã gỡ lỗi")
        elif args.cmd == "crash":
            c.crash(args.node)
            print(f"đã gửi lệnh crash tới {args.node}")
    except grpc.RpcError as exc:
        print(f"Không gọi được node: {exc.code().name} — {exc.details()}")
        return 1
    except ValueError as exc:
        print(f"Sai tham số: {exc}")
        return 2
    finally:
        c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
