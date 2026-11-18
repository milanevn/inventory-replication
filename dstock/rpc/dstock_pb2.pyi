from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Empty(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Line(_message.Message):
    __slots__ = ("sku", "qty")
    SKU_FIELD_NUMBER: _ClassVar[int]
    QTY_FIELD_NUMBER: _ClassVar[int]
    sku: str
    qty: int
    def __init__(self, sku: _Optional[str] = ..., qty: _Optional[int] = ...) -> None: ...

class Voucher(_message.Message):
    __slots__ = ("req_id", "kind", "code", "lines", "note", "product_name", "unit")
    REQ_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    LINES_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_NAME_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    req_id: str
    kind: str
    code: str
    lines: _containers.RepeatedCompositeFieldContainer[Line]
    note: str
    product_name: str
    unit: str
    def __init__(self, req_id: _Optional[str] = ..., kind: _Optional[str] = ..., code: _Optional[str] = ..., lines: _Optional[_Iterable[_Union[Line, _Mapping]]] = ..., note: _Optional[str] = ..., product_name: _Optional[str] = ..., unit: _Optional[str] = ...) -> None: ...

class Entry(_message.Message):
    __slots__ = ("lsn", "req_id", "kind", "code", "lines", "note", "ts", "prev_hash", "hash", "product_name", "unit", "epoch")
    LSN_FIELD_NUMBER: _ClassVar[int]
    REQ_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    LINES_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    TS_FIELD_NUMBER: _ClassVar[int]
    PREV_HASH_FIELD_NUMBER: _ClassVar[int]
    HASH_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_NAME_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    lsn: int
    req_id: str
    kind: str
    code: str
    lines: _containers.RepeatedCompositeFieldContainer[Line]
    note: str
    ts: float
    prev_hash: str
    hash: str
    product_name: str
    unit: str
    epoch: int
    def __init__(self, lsn: _Optional[int] = ..., req_id: _Optional[str] = ..., kind: _Optional[str] = ..., code: _Optional[str] = ..., lines: _Optional[_Iterable[_Union[Line, _Mapping]]] = ..., note: _Optional[str] = ..., ts: _Optional[float] = ..., prev_hash: _Optional[str] = ..., hash: _Optional[str] = ..., product_name: _Optional[str] = ..., unit: _Optional[str] = ..., epoch: _Optional[int] = ...) -> None: ...

class WriteReply(_message.Message):
    __slots__ = ("ok", "lsn", "error", "replicated_sync", "duplicate", "primary_hint")
    OK_FIELD_NUMBER: _ClassVar[int]
    LSN_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    REPLICATED_SYNC_FIELD_NUMBER: _ClassVar[int]
    DUPLICATE_FIELD_NUMBER: _ClassVar[int]
    PRIMARY_HINT_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    lsn: int
    error: str
    replicated_sync: bool
    duplicate: bool
    primary_hint: str
    def __init__(self, ok: _Optional[bool] = ..., lsn: _Optional[int] = ..., error: _Optional[str] = ..., replicated_sync: _Optional[bool] = ..., duplicate: _Optional[bool] = ..., primary_hint: _Optional[str] = ...) -> None: ...

class StockQuery(_message.Message):
    __slots__ = ("skus",)
    SKUS_FIELD_NUMBER: _ClassVar[int]
    skus: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, skus: _Optional[_Iterable[str]] = ...) -> None: ...

class StockReply(_message.Message):
    __slots__ = ("node_id", "lsn", "stock", "last_apply_ts", "health")
    class StockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    LSN_FIELD_NUMBER: _ClassVar[int]
    STOCK_FIELD_NUMBER: _ClassVar[int]
    LAST_APPLY_TS_FIELD_NUMBER: _ClassVar[int]
    HEALTH_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    lsn: int
    stock: _containers.ScalarMap[str, int]
    last_apply_ts: float
    health: str
    def __init__(self, node_id: _Optional[str] = ..., lsn: _Optional[int] = ..., stock: _Optional[_Mapping[str, int]] = ..., last_apply_ts: _Optional[float] = ..., health: _Optional[str] = ...) -> None: ...

class AppendRequest(_message.Message):
    __slots__ = ("from_node", "entries", "epoch")
    FROM_NODE_FIELD_NUMBER: _ClassVar[int]
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    from_node: str
    entries: _containers.RepeatedCompositeFieldContainer[Entry]
    epoch: int
    def __init__(self, from_node: _Optional[str] = ..., entries: _Optional[_Iterable[_Union[Entry, _Mapping]]] = ..., epoch: _Optional[int] = ...) -> None: ...

class AppendReply(_message.Message):
    __slots__ = ("ok", "last_lsn", "error", "last_hash", "epoch")
    OK_FIELD_NUMBER: _ClassVar[int]
    LAST_LSN_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    LAST_HASH_FIELD_NUMBER: _ClassVar[int]
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    last_lsn: int
    error: str
    last_hash: str
    epoch: int
    def __init__(self, ok: _Optional[bool] = ..., last_lsn: _Optional[int] = ..., error: _Optional[str] = ..., last_hash: _Optional[str] = ..., epoch: _Optional[int] = ...) -> None: ...

class FetchRequest(_message.Message):
    __slots__ = ("requester", "after_lsn")
    REQUESTER_FIELD_NUMBER: _ClassVar[int]
    AFTER_LSN_FIELD_NUMBER: _ClassVar[int]
    requester: str
    after_lsn: int
    def __init__(self, requester: _Optional[str] = ..., after_lsn: _Optional[int] = ...) -> None: ...

class PromoteRequest(_message.Message):
    __slots__ = ("exclude",)
    EXCLUDE_FIELD_NUMBER: _ClassVar[int]
    exclude: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, exclude: _Optional[_Iterable[str]] = ...) -> None: ...

class NodeStatus(_message.Message):
    __slots__ = ("node_id", "role", "health", "last_lsn", "last_hash", "state_digest", "stock", "links", "last_apply_ts", "detail", "epoch", "primary_id", "has_quorum", "members", "products")
    class StockEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    class ProductsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    HEALTH_FIELD_NUMBER: _ClassVar[int]
    LAST_LSN_FIELD_NUMBER: _ClassVar[int]
    LAST_HASH_FIELD_NUMBER: _ClassVar[int]
    STATE_DIGEST_FIELD_NUMBER: _ClassVar[int]
    STOCK_FIELD_NUMBER: _ClassVar[int]
    LINKS_FIELD_NUMBER: _ClassVar[int]
    LAST_APPLY_TS_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    EPOCH_FIELD_NUMBER: _ClassVar[int]
    PRIMARY_ID_FIELD_NUMBER: _ClassVar[int]
    HAS_QUORUM_FIELD_NUMBER: _ClassVar[int]
    MEMBERS_FIELD_NUMBER: _ClassVar[int]
    PRODUCTS_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    role: str
    health: str
    last_lsn: int
    last_hash: str
    state_digest: str
    stock: _containers.ScalarMap[str, int]
    links: _containers.RepeatedCompositeFieldContainer[LinkInfo]
    last_apply_ts: float
    detail: str
    epoch: int
    primary_id: str
    has_quorum: bool
    members: _containers.RepeatedScalarFieldContainer[str]
    products: _containers.ScalarMap[str, str]
    def __init__(self, node_id: _Optional[str] = ..., role: _Optional[str] = ..., health: _Optional[str] = ..., last_lsn: _Optional[int] = ..., last_hash: _Optional[str] = ..., state_digest: _Optional[str] = ..., stock: _Optional[_Mapping[str, int]] = ..., links: _Optional[_Iterable[_Union[LinkInfo, _Mapping]]] = ..., last_apply_ts: _Optional[float] = ..., detail: _Optional[str] = ..., epoch: _Optional[int] = ..., primary_id: _Optional[str] = ..., has_quorum: _Optional[bool] = ..., members: _Optional[_Iterable[str]] = ..., products: _Optional[_Mapping[str, str]] = ...) -> None: ...

class LinkInfo(_message.Message):
    __slots__ = ("from_node", "to_node", "mode", "param", "acked_lsn", "pending", "state", "last_flush_ts", "fault", "detail")
    FROM_NODE_FIELD_NUMBER: _ClassVar[int]
    TO_NODE_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    PARAM_FIELD_NUMBER: _ClassVar[int]
    ACKED_LSN_FIELD_NUMBER: _ClassVar[int]
    PENDING_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    LAST_FLUSH_TS_FIELD_NUMBER: _ClassVar[int]
    FAULT_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    from_node: str
    to_node: str
    mode: str
    param: float
    acked_lsn: int
    pending: int
    state: str
    last_flush_ts: float
    fault: str
    detail: str
    def __init__(self, from_node: _Optional[str] = ..., to_node: _Optional[str] = ..., mode: _Optional[str] = ..., param: _Optional[float] = ..., acked_lsn: _Optional[int] = ..., pending: _Optional[int] = ..., state: _Optional[str] = ..., last_flush_ts: _Optional[float] = ..., fault: _Optional[str] = ..., detail: _Optional[str] = ...) -> None: ...

class LinkParam(_message.Message):
    __slots__ = ("to_node", "param")
    TO_NODE_FIELD_NUMBER: _ClassVar[int]
    PARAM_FIELD_NUMBER: _ClassVar[int]
    to_node: str
    param: float
    def __init__(self, to_node: _Optional[str] = ..., param: _Optional[float] = ...) -> None: ...

class FaultRule(_message.Message):
    __slots__ = ("to_node", "drop_rate", "delay_ms", "partition")
    TO_NODE_FIELD_NUMBER: _ClassVar[int]
    DROP_RATE_FIELD_NUMBER: _ClassVar[int]
    DELAY_MS_FIELD_NUMBER: _ClassVar[int]
    PARTITION_FIELD_NUMBER: _ClassVar[int]
    to_node: str
    drop_rate: float
    delay_ms: int
    partition: bool
    def __init__(self, to_node: _Optional[str] = ..., drop_rate: _Optional[float] = ..., delay_ms: _Optional[int] = ..., partition: _Optional[bool] = ...) -> None: ...
