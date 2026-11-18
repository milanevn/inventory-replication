"""Sinh code Python từ proto/dstock.proto vào dstock/rpc/.

    python scripts/gen_proto.py

Chạy lại mỗi khi sửa .proto, rồi commit cả file sinh ra (để thành viên khác không phải tự sinh).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from grpc_tools import protoc

ROOT = Path(__file__).resolve().parent.parent
OUT = Path("dstock") / "rpc"


def main() -> int:
    # Dùng đường dẫn tương đối: protoc trên Windows dễ lỗi với đường dẫn có dấu tiếng Việt.
    os.chdir(ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    code = protoc.main([
        "grpc_tools.protoc",
        "-Iproto",
        f"--python_out={OUT}",
        f"--pyi_out={OUT}",
        f"--grpc_python_out={OUT}",
        "dstock.proto",
    ])
    if code != 0:
        print("protoc lỗi", file=sys.stderr)
        return code
    # grpc sinh `import dstock_pb2` (import tuyệt đối) -> đổi thành import tương đối trong package.
    grpc_file = OUT / "dstock_pb2_grpc.py"
    src = grpc_file.read_text(encoding="utf-8")
    src = re.sub(r"^import dstock_pb2 as", "from . import dstock_pb2 as", src, flags=re.M)
    grpc_file.write_text(src, encoding="utf-8", newline="\n")
    print(f"OK -> {OUT}/dstock_pb2.py, dstock_pb2_grpc.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
