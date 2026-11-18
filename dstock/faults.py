"""Lớp GÂY LỖI MẠNG cho demo và test — interceptor gRPC phía client của mỗi kênh đi ra.

Chủ sở hữu: TV5.

Mỗi kênh nhân bản (nguồn -> đích) đi qua một FaultInterceptor gắn với `dst`.
Admin.SetFault(FaultRule) ghi luật vào FaultInjector của node nguồn; interceptor đọc luật
trước mỗi lời gọi. Code nhân bản KHÔNG biết gì về lớp này — đúng như mạng thật.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import grpc


@dataclass
class Rule:
    drop_rate: float = 0.0
    delay_ms: int = 0
    partition: bool = False

    def is_noop(self) -> bool:
        return self.drop_rate <= 0 and self.delay_ms <= 0 and not self.partition

    def describe(self) -> str:
        if self.is_noop():
            return ""
        parts = []
        if self.partition:
            parts.append("CẮT")
        if self.drop_rate > 0:
            parts.append(f"bỏ {self.drop_rate:.0%}")
        if self.delay_ms > 0:
            parts.append(f"trễ {self.delay_ms}ms")
        return ", ".join(parts)


class FaultInjector:
    """Bảng luật gây lỗi của một node, theo đích. Thread-safe."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rules: dict[str, Rule] = {}
        self.injected = 0          # số lần ĐÃ gây lỗi (bỏ/cắt/trễ) — test dùng để chắc lỗi đã xảy ra

    def count_injected(self) -> None:
        with self._lock:
            self.injected += 1

    def set_rule(self, dst: str, rule: Rule) -> None:
        with self._lock:
            if rule.is_noop():
                self._rules.pop(dst, None)
            else:
                self._rules[dst] = rule

    def rule_for(self, dst: str) -> Rule:
        with self._lock:
            return self._rules.get(dst) or self._rules.get("*") or Rule()

    def describe(self, dst: str) -> str:
        return self.rule_for(dst).describe()


class FaultInterceptor(grpc.UnaryUnaryClientInterceptor, grpc.UnaryStreamClientInterceptor):
    def __init__(self, injector: FaultInjector, dst: str):
        self.injector = injector
        self.dst = dst

    def _before_call(self) -> None:
        rule = self.injector.rule_for(self.dst)
        if rule.is_noop():
            return
        # TODO(TV5): áp dụng luật:
        #   - partition  -> ném lỗi UNAVAILABLE ngay (không gửi gì)
        #   - drop_rate  -> random() < drop_rate thì ném UNAVAILABLE
        #   - delay_ms   -> time.sleep(delay_ms / 1000) rồi gửi bình thường
        # Mỗi lần THỰC SỰ gây lỗi: gọi self.injector.count_injected().
        # Gợi ý ném lỗi: tạo class InjectedFault(grpc.RpcError) có method code() trả
        # grpc.StatusCode.UNAVAILABLE và details() trả "injected" — link.py bắt grpc.RpcError.
        # Bật tests/acceptance/test_tv5_faults.py để kiểm tra.

    def intercept_unary_unary(self, continuation, client_call_details, request):
        self._before_call()
        return continuation(client_call_details, request)

    def intercept_unary_stream(self, continuation, client_call_details, request):
        self._before_call()
        return continuation(client_call_details, request)
