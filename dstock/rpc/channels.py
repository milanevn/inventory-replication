"""Tạo kênh gRPC dùng chung cho node và client.

Lưu ý quan trọng: mặc định gRPC chờ kết nối lại theo backoff tăng tới ~120 giây.
Node bị tắt rồi bật lại sẽ "trông như vẫn chết" rất lâu => rút ngắn backoff cho demo.
"""
from __future__ import annotations

import grpc

CHANNEL_OPTIONS = [
    ("grpc.initial_reconnect_backoff_ms", 200),
    ("grpc.min_reconnect_backoff_ms", 200),
    ("grpc.max_reconnect_backoff_ms", 1000),
]


def make_channel(address: str, interceptors: tuple = ()) -> grpc.Channel:
    ch = grpc.insecure_channel(address, options=CHANNEL_OPTIONS)
    if interceptors:
        ch = grpc.intercept_channel(ch, *interceptors)
    return ch
