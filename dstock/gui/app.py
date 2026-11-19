"""Bảng điều khiển Tkinter (GUI) — chỉ là CLIENT: quan sát + điều khiển, KHÔNG chứa logic phân tán.

    python -m dstock.gui

Kiến trúc luồng (quan trọng với Tkinter: CHỈ thread chính được đụng vào widget):
    thread "poller"  : mỗi 0.5s gọi Admin.Status 4 node -> đẩy kết quả vào queue
    thread "action"  : mỗi thao tác (ghi phiếu, đổi n, crash) chạy ở thread riêng -> đẩy log vào queue
    thread chính     : root.after(150ms) lấy queue -> vẽ lại

Việc cần làm (TODO), để chạy được kịch bản trong docs/demo.md:
  1. Khung "Gây lỗi mạng": chọn kênh nguồn -> đích, cắt / gỡ (bắt buộc), bỏ x% gói, trễ y ms (tùy
     chọn) -> client.set_fault(...).
  2. Form khai báo sản phẩm (client.khai_bao).
  3. Mỗi thẻ node hiện epoch, members và có đủ đa số hay không (NodeStatus.epoch, members, has_quorum).
  4. Nút "Nâng lên bản chính": chọn node và các node loại trừ, HỎI XÁC NHẬN rồi mới gọi
     client.promote(...); báo rõ lỗi khi promote bị từ chối.
  5. Chế độ chỉ đọc: khi không gọi được bản chính, khung tồn kho đọc qua client.stock() (tự chọn node
     mới nhất) và hiện node đang đọc, lsn, cảnh báo dữ liệu có thể cũ.
  6. Độ lệch của N3 (giây) và N4 (số thao tác) so với bản chính.
  Bản chính để so sánh lấy từ trạng thái các node (_ban_chinh), không lấy từ cấu hình: sau khi nâng
  tay thì cfg.primary không còn đúng.
"""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import grpc

from ..client import ClusterClient, parse_lines
from ..config import ClusterConfig, load_config

POLL_SEC = 0.5
# Vị trí các node trên lưới — vẽ giống sơ đồ đề bài:  N1 -> N2 -> N4 ;  N1 -> N3
LAYOUT = {"N1": (0, 0, 2), "N2": (0, 1, 1), "N4": (0, 2, 1), "N3": (1, 1, 1)}  # row, col, rowspan

C_OK, C_BAD, C_WARN, C_DOWN = "#2e7d32", "#c62828", "#ef6c00", "#757575"
HEALTH_COLOR = {"OK": C_OK, "CORRUPT": C_BAD, "RECOVERING": C_WARN, "DOWN": C_DOWN}
LINK_COLOR = {"OK": C_OK, "LAGGING": C_WARN, "DOWN": C_BAD, "DIVERGED": C_BAD, "UNKNOWN": C_DOWN}


class NodeCard(ttk.LabelFrame):
    def __init__(self, master, node_id: str, on_crash):
        super().__init__(master, text=f" {node_id} ", padding=6)
        self.node_id = node_id
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.badge = tk.Label(top, text="…", fg="white", bg=C_DOWN, padx=6, font=("Segoe UI", 9, "bold"))
        self.badge.pack(side="left")
        self.role = ttk.Label(top, text="", font=("Segoe UI", 9))
        self.role.pack(side="left", padx=6)
        ttk.Button(top, text="Crash", width=7, command=lambda: on_crash(node_id)).pack(side="right")
        self.info = ttk.Label(self, text="", font=("Consolas", 9))
        self.info.pack(fill="x", pady=(4, 2))
        self.tree = ttk.Treeview(self, columns=("ton",), height=4, show="tree headings")
        self.tree.heading("#0", text="Mã hàng")
        self.tree.heading("ton", text="Tồn")
        self.tree.column("#0", width=90)
        self.tree.column("ton", width=70, anchor="e")
        self.tree.tag_configure("diff", background="#ffe0b2")
        self.tree.pack(fill="both", expand=True)

    def show(self, st, primary_st) -> None:
        if st is None:
            self.badge.config(text="DOWN", bg=C_DOWN)
            self.role.config(text="")
            self.info.config(text="không liên lạc được")
            self.tree.delete(*self.tree.get_children())
            return
        self.badge.config(text=st.health, bg=HEALTH_COLOR.get(st.health, C_WARN))
        self.role.config(text=st.role)
        lag = ""
        if primary_st is not None and st.node_id != primary_st.node_id:
            behind = primary_st.last_lsn - st.last_lsn
            age = time.time() - st.last_apply_ts if st.last_apply_ts else 0
            lag = f"\nchậm {behind} thao tác" + (f", bản ghi cuối {age:.0f}s trước" if behind else "")
        self.info.config(text=f"lsn {st.last_lsn}   digest {st.state_digest[:8]}{lag}"
                              + (f"\n{st.detail}" if st.detail else ""))
        ref = dict(primary_st.stock) if primary_st is not None else {}
        self.tree.delete(*self.tree.get_children())
        for sku in sorted(set(st.stock) | set(ref)):
            v = st.stock.get(sku, 0)
            tag = ("diff",) if ref and ref.get(sku, 0) != v else ()
            self.tree.insert("", "end", text=sku, values=(v,), tags=tag)


class Dashboard:
    def __init__(self, root: tk.Tk, cfg: ClusterConfig):
        self.root = root
        self.cfg = cfg
        self.client = ClusterClient(cfg, timeout=1.0)
        self.q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._last_health: dict[str, str] = {}

        root.title("Bảng điều khiển cụm")
        try:
            root.state("zoomed")          # Windows: phóng to vừa màn hình (kể cả khi bật scale 125%)
        except tk.TclError:
            root.geometry("1180x760")
        ttk.Style().theme_use("clam")

        # Đóng gói phần dưới TRƯỚC (side="bottom") để luôn hiển thị; sơ đồ node co giãn phần còn lại.
        self._build_log(root)
        bottom = ttk.Frame(root, padding=(8, 0, 8, 4))
        bottom.pack(side="bottom", fill="x")
        self._build_links(bottom)
        self._build_write(bottom)

        # --- sơ đồ node ---
        grid = ttk.Frame(root, padding=8)
        grid.pack(fill="both", expand=True)
        self.cards: dict[str, NodeCard] = {}
        for nid in cfg.nodes:
            r, c, span = LAYOUT.get(nid, (2, len(self.cards), 1))
            card = NodeCard(grid, nid, self.crash)
            card.grid(row=r, column=c, rowspan=span, sticky="nsew", padx=4, pady=4)
            self.cards[nid] = card
        for c in range(3):
            grid.columnconfigure(c, weight=1)
        for r in range(2):
            grid.rowconfigure(r, weight=1)

        threading.Thread(target=self._poll_loop, daemon=True, name="poller").start()
        self._after_id = root.after(150, self._drain)
        root.protocol("WM_DELETE_WINDOW", self.close)

    # ------------------------------------------------------------------ khung giao diện
    def _build_links(self, parent) -> None:
        f = ttk.LabelFrame(parent, text=" Kênh nhân bản ", padding=6)
        f.pack(side="left", fill="both", expand=True, padx=(0, 4))
        cols = ("mode", "param", "acked", "pending", "state", "fault")
        heads = ("Kiểu", "n / timeout", "Đích đã có", "Đang chờ", "Trạng thái", "Gây lỗi")
        self.links = ttk.Treeview(f, columns=cols, height=3, show="tree headings")
        self.links.heading("#0", text="Kênh")
        self.links.column("#0", width=80)
        for c, h in zip(cols, heads):
            self.links.heading(c, text=h)
            self.links.column(c, width=80, anchor="center")
        for st, color in LINK_COLOR.items():
            self.links.tag_configure(st, foreground=color)
        self.links.pack(fill="x")
        ctl = ttk.Frame(f)
        ctl.pack(fill="x", pady=(6, 0))
        ttk.Label(ctl, text="Đổi n kênh vào").pack(side="left")
        targets = [l.dst for l in self.cfg.links]
        self.n_target = ttk.Combobox(ctl, values=targets, width=5, state="readonly")
        self.n_target.set(targets[-1] if targets else "")
        self.n_target.pack(side="left", padx=4)
        self.n_value = ttk.Entry(ctl, width=6)
        self.n_value.pack(side="left")
        ttk.Button(ctl, text="Áp dụng", command=self.set_n).pack(side="left", padx=4)
        # TODO: khung "Gây lỗi mạng": chọn kênh + cắt / bỏ x% / trễ y ms -> client.set_fault(...)

    def _build_write(self, parent) -> None:
        f = ttk.LabelFrame(parent, text=" Ghi phiếu (gửi tới bản chính) ", padding=6)
        f.pack(side="left", fill="both")
        self.kind = ttk.Combobox(f, values=["NHAP", "XUAT"], width=6, state="readonly")
        self.kind.set("NHAP")
        self.code = ttk.Entry(f, width=10)
        self.lines = ttk.Entry(f, width=24)
        self.note = ttk.Entry(f, width=24)
        for i, (lbl, w) in enumerate([("Loại", self.kind), ("Số phiếu", self.code),
                                      ("Dòng hàng", self.lines), ("Ghi chú", self.note)]):
            ttk.Label(f, text=lbl).grid(row=i, column=0, sticky="w")
            w.grid(row=i, column=1, sticky="we", pady=1)
        self.code.insert(0, "PN001")
        self.lines.insert(0, "SP01:10 SP02:5")
        ttk.Button(f, text="Gửi", command=self.write).grid(row=4, column=1, sticky="e", pady=(4, 0))

    def _build_log(self, parent) -> None:
        f = ttk.LabelFrame(parent, text=" Nhật ký ", padding=4)
        f.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        self.log = tk.Text(f, height=5, font=("Consolas", 9), state="disabled")
        self.log.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ thread nền
    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            snap = {}
            for nid in self.cfg.nodes:
                try:
                    snap[nid] = self.client.status(nid, timeout=0.4)
                except grpc.RpcError:
                    snap[nid] = None
            self.q.put(("status", snap))
            self._stop.wait(POLL_SEC)

    def _run_action(self, label: str, fn) -> None:
        def work():
            try:
                self.q.put(("log", f"{label}: {fn()}"))
            except grpc.RpcError as exc:
                self.q.put(("log", f"{label}: LỖI gọi node — {exc.code().name} {exc.details() or ''}"))
            except Exception as exc:  # hiển thị mọi lỗi cho người demo thấy
                self.q.put(("log", f"{label}: LỖI — {exc}"))
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ thao tác
    def write(self) -> None:
        kind, code, lines, note = self.kind.get(), self.code.get().strip(), self.lines.get(), self.note.get()

        def do():
            r = self.client.write(kind, code, parse_lines([lines]), note)
            return f"OK lsn={r.lsn}" + (" (N2 đã xác nhận)" if r.replicated_sync else "") if r.ok else r.error
        self._run_action(f"{kind} {code}", do)

    def set_n(self) -> None:
        dst, raw = self.n_target.get(), self.n_value.get().strip()

        def do():
            info = self.client.set_link_param(dst, float(raw))
            return f"kênh {info.from_node}->{info.to_node} ({info.mode}) = {info.param:g}"
        self._run_action("Đổi n", do)

    def crash(self, nid: str) -> None:
        if not messagebox.askyesno("Crash node", f"Tắt hẳn tiến trình {nid}?", parent=self.root):
            return
        self._run_action(f"Crash {nid}", lambda: (self.client.crash(nid), "đã gửi lệnh")[1])

    # ------------------------------------------------------------------ vẽ lại (thread chính)
    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self._render(payload)
                else:
                    self._append_log(payload)
        except queue.Empty:
            pass
        if not self._stop.is_set():
            self._after_id = self.root.after(150, self._drain)

    @staticmethod
    def _ban_chinh(snap: dict):
        """Status của bản chính hiện tại: node PRIMARY có epoch lớn nhất (sau khi nâng tay thì
        cfg.primary không còn đúng). None nếu không node nào đang là bản chính."""
        prim = [st for st in snap.values() if st is not None and st.role == "PRIMARY"]
        return max(prim, key=lambda st: st.epoch) if prim else None

    def _render(self, snap: dict) -> None:
        primary = self._ban_chinh(snap)
        for nid, card in self.cards.items():
            card.show(snap.get(nid), primary)
            health = snap[nid].health if snap.get(nid) else "DOWN"
            if self._last_health.get(nid, health) != health:
                self._append_log(f"{nid}: {self._last_health[nid]} -> {health}")
            self._last_health[nid] = health
        self.links.delete(*self.links.get_children())
        for st in snap.values():
            if st is None:
                continue
            for l in st.links:
                acked = "?" if l.acked_lsn < 0 else l.acked_lsn
                pending = "?" if l.pending < 0 else l.pending
                self.links.insert("", "end", text=f"{l.from_node}→{l.to_node}", tags=(l.state,),
                                  values=(l.mode, f"{l.param:g}", acked, pending, l.state, l.fault or "-"))

    def _append_log(self, msg: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def close(self) -> None:
        self._stop.set()
        self.root.after_cancel(self._after_id)
        self.client.close()
        self.root.destroy()


def main(config: str = "cluster.toml") -> None:
    root = tk.Tk()
    Dashboard(root, load_config(config))
    root.mainloop()
