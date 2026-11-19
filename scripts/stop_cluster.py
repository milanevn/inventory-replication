"""Tắt các node còn chạy ngầm (vd: lỡ đóng cửa sổ terminal của run_cluster.py).

    python scripts/stop_cluster.py

Tắt theo data/pids.txt; sau đó kiểm tra lại các cổng trong cluster.toml.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def la_python(pid: int) -> bool:
    """PID trong pids.txt có thể đã bị hệ điều hành cấp lại cho chương trình khác (Windows dùng lại
    PID rất nhanh) => chỉ tắt khi tiến trình đó đúng là python."""
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="replace").stdout
        return out.strip().lower().startswith('"python')
    out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True).stdout
    return "python" in out.lower()


def kill(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else "cluster.toml"
    os.chdir(ROOT)
    pids = Path("data/pids.txt")
    if pids.exists():
        for line in pids.read_text(encoding="utf-8").split():
            pid = int(line)
            if la_python(pid):
                kill(pid)
                print(f"đã tắt pid {pid}")
            else:
                print(f"bỏ qua pid {pid}: không còn là tiến trình python của cụm")
        pids.unlink()
    sys.path.insert(0, str(ROOT))
    from dstock.config import load_config
    busy = []
    for n in load_config(config).nodes.values():
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex((n.host, n.port)) == 0:
                busy.append(f"{n.id} ({n.address})")
    if busy:
        print("Cổng vẫn bận:", ", ".join(busy), "— Windows: netstat -ano | findstr 700  rồi taskkill /F /PID <pid>")
        return 1
    print("Sạch: không còn node nào chạy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
