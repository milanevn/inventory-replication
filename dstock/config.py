"""Đọc cấu hình cụm (cluster.toml).

Chủ sở hữu: TV1 (tech lead).
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

LINK_MODES = ("sync", "interval", "count")


@dataclass(frozen=True)
class NodeAddr:
    id: str
    host: str
    port: int

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class LinkConfig:
    src: str
    dst: str
    mode: str      # sync | interval | count
    param: float   # sync: không dùng | interval: n giây | count: n lần


@dataclass
class ClusterConfig:
    nodes: dict[str, NodeAddr]
    primary: str
    links: list[LinkConfig]
    data_dir: Path = Path("data")
    snapshot_every: int = 50
    recovery_sources: dict[str, list[str]] = field(default_factory=dict)

    def links_from(self, node_id: str) -> list[LinkConfig]:
        return [l for l in self.links if l.src == node_id]

    def links_to(self, node_id: str) -> list[LinkConfig]:
        return [l for l in self.links if l.dst == node_id]

    def node_data_dir(self, node_id: str) -> Path:
        return self.data_dir / node_id

    def validate(self) -> None:
        if self.primary not in self.nodes:
            raise ValueError(f"primary {self.primary!r} không có trong [nodes]")
        for l in self.links:
            if l.src not in self.nodes or l.dst not in self.nodes:
                raise ValueError(f"link {l.src}->{l.dst} trỏ tới node không tồn tại")
            if l.mode not in LINK_MODES:
                raise ValueError(f"link {l.src}->{l.dst}: mode {l.mode!r} không hợp lệ")
            if l.param <= 0:
                raise ValueError(f"link {l.src}->{l.dst}: param phải > 0")


def load_config(path: str | Path = "cluster.toml") -> ClusterConfig:
    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)
    return parse_config(raw, base_dir=path.parent)


def parse_config(raw: dict, base_dir: Path = Path(".")) -> ClusterConfig:
    nodes = {
        nid: NodeAddr(nid, v.get("host", "127.0.0.1"), int(v["port"]))
        for nid, v in raw["nodes"].items()
    }
    links = [
        LinkConfig(src=l["from"], dst=l["to"], mode=l["mode"], param=float(l.get("param", 1)))
        for l in raw.get("links", [])
    ]
    data_dir = Path(raw.get("data_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir
    cfg = ClusterConfig(
        nodes=nodes,
        primary=raw["primary"],
        links=links,
        data_dir=data_dir,
        snapshot_every=int(raw.get("snapshot_every", 50)),
        recovery_sources={k: list(v) for k, v in raw.get("recovery_sources", {}).items()},
    )
    cfg.validate()
    return cfg
