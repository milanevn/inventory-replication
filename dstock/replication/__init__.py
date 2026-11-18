"""Khung kênh nhân bản dùng chung cho cả 3 kiểu lan truyền (sync / interval / count)."""
from .link import ReplicationLink
from .triggers import make_trigger

__all__ = ["ReplicationLink", "make_trigger"]
