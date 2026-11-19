"""Chạy cả cụm bằng một lệnh: mỗi node là một tiến trình riêng, log ghi vào data/logs/<id>.log.

    python scripts/run_cluster.py            # chạy N1..N4
    python scripts/run_cluster.py --clean    # xóa data/ trước khi chạy (bắt đầu sạch)
    python scripts/run_cluster.py N1 N2      # chỉ chạy một số node
    python scripts/run_cluster.py N2 --config cluster.lan.toml   # cách B: máy này chỉ chạy N2
    python scripts/run_cluster.py --gui      # chạy kèm bảng điều khiển

Ctrl+C để dừng tất cả. Muốn "sập" một node: bấm Crash trên GUI hoặc `python -m dstock.cli crash N3`.
Muốn bật lại node đó:  python -m dstock.node --id N3   (ở terminal khác)
Lỡ đóng cửa sổ terminal (không Ctrl+C) => node còn chạy ngầm:  python scripts/stop_cluster.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("nodes", nargs="*", default=["N1", "N2", "N3", "N4"])
    ap.add_argument("--clean", action="store_true", help="xóa thư mục data trước khi chạy")
    ap.add_argument("--gui", action="store_true", help="mở bảng điều khiển")
    ap.add_argument("--config", default="cluster.toml", help="cluster.toml (cả cụm 1 máy) | cluster.lan.toml")
    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    os.chdir(ROOT)  # đường dẫn tương đối => tránh lỗi đường dẫn tiếng Việt
    if args.clean and Path("data").exists():
        shutil.rmtree("data")
    Path("data/logs").mkdir(parents=True, exist_ok=True)

    procs: list[tuple[str, subprocess.Popen]] = []
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    for nid in args.nodes:
        logf = open(f"data/logs/{nid}.log", "a", encoding="utf-8")
        p = subprocess.Popen([sys.executable, "-m", "dstock.node", "--id", nid, "--config", args.config],
                             stdout=logf, stderr=subprocess.STDOUT, env=env)
        procs.append((nid, p))
        print(f"{nid}: pid {p.pid}  (log: data/logs/{nid}.log)")
    # Ghi cả PID của chính launcher (nó giữ file log mở) để stop_cluster.py tắt sạch.
    pids = [p.pid for _, p in procs] + [os.getpid()]
    Path("data/pids.txt").write_text(" ".join(map(str, pids)) + "\n", encoding="utf-8")
    if args.gui:
        procs.append(("GUI", subprocess.Popen([sys.executable, "-m", "dstock.gui", "--config", args.config],
                                              env=env)))

    print("Đang chạy. Ctrl+C để dừng tất cả.")
    try:
        while True:
            time.sleep(1)
            for nid, p in procs:
                if p.poll() is not None and not getattr(p, "_reported", False):
                    p._reported = True  # type: ignore[attr-defined]
                    print(f"{nid} đã thoát (mã {p.returncode})")
    except KeyboardInterrupt:
        pass
    finally:
        for _, p in procs:
            if p.poll() is None:
                p.terminate()
        for _, p in procs:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        # Tắt hết rồi thì PID cũ không còn nghĩa; để lại thì stop_cluster.py có thể tắt nhầm
        # chương trình khác được cấp lại PID đó.
        Path("data/pids.txt").unlink(missing_ok=True)
        print("Đã dừng.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
