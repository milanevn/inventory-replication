"""Checkpoint (khắc phục lùi dựa trên TRẠNG THÁI — bài 12).

File data/<node>/checkpoint.json:
    {"lsn": 120, "last_hash": "...", "stock": {...}, "checksum": "sha256 của 3 field trên"}

Đã có: save / load có checksum. TODO: dùng trong recovery.py (qua store.add_listener).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .oplog import _replace_with_retry


@dataclass
class Checkpoint:
    lsn: int
    last_hash: str
    stock: dict[str, int]

    def checksum(self) -> str:
        body = json.dumps([self.lsn, self.last_hash, sorted(self.stock.items())], separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()


def save(path: Path, cp: Checkpoint) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"lsn": cp.lsn, "last_hash": cp.last_hash, "stock": cp.stock, "checksum": cp.checksum()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    _replace_with_retry(tmp, path)


def load(path: Path) -> Checkpoint | None:
    """Trả None nếu không có file hoặc checksum sai (checkpoint hỏng => bỏ qua, replay log)."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        cp = Checkpoint(int(d["lsn"]), d["last_hash"], {k: int(v) for k, v in d["stock"].items()})
    except (ValueError, KeyError, TypeError):
        return None
    return cp if cp.checksum() == d.get("checksum") else None
