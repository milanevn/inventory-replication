"""Nghiệp vụ nhập – xuất – tồn. Thuần Python, không biết gì về mạng hay CSDL.

- `Inventory` là trạng thái (danh mục sản phẩm + bảng tồn) — được TÍNH RA từ nhật ký thay đổi,
  không phải nguồn sự thật.
- `validate()` chỉ chạy ở bản chính trước khi cấp LSN.
- `apply()` chạy ở MỌI node, phải tất định: cùng dãy entry => cùng trạng thái.

Ba loại thao tác:
    SANPHAM : khai báo / sửa sản phẩm (code = mã hàng, product_name, unit)
    NHAP    : phiếu nhập (code = số phiếu, lines). Mã hàng chưa khai báo thì tự tạo (tên = mã).
    XUAT    : phiếu xuất — tồn phải đủ.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .errors import InsufficientStock, InvalidVoucher

SANPHAM = "SANPHAM"
NHAP = "NHAP"
XUAT = "XUAT"
KINDS = (SANPHAM, NHAP, XUAT)
MAX_QTY = 1_000_000_000          # mỗi dòng hàng
MAX_STOCK = 1_000_000_000_000    # tồn của một mã — giữ xa giới hạn int64 của protobuf


@dataclass(frozen=True)
class Line:
    sku: str
    qty: int


@dataclass
class Voucher:
    req_id: str
    kind: str
    code: str
    lines: list[Line]
    note: str = ""
    product_name: str = ""
    unit: str = ""


def normalize(v: Voucher) -> Voucher:
    """Chuẩn hóa trước khi kiểm tra: bỏ khoảng trắng, mã hàng viết HOA (" sp01" == "SP01").

    req_id bắt buộc: thiếu req_id thì không chống ghi trùng được (2 phiếu khác nhau cùng
    req_id "" sẽ bị coi là gửi lại) => từ chối.
    """
    req_id = (v.req_id or "").strip()
    if not req_id:
        raise InvalidVoucher("thiếu req_id")
    kind = (v.kind or "").strip().upper()
    code = (v.code or "").strip()
    return Voucher(
        req_id=req_id,
        kind=kind,
        code=code.upper() if kind == SANPHAM else code,
        lines=[Line(l.sku.strip().upper(), l.qty) for l in v.lines],
        note=v.note or "",
        product_name=(v.product_name or "").strip(),
        unit=(v.unit or "").strip(),
    )


def merge_lines(lines) -> dict[str, int]:
    """Gộp các dòng trùng mã hàng: [SP01:2, SP01:3] -> {SP01: 5}."""
    out: dict[str, int] = {}
    for ln in lines:
        out[ln.sku] = out.get(ln.sku, 0) + ln.qty
    return out


@dataclass
class Inventory:
    stock: dict[str, int] = field(default_factory=dict)
    products: dict[str, tuple[str, str]] = field(default_factory=dict)   # mã -> (tên, đơn vị)

    def get(self, sku: str) -> int:
        return self.stock.get(sku, 0)

    def validate(self, v: Voucher) -> None:
        if v.kind not in KINDS:
            raise InvalidVoucher(f"loại {v.kind!r} không hợp lệ (SANPHAM|NHAP|XUAT)")
        if not v.code.strip():
            raise InvalidVoucher("thiếu mã hàng" if v.kind == SANPHAM else "thiếu số phiếu")
        if v.kind == SANPHAM:
            if not v.product_name:
                raise InvalidVoucher("thiếu tên sản phẩm")
            if v.lines:
                raise InvalidVoucher("khai báo sản phẩm không có dòng hàng")
            return
        if not v.lines:
            raise InvalidVoucher("phiếu không có dòng hàng")
        for ln in v.lines:
            if not ln.sku.strip():
                raise InvalidVoucher("dòng hàng thiếu mã")
            if ln.qty <= 0:
                raise InvalidVoucher(f"{ln.sku}: số lượng phải > 0")
            if ln.qty > MAX_QTY:
                raise InvalidVoucher(f"{ln.sku}: số lượng tối đa {MAX_QTY:,}")
        if v.kind == NHAP:
            for sku, qty in merge_lines(v.lines).items():
                if self.get(sku) + qty > MAX_STOCK:
                    raise InvalidVoucher(f"{sku}: tồn vượt giới hạn {MAX_STOCK:,}")
        if v.kind == XUAT:
            for sku, qty in merge_lines(v.lines).items():
                if self.get(sku) < qty:
                    raise InsufficientStock(f"{sku}: tồn {self.get(sku)} < xuất {qty}")

    def apply(self, kind: str, lines, code: str = "", product_name: str = "", unit: str = "") -> None:
        if kind == SANPHAM:
            self.products[code] = (product_name, unit)
            self.stock.setdefault(code, 0)
            return
        sign = 1 if kind == NHAP else -1
        for sku, qty in merge_lines(lines).items():
            if kind == NHAP and sku not in self.products:
                self.products[sku] = (sku, "")             # tự tạo khi nhập mã mới
            self.stock[sku] = self.get(sku) + sign * qty

    def digest(self) -> str:
        """Dấu vân tay của trạng thái — 2 node cùng digest <=> cùng dữ liệu."""
        body = [sorted(self.stock.items()), sorted((k, list(v)) for k, v in self.products.items())]
        canon = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()

    def snapshot(self) -> dict[str, int]:
        return dict(self.stock)
