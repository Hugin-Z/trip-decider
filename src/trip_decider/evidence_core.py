"""证据两轴内核：support 判定、freshness 计算、token 合取、next_action 构造。

本模块是 ``docs/contracts/evidence-axes.md`` 的唯一可执行实现。

设计约束（``PLAN.md`` v4 §12 的 P2 闸门）：

* **零 I/O**。不读文件、不读时钟、不发网络。``now`` 与策略由调用方注入。
* **不 import 任何产品模块**。只用标准库。依赖方向单向：产品可以依赖内核，
  内核不依赖产品。
* **纯函数**。除构造 frozen dataclass 外无副作用，同样输入恒得同样输出。

参照而非复用：``evidence_broker.py:359-443`` 的 ``_stale_projection`` 是现有
代码中唯一符合两轴分离的实现——它保留 ``EvidenceStatus.SOURCED``（support
不变），只改写 freshness 派生的展示字段。本模块把这条原则从一处特例提升为
全局规则，但不 import 它，也不搬运它的代码。

术语与章节号一律指向 ``docs/contracts/evidence-axes.md``。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

__all__ = [
    "ACTORS",
    "CONFIRMED_ABSENT_KIND",
    "DERIVATIONS_ESTIMATED",
    "DERIVATIONS_SOURCED",
    "EvidenceCoreError",
    "FRESHNESS_FRESH",
    "FRESHNESS_STALE",
    "FRESHNESS_UNDATED",
    "FRESHNESS_VALUES",
    "FactInput",
    "FreshnessVerdict",
    "FactVerdict",
    "FreshnessPolicy",
    "NEXT_ACTION_KINDS",
    "REASON_CODES",
    "REASON_CODES_BY_AXIS_VALUE",
    "SUPPORT_CONFLICTING",
    "SUPPORT_ESTIMATED",
    "SUPPORT_SOURCED",
    "SUPPORT_UNKNOWN",
    "SUPPORT_VALUES",
    "SourceRef",
    "SupportAggregate",
    "SupportVerdict",
    "TOKEN_CONFLICTING",
    "TOKEN_ESTIMATED",
    "TOKEN_ESTIMATED_STALE",
    "TOKEN_ESTIMATED_UNDATED",
    "TOKEN_SOURCED_STALE",
    "TOKEN_SOURCED_UNDATED",
    "TOKEN_UNKNOWN",
    "TOKEN_VERIFIED",
    "TOKEN_VALUES",
    "aggregate_freshness",
    "aggregate_support",
    "build_next_action",
    "SonarValue",
    "V1AccessError",
    "collection_metadata",
    "combine_token",
    "classify_support",
    "compute_freshness",
    "confirmed_absent",
    "derive_facts",
    "evaluate_fact",
    "fact_id",
    "is_confirmed_absent",
    "normalized_retrieved_at",
    "parse_timestamp",
    "recovery_safe",
    "resolve_blocking",
    "resolve_freshness",
    "split_fact_id",
    "token_freshness",
    "token_support",
    "validate_next_action",
]


class EvidenceCoreError(ValueError):
    """内核收到了不满足契约的输入。"""


# ---------------------------------------------------------------------------
# 取值域（§1、§4.1、§5.2）
# ---------------------------------------------------------------------------

SUPPORT_SOURCED = "sourced"
SUPPORT_ESTIMATED = "estimated"
SUPPORT_CONFLICTING = "conflicting"
SUPPORT_UNKNOWN = "unknown"
SUPPORT_VALUES = frozenset(
    {SUPPORT_SOURCED, SUPPORT_ESTIMATED, SUPPORT_CONFLICTING, SUPPORT_UNKNOWN}
)

# v1 的枚举名与 support 轴只差一个词。映射只许有一份——词表映射和 token
# 一样，实现数必须是 1（基线报告 M1「四套词表」）。枚举本身是否退役是另一
# 个问题，退役前它存在期间也只许这一份。
_LEGACY_SUPPORT_NAMES: Mapping[str, str] = MappingProxyType(
    {"missing": SUPPORT_UNKNOWN}
)


# 读取层投影的键。它们由 now 与内核算出，写回盘就等于把一次读取的结论冻成
# 数据——I5 禁止的正是这件事，I1 数的正是它的落盘痕迹。
_PROJECTION_KEYS = frozenset(
    {"token", "next_action", "display_status", "displayable", "planning_state"}
)


def recovery_safe(value: object) -> object:
    """剥掉读取层投影，只留事实、结构与引用（persistence-v2.md §1.1）。

    恢复数据的职责是让运行能接着走，不是让上一次的判定原样复活。判定由
    读取层按当时的 now 重算——这是 PlanVersion 的同一个哲学：盘上存引用，
    读时算结论。
    """

    if isinstance(value, Mapping):
        return {
            key: recovery_safe(item)
            for key, item in value.items()
            if key not in _PROJECTION_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [recovery_safe(item) for item in value]
    return value


def support_from_legacy_name(name: object) -> str:
    """旧状态名 → support 轴取值。认不出的原样返回，由校验去拒。

    只吃字符串：内核不认识产品的枚举类型，调用方传 ``status.value``。
    """

    if not isinstance(name, str):
        return SUPPORT_UNKNOWN
    return _LEGACY_SUPPORT_NAMES.get(name, name)

FRESHNESS_FRESH = "fresh"
FRESHNESS_STALE = "stale"
FRESHNESS_UNDATED = "undated"
FRESHNESS_VALUES = frozenset(
    {FRESHNESS_FRESH, FRESHNESS_STALE, FRESHNESS_UNDATED}
)

TOKEN_VERIFIED = "verified"
TOKEN_SOURCED_STALE = "sourced_stale"
TOKEN_SOURCED_UNDATED = "sourced_undated"
TOKEN_ESTIMATED = "estimated"
TOKEN_ESTIMATED_STALE = "estimated_stale"
TOKEN_ESTIMATED_UNDATED = "estimated_undated"
TOKEN_CONFLICTING = "conflicting"
TOKEN_UNKNOWN = "unknown"

# §4.1 的 8 token 表。这是全仓唯一一份 support x freshness -> token 映射
# （``invariants.md`` I6）。
_TOKEN_TABLE: Mapping[tuple[str, str], str] = MappingProxyType(
    {
        (SUPPORT_SOURCED, FRESHNESS_FRESH): TOKEN_VERIFIED,
        (SUPPORT_SOURCED, FRESHNESS_STALE): TOKEN_SOURCED_STALE,
        (SUPPORT_SOURCED, FRESHNESS_UNDATED): TOKEN_SOURCED_UNDATED,
        (SUPPORT_ESTIMATED, FRESHNESS_FRESH): TOKEN_ESTIMATED,
        (SUPPORT_ESTIMATED, FRESHNESS_STALE): TOKEN_ESTIMATED_STALE,
        (SUPPORT_ESTIMATED, FRESHNESS_UNDATED): TOKEN_ESTIMATED_UNDATED,
        (SUPPORT_CONFLICTING, FRESHNESS_FRESH): TOKEN_CONFLICTING,
        (SUPPORT_CONFLICTING, FRESHNESS_STALE): TOKEN_CONFLICTING,
        (SUPPORT_CONFLICTING, FRESHNESS_UNDATED): TOKEN_CONFLICTING,
        (SUPPORT_UNKNOWN, FRESHNESS_FRESH): TOKEN_UNKNOWN,
        (SUPPORT_UNKNOWN, FRESHNESS_STALE): TOKEN_UNKNOWN,
        (SUPPORT_UNKNOWN, FRESHNESS_UNDATED): TOKEN_UNKNOWN,
    }
)

TOKEN_VALUES = frozenset(_TOKEN_TABLE.values())

# §4.3 的分解。conflicting / unknown 吸收 freshness，因此 freshness 分量为
# None——它们的 token 不携带 freshness 信息，I2 也就不比较该分量。
_TOKEN_SUPPORT: Mapping[str, str] = MappingProxyType(
    {
        TOKEN_VERIFIED: SUPPORT_SOURCED,
        TOKEN_SOURCED_STALE: SUPPORT_SOURCED,
        TOKEN_SOURCED_UNDATED: SUPPORT_SOURCED,
        TOKEN_ESTIMATED: SUPPORT_ESTIMATED,
        TOKEN_ESTIMATED_STALE: SUPPORT_ESTIMATED,
        TOKEN_ESTIMATED_UNDATED: SUPPORT_ESTIMATED,
        TOKEN_CONFLICTING: SUPPORT_CONFLICTING,
        TOKEN_UNKNOWN: SUPPORT_UNKNOWN,
    }
)

_TOKEN_FRESHNESS: Mapping[str, str | None] = MappingProxyType(
    {
        TOKEN_VERIFIED: FRESHNESS_FRESH,
        TOKEN_SOURCED_STALE: FRESHNESS_STALE,
        TOKEN_SOURCED_UNDATED: FRESHNESS_UNDATED,
        TOKEN_ESTIMATED: FRESHNESS_FRESH,
        TOKEN_ESTIMATED_STALE: FRESHNESS_STALE,
        TOKEN_ESTIMATED_UNDATED: FRESHNESS_UNDATED,
        TOKEN_CONFLICTING: None,
        TOKEN_UNKNOWN: None,
    }
)

# §2.1 的 derivation 六值，按 §2.2 的序 3 / 序 4 分组。
DERIVATIONS_ESTIMATED = frozenset(
    {"api_estimate", "model_estimate", "rule_derived"}
)
DERIVATIONS_SOURCED = frozenset(
    {"direct_observation", "official_report", "user_supplied"}
)
_DERIVATIONS = DERIVATIONS_ESTIMATED | DERIVATIONS_SOURCED

NEXT_ACTION_KINDS = frozenset(
    {
        "auto_refetch",
        "user_confirm",
        "user_choice",
        "user_supply",
        "accept_as_is",
    }
)

ACTORS = frozenset({"system", "user", "either"})

# §5.2 扩充后的 15 值。P2 新增 4 个 unknown 类（reason-code-inventory.md §4），
# P3b 前置修正新增 refresh_failed（evidence-axes.md §3.4）。
REASON_CODES_BY_AXIS_VALUE: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        SUPPORT_UNKNOWN: frozenset(
            {
                "no_source_found",
                "collector_not_configured",
                "collector_timeout",
                "collector_error",
                "classification_failed",
                "cancelled_by_user",
                "input_precondition_unmet",
                "internal_contract_violation",
                "source_rejected_by_policy",
            }
        ),
        SUPPORT_CONFLICTING: frozenset({"sources_disagree"}),
        SUPPORT_ESTIMATED: frozenset(
            {"derived_by_rule", "derived_by_provider_estimate"}
        ),
        FRESHNESS_STALE: frozenset(
            {"beyond_tolerance_window", "refresh_failed"}
        ),
        FRESHNESS_UNDATED: frozenset({"retrieved_at_absent"}),
    }
)

REASON_CODES = frozenset(
    code for codes in REASON_CODES_BY_AXIS_VALUE.values() for code in codes
)

CONFIRMED_ABSENT_KIND = "confirmed_absent"

# 判定序号，作为 support 判定规则的可追溯载体（§7 未决问题 3）。
_RULE_UNKNOWN_NO_CONCLUSION = "s1-unknown-no-conclusion"
_RULE_CONFLICTING = "s2-conflicting-sources-disagree"
_RULE_ESTIMATED = "s3-estimated-derived"
_RULE_SOURCED_DIRECT = "s4-sourced-direct-readout"
_RULE_SOURCED_ABSENT = "s4-sourced-confirmed-absent"
_RULE_UNKNOWN_FALLBACK = "s5-unknown-classification-failed"


# ---------------------------------------------------------------------------
# 输入结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceRef:
    """一条外部来源引用（§2.1）。"""

    provider: str
    retrieved_at: str | None = None
    url: str | None = None
    scope: str | None = None

    def __post_init__(self) -> None:
        if not str(self.provider).strip():
            raise EvidenceCoreError("source provider is required")


@dataclass(frozen=True)
class FreshnessPolicy:
    """一个 data_type 的策略，由调用方从契约登记表注入（§3.1）。

    内核不读 ``docs/contracts/freshness-policy.md``——那是 I/O。调用方负责
    解析并注入。
    """

    data_type: str
    tolerance_seconds: int
    feasibility_critical: bool
    on_stale: str = "flag_for_confirmation"
    stale_allowed: bool = True

    def __post_init__(self) -> None:
        if not str(self.data_type).strip():
            raise EvidenceCoreError("policy data_type is required")
        if int(self.tolerance_seconds) < 0:
            raise EvidenceCoreError("tolerance_seconds must not be negative")
        if self.on_stale not in {
            "auto_refetch",
            "flag_for_confirmation",
            "block",
        }:
            raise EvidenceCoreError(f"unsupported on_stale: {self.on_stale}")


@dataclass(frozen=True)
class FactInput:
    """一个待定级的事实（§2.1 的四项判定输入 + freshness 的两项）。"""

    fact_id: str
    data_type: str
    value: Any = None
    derivation: str | None = None
    sources: tuple[SourceRef, ...] = ()
    conflict_details: tuple[str, ...] = ()
    conflict_source_refs: tuple[str, ...] = ()
    reason: str | None = None
    retrieved_at: str | None = None
    field_name: str | None = None
    derivation_detail: Mapping[str, Any] | None = None
    # §3.4：刷新失败是采集时刻的事实，可持久化，与 support 同性质。
    refresh_failed: bool = False
    refresh_failed_at: str | None = None

    def __post_init__(self) -> None:
        if not str(self.fact_id).strip():
            raise EvidenceCoreError("fact_id is required")
        if not str(self.data_type).strip():
            raise EvidenceCoreError("data_type is required")
        if self.derivation is not None and self.derivation not in _DERIVATIONS:
            raise EvidenceCoreError(
                f"unsupported derivation: {self.derivation}"
            )
        if self.reason is not None and self.reason not in REASON_CODES:
            raise EvidenceCoreError(f"unsupported reason: {self.reason}")


# ---------------------------------------------------------------------------
# 输出结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupportVerdict:
    """support 判定结果（§2.2）。"""

    support: str
    rule: str
    reason: str | None = None
    confirmed_absent: bool = False


@dataclass(frozen=True)
class SupportAggregate:
    """派生事实的聚合结果（§2.4 + §2.2.2）。

    ``support`` 是四态之一；``confirmed_absent`` 是正交的传播标志，不进入
    support 取值域。
    """

    support: str
    confirmed_absent: bool
    input_fact_ids: tuple[str, ...]
    absent_scopes: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class FactVerdict:
    """一个事实的完整读时判定（门面 ``evaluate_fact`` 的输出）。"""

    fact_id: str
    token: str
    support: str
    freshness: str
    rule: str
    confirmed_absent: bool = False
    next_action: Mapping[str, Any] | None = None
    reason: str | None = None
    # §5.2.1 序 3：estimated 可以参与判定但结论必须条件化。P3a 只产出该标志，
    # 消费它的是 P3b 的 29 个闸门改造。
    requires_conditional: bool = False


# ---------------------------------------------------------------------------
# confirmed_absent（§2.2.1）
# ---------------------------------------------------------------------------


def confirmed_absent(scope: Mapping[str, Any]) -> dict[str, Any]:
    """构造一个「来源确认不存在」的 value。

    ``scope`` 必须非空：否定必须有范围。「没有直达车」只在给定的起讫点与
    时间窗内成立，脱离范围的否定无意义。
    """

    if not isinstance(scope, Mapping) or not scope:
        raise EvidenceCoreError(
            "confirmed_absent requires a non-empty scope mapping"
        )
    return {"kind": CONFIRMED_ABSENT_KIND, "scope": dict(scope)}


def is_confirmed_absent(value: Any) -> bool:
    """机械区分「确认没有」与「有值」。这是下游唯一的判据。"""

    return (
        isinstance(value, Mapping)
        and value.get("kind") == CONFIRMED_ABSENT_KIND
        and isinstance(value.get("scope"), Mapping)
        and bool(value.get("scope"))
    )



# ---------------------------------------------------------------------------
# fact_id 生成（persistence-v2.md §5 的引用基石）
# ---------------------------------------------------------------------------


def fact_id(evidence_id: str, field: str) -> str:
    """由 ``(evidence_id, field)`` 生成稳定的 fact 标识。

    **全仓唯一的生成规则。** 写入侧与测试共用它——P4-c 的 PlanVersion 与候选卡
    靠 ``fact_id`` 指向事实，两侧各自拼一套会让引用在读取时对不上，而对不上
    只会表现为「引用解析失败」，看不出是规则不一致造成的。

    规则刻意保持可读且可逆：``<evidence_id>#<field>``。不做哈希——排查引用
    问题时能一眼看出它指向谁，比短标识值钱。
    """

    left = str(evidence_id).strip()
    right = str(field).strip()
    if not left:
        raise EvidenceCoreError("fact_id requires an evidence_id")
    if not right:
        raise EvidenceCoreError("fact_id requires a field path")
    if "#" in left:
        raise EvidenceCoreError("evidence_id must not contain '#'")
    return f"{left}#{right}"


def split_fact_id(value: str) -> tuple[str, str]:
    """``fact_id`` 的逆运算，返回 ``(evidence_id, field)``。"""

    text = str(value)
    if "#" not in text:
        raise EvidenceCoreError(f"not a fact_id: {value!r}")
    left, _, right = text.partition("#")
    return left, right



# ---------------------------------------------------------------------------
# v1 -> facts 推导（persistence-v2.md §1.3 的双读机制）
# ---------------------------------------------------------------------------
#
# v2 把 support 从 item 级改为字段级。切换分两步：先让读取端能从 v1 的裸
# mapping **推导**出 facts（本节），再把写入端改成直接落 facts。推导期内落盘
# 形状不变，因此行为零变更。

# 这些键是取证元数据或展示态，不是事实本身，不产出 fact。
# ``snapshot`` / ``freshness`` / ``refresh_failure`` 记录「怎么取到的」；
# ``*_status`` / ``display`` 是展示态（P4-b3 的删除对象）。
# 剪掉整棵子树的键：它们自上而下都是取证元数据。
# 采集元数据登记表（persistence-v2.md §1.4.1）。**一个符号，三处使用**：
# 剪枝（_is_non_fact_path）、保留（collection_metadata）、声呐（SonarValue）。
#
# 值为 None：整棵子树都是元数据。
# 值为一组叶子名：该键是**重载键**——它本身装着事实（``snapshot`` 下面是车次
# 本体），只有列出的叶子是元数据。
#
# 合并成一份是刻意的。分成两个符号时，「剪掉了但没保留」与「保留了但没放行」
# 在语法上都成立，而这两个错各犯过一次：collection_metadata 漏了重载键让元
# 数据凭空消失，SonarValue 漏了同一批键报出 8 条假阳性。
_NON_FACT_PATHS: Mapping[str, frozenset[str] | None] = MappingProxyType(
    {
        "freshness": None,
        "refresh_failure": None,
        "local_transit_refresh_failure": None,
        # 采集结果（AVAILABLE / PARTIAL / FAILED），与 refresh_failure 同族：
        # 是取证元数据，可以持久化，但不是关于世界的事实。按名字登记，
        # 不靠 _status 后缀——后缀是按拼写认的，这个字段正是被它误伤过。
        "local_transit_outcome": None,
        # 采集请求的签名：记录这次向服务商问了哪些点，与 outcome 同族。
        "local_transit_input_signature": None,
        # 采集器写在 value 顶层的 item 级 support（P4-b3 甲类改名后的形态）。
        "support": None,
        "source": None,
        "sources": None,
        "retrieved_at": None,
        "domain": None,
        "network_attempts": None,
        "conditions": None,
        "display": None,
        "availability_semantics": None,
        # 重载键：装着车次本体，只有这几片叶子是元数据。
        "snapshot": frozenset(
            {
                # P4-b3 把 status 改名为 acquisition 并脱轴取值。名单自身是
                # 改名同步范围的一部分——这一处漏了，acquisition 就不算元
                # 数据，被推导成事实后从落盘的 snapshot 里消失。
                "acquisition",
                # 旧名。双读期内历史数据仍带它，历史存量删除后可去掉。
                "status",
                "retrieved_at",
                "attempted_at",
                "availability_semantics",
                "source",
                "provider",
            }
        ),
    }
)

_NON_FACT_KEYS = frozenset(
    key for key, leaves in _NON_FACT_PATHS.items() if leaves is None
)
_NON_FACT_LEAVES_UNDER = MappingProxyType(
    {key: leaves for key, leaves in _NON_FACT_PATHS.items() if leaves is not None}
)

# _stale_projection 抹除不可知字段时写的字面量。见 persistence-v2.md §3.1。
_UNKNOWABLE_SENTINEL = "UNKNOWN"


def _is_non_fact_key(key: str) -> bool:
    return key in _NON_FACT_KEYS or key.endswith("_status")


def _is_non_fact_path(path: str) -> bool:
    """按整条点分路径判定，让子树里的元数据叶子单独出局。"""

    steps = [step for step in path.replace("]", "").split(".") if step]
    for index, step in enumerate(steps):
        bare = step.split("[")[0]
        if _is_non_fact_key(bare):
            return True
        allowed = _NON_FACT_LEAVES_UNDER.get(bare)
        if allowed is not None and index + 1 < len(steps):
            if steps[index + 1].split("[")[0] in allowed:
                return True
    return False


def _flatten_leaves(
    value: Any,
    prefix: str = "",
) -> list[tuple[str, Any]]:
    """把嵌套 mapping 压平成 ``(点分路径, 叶子值)``。

    列表按下标展开，因为 ``local_transit[0].duration_seconds`` 与
    ``local_transit[1].duration_seconds`` 是两个独立的事实，可以有不同的
    support。
    """

    if isinstance(value, Mapping):
        out: list[tuple[str, Any]] = []
        for key, child in value.items():
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            if _is_non_fact_path(path):
                continue
            out.extend(_flatten_leaves(child, path))
        return out
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        out = []
        for index, child in enumerate(value):
            out.extend(_flatten_leaves(child, f"{prefix}[{index}]"))
        return out
    return [(prefix, value)] if prefix else []


class V1AccessError(EvidenceCoreError):
    """有人把 v2 形状的 value 当 v1 裸 mapping 读了。"""


class SonarValue(dict):
    """v2 落盘 value 的迁移期外壳：v1 式访问大声失败。

    ``value.get("outbound")`` 在 v2 下静默返回 ``None``——不报错，只是悄悄什么
    也没做。静态普查数不出这类消费点，所以让它们自己报名。**迁移完成后拆除。**
    """

    __slots__ = ()

    _KNOWN = frozenset({"facts"}) | frozenset(_NON_FACT_PATHS)

    def _guard(self, key: object) -> None:
        name = str(key)
        if name in self._KNOWN:
            return
        raise V1AccessError(
            f"v1 式访问 v2 落盘形状：键 {name!r} 不在 v2 的 value 里。"
            f"业务字段要走 usable_fact_values(item_facts(...)) 重建。"
        )

    def get(self, key, default=None):  # type: ignore[override]
        self._guard(key)
        return super().get(key, default)

    def __getitem__(self, key):
        self._guard(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self._guard(key)
        return super().__contains__(key)


def collection_metadata(value: Any) -> dict[str, Any]:
    """从裸 value 里摘出该持久化的采集元数据。

    判据是 ``_NON_FACT_PATHS``——与剪枝、声呐同一份名单。不做深拷贝：内核只用
    标准库最小集，拷贝责任留给调用方。
    """

    if not isinstance(value, Mapping):
        return {}
    metadata: dict[str, Any] = {}
    for key, leaves in _NON_FACT_PATHS.items():
        if key not in value:
            continue
        if leaves is None:
            metadata[key] = value[key]
            continue
        nested = value[key]
        if not isinstance(nested, Mapping):
            continue
        kept = {
            str(name): item
            for name, item in nested.items()
            if str(name) in leaves
        }
        if kept:
            metadata[key] = kept
    return metadata


def normalized_retrieved_at(value: Any, fallback: Any = None) -> str | None:
    """按 §1.3.1 从 v1 的三种放法里解析采集时刻。

    优先级 ``snapshot.retrieved_at`` > ``freshness.retrieved_at`` >
    ``value.retrieved_at`` > 调用方给的 fallback（通常是 source 级）。v2 之后
    这三种放法全部废除，本函数只在推导期存在。
    """

    mapping = value if isinstance(value, Mapping) else {}
    for path in (("snapshot", "retrieved_at"), ("freshness", "retrieved_at")):
        nested = mapping.get(path[0])
        if isinstance(nested, Mapping) and isinstance(nested.get(path[1]), str):
            return str(nested[path[1]])
    if isinstance(mapping.get("retrieved_at"), str):
        return str(mapping["retrieved_at"])
    return str(fallback) if isinstance(fallback, str) else None


def derive_facts(
    value: Any,
    evidence_id: str,
    domain: str,
    *,
    item_support: str = SUPPORT_SOURCED,
    data_type: str = "",
    retrieved_at: Any = None,
    reason: str | None = None,
    conflict_details: Sequence[str] = (),
) -> tuple[Mapping[str, Any], ...]:
    """从 v1 的裸 mapping 推导字段级 facts。

    ``item_support`` 是该证据的 item 级 support，作为每个 fact 的默认值；
    个别字段按下列规则下调：

    * 叶子为 ``None`` → ``unknown``（该字段没有结论）
    * 叶子为字面量 ``"UNKNOWN"`` → ``unknown``，值丢弃（写入端用它表示
      「本字段不可知」，见 ``_UNKNOWABLE_SENTINEL``）

    **只下调不上调**：item 级为 ``unknown`` 时每个 fact 都是 ``unknown``，
    不会因为某个叶子有值就升回去。
    """

    if item_support not in SUPPORT_VALUES:
        raise EvidenceCoreError(f"unsupported support value: {item_support!r}")
    stamp = normalized_retrieved_at(value, retrieved_at)

    def build(field: str, leaf: Any, support: str) -> dict[str, Any]:
        fact: dict[str, Any] = {
            "fact_id": fact_id(evidence_id, field),
            "field": field,
            "value": leaf,
            "support": support,
            "data_type": data_type,
            "retrieved_at": stamp,
        }
        if support == SUPPORT_UNKNOWN:
            fact["reason"] = reason or "no_source_found"
        if support == SUPPORT_CONFLICTING and conflict_details:
            fact["conflict_details"] = list(conflict_details)
        return fact

    # 确认的否定是一条事实，不拆字段——「没有直达车」不是「车次为空」加
    # 「票价为空」，它是一个整体结论（evidence-axes.md §2.2.1）。
    if is_confirmed_absent(value):
        return (build(domain, dict(value), item_support),)

    if value is None:
        return (build(domain, None, SUPPORT_UNKNOWN),)

    facts: list[Mapping[str, Any]] = []
    for field, leaf in _flatten_leaves(value):
        support = item_support
        if leaf is None or leaf == _UNKNOWABLE_SENTINEL:
            support = SUPPORT_UNKNOWN
            leaf = None
        facts.append(build(field, leaf, support))
    return tuple(facts)


# ---------------------------------------------------------------------------
# 1. support 判定（§2.2）
# ---------------------------------------------------------------------------


def _has_conclusion(fact: FactInput) -> bool:
    """序 1 的反面：``value`` 是否承载结论。

    有值与确认没有都算结论；只有「不知道」不算。字段名给定时，还要求该字段
    在 mapping 型 value 中出现。
    """

    value = fact.value
    if value is None:
        return False
    if is_confirmed_absent(value):
        return True
    if fact.field_name is not None and isinstance(value, Mapping):
        if fact.field_name not in value:
            return False
        return value[fact.field_name] is not None
    return True


def _sources_are_complete(fact: FactInput) -> bool:
    return bool(fact.sources) and all(
        source.retrieved_at is not None and str(source.retrieved_at).strip()
        for source in fact.sources
    )


def classify_support(fact: FactInput) -> SupportVerdict:
    """按 §2.2 的五序判定定级。第一个命中的胜出，顺序是规范的一部分。"""

    # 序 1：采集未产出结论。
    if not _has_conclusion(fact):
        return SupportVerdict(
            support=SUPPORT_UNKNOWN,
            rule=_RULE_UNKNOWN_NO_CONCLUSION,
            reason=fact.reason or "no_source_found",
        )

    # 序 2：来源分歧。conflicting 优先于 estimated——分歧本身是需要用户
    # 裁决的事实，不因其中一方是推算值而降级。
    if fact.conflict_details:
        if len(fact.conflict_source_refs) < 2:
            raise EvidenceCoreError(
                "conflicting support requires at least two "
                "conflict_source_refs"
            )
        return SupportVerdict(
            support=SUPPORT_CONFLICTING,
            rule=_RULE_CONFLICTING,
            reason="sources_disagree",
        )

    # 序 3：推算产生。不区分推算主体（本地规则 / 供应商 API / 模型）。
    if fact.derivation in DERIVATIONS_ESTIMATED:
        return SupportVerdict(
            support=SUPPORT_ESTIMATED,
            rule=_RULE_ESTIMATED,
            reason=(
                "derived_by_rule"
                if fact.derivation == "rule_derived"
                else "derived_by_provider_estimate"
            ),
        )

    # 序 4：直接读出，或来源明确给出的负结果。
    if fact.derivation in DERIVATIONS_SOURCED and _sources_are_complete(fact):
        absent = is_confirmed_absent(fact.value)
        return SupportVerdict(
            support=SUPPORT_SOURCED,
            rule=_RULE_SOURCED_ABSENT if absent else _RULE_SOURCED_DIRECT,
            confirmed_absent=absent,
        )

    # 序 5：兜底。采到了但归不了类。
    return SupportVerdict(
        support=SUPPORT_UNKNOWN,
        rule=_RULE_UNKNOWN_FALLBACK,
        reason="classification_failed",
    )


# ---------------------------------------------------------------------------
# 2. freshness 计算（§3.2）
# ---------------------------------------------------------------------------


def parse_timestamp(text: Any) -> datetime | None:
    """解析带时区的 ISO-8601 时间戳。不可解析或无时区一律返回 None。

    要求时区：不带时区的时间戳无法与注入的 ``now`` 比较，按 §3.2 归 undated
    而不是猜一个时区。
    """

    if not isinstance(text, str) or not text.strip():
        return None
    candidate = text.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


@dataclass(frozen=True)
class FreshnessVerdict:
    """freshness 判定结果，附带「是否被刷新失败封顶」。

    分开记录封顶来源，是因为两种 stale 对用户的行动指引不同：超窗是「太久
    没查、重查即可」，刷新失败是「刚查没查成、数据源可能异常」。
    """

    value: str
    capped_by_refresh_failure: bool = False


def resolve_freshness(
    retrieved_at: Any,
    *,
    now: datetime,
    tolerance_seconds: int,
    refresh_failed: bool = False,
    refresh_failed_at: Any = None,
) -> FreshnessVerdict:
    """按 §3.2 计算 freshness，并施加 §3.4 的刷新失败封顶。

    封顶规则：存在**晚于** ``retrieved_at`` 的刷新失败记录时，freshness 最高
    只能是 ``stale``。缺失 ``attempted_at`` 时仍然封顶——一条挂在该值上的刷新
    失败记录必然发生在该值采集之后（采集不到的东西谈不上刷新失败），顺序是
    结构性保证的。反过来，若记录带的时间戳**不晚于** ``retrieved_at``，说明它
    属于产出这份数据的那次采集本身而不是后续刷新，不封顶。
    """

    if now.tzinfo is None:
        raise EvidenceCoreError("now must be timezone-aware")
    if int(tolerance_seconds) < 0:
        raise EvidenceCoreError("tolerance_seconds must not be negative")

    parsed = parse_timestamp(retrieved_at)
    if parsed is None:
        return FreshnessVerdict(FRESHNESS_UNDATED)

    age = (now - parsed).total_seconds()
    if age < 0:
        # 未来时间戳是数据错误，不得被当作最新。
        return FreshnessVerdict(FRESHNESS_UNDATED)
    base = FRESHNESS_FRESH if age <= int(tolerance_seconds) else FRESHNESS_STALE

    has_failure = bool(refresh_failed) or refresh_failed_at is not None
    if not has_failure:
        return FreshnessVerdict(base)
    failed_at = parse_timestamp(refresh_failed_at)
    if failed_at is not None and failed_at <= parsed:
        return FreshnessVerdict(base)
    if base == FRESHNESS_FRESH:
        return FreshnessVerdict(FRESHNESS_STALE, capped_by_refresh_failure=True)
    return FreshnessVerdict(base, capped_by_refresh_failure=True)


def compute_freshness(
    retrieved_at: Any,
    *,
    now: datetime,
    tolerance_seconds: int,
    refresh_failed: bool = False,
    refresh_failed_at: Any = None,
) -> str:
    """``resolve_freshness`` 的取值分量。"""

    return resolve_freshness(
        retrieved_at,
        now=now,
        tolerance_seconds=tolerance_seconds,
        refresh_failed=refresh_failed,
        refresh_failed_at=refresh_failed_at,
    ).value


# ---------------------------------------------------------------------------
# 3. token 合取与分解（§4.1、§4.3）
# ---------------------------------------------------------------------------


def combine_token(support: str, freshness: str) -> str:
    """§4.1 的合取。freshness 只能下调，不能上调。"""

    if support not in SUPPORT_VALUES:
        raise EvidenceCoreError(f"unsupported support value: {support!r}")
    if freshness not in FRESHNESS_VALUES:
        raise EvidenceCoreError(f"unsupported freshness value: {freshness!r}")
    return _TOKEN_TABLE[(support, freshness)]


def token_support(token: str) -> str:
    """§4.3 的分解：token 的 support 分量。"""

    if token not in _TOKEN_SUPPORT:
        raise EvidenceCoreError(f"unsupported token: {token!r}")
    return _TOKEN_SUPPORT[token]


def token_freshness(token: str) -> str | None:
    """§4.3 的分解：token 的 freshness 分量。

    ``conflicting`` / ``unknown`` 吸收 freshness，返回 None——它们的 token
    不携带 freshness 信息，I2 也就不比较该分量。
    """

    if token not in _TOKEN_FRESHNESS:
        raise EvidenceCoreError(f"unsupported token: {token!r}")
    return _TOKEN_FRESHNESS[token]


# ---------------------------------------------------------------------------
# 4. next_action 构造与校验（§5）
# ---------------------------------------------------------------------------

_KIND_BY_REASON: Mapping[str, str] = MappingProxyType(
    {
        # unknown 类
        "no_source_found": "user_supply",
        "collector_not_configured": "user_supply",
        "collector_timeout": "auto_refetch",
        "collector_error": "auto_refetch",
        "classification_failed": "user_confirm",
        "cancelled_by_user": "user_confirm",
        "input_precondition_unmet": "user_supply",
        "internal_contract_violation": "accept_as_is",
        "source_rejected_by_policy": "auto_refetch",
        # conflicting 类
        "sources_disagree": "user_choice",
        # estimated 类
        "derived_by_rule": "accept_as_is",
        "derived_by_provider_estimate": "accept_as_is",
        # freshness 类
        "beyond_tolerance_window": "auto_refetch",
        "refresh_failed": "auto_refetch",
        "retrieved_at_absent": "user_confirm",
    }
)

_ACTOR_BY_REASON: Mapping[str, str] = MappingProxyType(
    {
        "no_source_found": "user",
        "collector_not_configured": "system",
        "collector_timeout": "system",
        "collector_error": "system",
        "classification_failed": "system",
        "cancelled_by_user": "user",
        "input_precondition_unmet": "user",
        "internal_contract_violation": "system",
        "source_rejected_by_policy": "system",
        "sources_disagree": "user",
        "derived_by_rule": "either",
        "derived_by_provider_estimate": "either",
        "beyond_tolerance_window": "system",
        "refresh_failed": "system",
        "retrieved_at_absent": "user",
    }
)

_DETAIL_BY_REASON: Mapping[str, str] = MappingProxyType(
    {
        "no_source_found": "没有找到支持该事实的来源，请补充信息。",
        "collector_not_configured": "该来源尚未接入，暂时查不到。",
        "collector_timeout": "查询超时，正在重试。",
        "collector_error": "查询出错，正在重试。",
        "classification_failed": "该事实的证据形态无法识别，请人工确认。",
        "cancelled_by_user": "查询已按你的要求中止，是否继续？",
        "input_precondition_unmet": "缺少必要输入，请先补全后再查询。",
        "internal_contract_violation": "系统内部参数不合法，该事实暂不可用。",
        "source_rejected_by_policy": "来源返回的内容未通过校验，正在换用其他来源。",
        "sources_disagree": "不同来源对该事实给出了不一致的结果，请选择。",
        "derived_by_rule": "该数值由规则推算得出，实际情况可能不同。",
        "derived_by_provider_estimate": "该数值为服务方推算值，实际情况可能不同。",
        "beyond_tolerance_window": "该数据已超出时效窗，正在重新查询。",
        "refresh_failed": (
            "刚刚尝试刷新该数据但没有成功，数据源可能暂时异常；"
            "当前显示的是上一次采集的结果，稍后会再试。"
        ),
        "retrieved_at_absent": "该数据没有采集时间，无法判断是否仍然有效。",
    }
)


def _reason_for(
    support: str,
    freshness: str,
    verdict_reason: str | None,
    *,
    capped_by_refresh_failure: bool = False,
) -> str:
    """§5.2 末段：support 与 freshness 同时非理想时，取 freshness 侧的值。"""

    stale_reason = (
        "refresh_failed" if capped_by_refresh_failure else "beyond_tolerance_window"
    )
    if support == SUPPORT_SOURCED:
        if freshness == FRESHNESS_STALE:
            return stale_reason
        if freshness == FRESHNESS_UNDATED:
            return "retrieved_at_absent"
        raise EvidenceCoreError("verified facts carry no reason_code")
    if support == SUPPORT_ESTIMATED and freshness != FRESHNESS_FRESH:
        return (
            stale_reason
            if freshness == FRESHNESS_STALE
            else "retrieved_at_absent"
        )
    if verdict_reason is not None:
        return verdict_reason
    if support == SUPPORT_CONFLICTING:
        return "sources_disagree"
    if support == SUPPORT_ESTIMATED:
        return "derived_by_provider_estimate"
    return "classification_failed"


def resolve_blocking(
    support: str,
    freshness: str,
    *,
    feasibility_critical: bool,
    on_stale: str,
) -> tuple[bool, bool]:
    """§5.2.1：返回 ``(blocking, requires_conditional)``。

    ``blocking`` 意为「不能支撑判定」；``requires_conditional`` 意为「能支撑
    但结论必须携带条件」。两者不是强弱之分，是种类之分。

    序 3 与序 4 的不对称是有意的：``sourced`` 超窗意味着曾经精确、现在过期，
    重查能修复，因此在重查前停下来是对的；``estimated`` 从来不精确，没有任何
    重查能让它变精确，conditional 是它的永久正确形态。
    """

    if support not in SUPPORT_VALUES:
        raise EvidenceCoreError(f"unsupported support value: {support!r}")
    if freshness not in FRESHNESS_VALUES:
        raise EvidenceCoreError(f"unsupported freshness value: {freshness!r}")

    # 序 1：非关键字段恒不阻断。
    if not feasibility_critical:
        return False, False
    # 序 2：没有结论或结论打架，判定无从进行。
    if support in {SUPPORT_UNKNOWN, SUPPORT_CONFLICTING}:
        return True, False
    # 序 3：推算值可以参与判定，但必须条件化（裁决 5）。
    if support == SUPPORT_ESTIMATED:
        return False, True
    # 序 4：曾经精确、现在超窗，由该 data_type 的超窗档位决定。
    if freshness != FRESHNESS_FRESH:
        if on_stale in {"auto_refetch", "block"}:
            return True, False
        return False, True
    # 序 5：sourced 且 fresh —— token 为 verified，本来就没有 next_action。
    return False, False


def build_next_action(
    *,
    token: str,
    field_ref: str,
    data_type: str,
    support: str,
    freshness: str,
    feasibility_critical: bool,
    on_stale: str = "flag_for_confirmation",
    capped_by_refresh_failure: bool = False,
    reason: str | None = None,
    detail: str | None = None,
    retry_after_at: str | None = None,
    options: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """构造 next_action，或在 token == verified 时返回 None（§5.1 双向约束）。"""

    if token == TOKEN_VERIFIED:
        # 有把握的事实不产生噪声。这半边约束是 UI 渲染分支的依据。
        return None

    reason_code = _reason_for(
        support,
        freshness,
        reason,
        capped_by_refresh_failure=capped_by_refresh_failure,
    )
    kind = _KIND_BY_REASON[reason_code]
    blocking, _conditional = resolve_blocking(
        support,
        freshness,
        feasibility_critical=feasibility_critical,
        on_stale=on_stale,
    )
    action: dict[str, Any] = {
        "kind": kind,
        "field_ref": field_ref,
        "data_type": data_type,
        "reason_code": reason_code,
        "actor": _ACTOR_BY_REASON[reason_code],
        "blocking": blocking,
        "detail": detail or _DETAIL_BY_REASON[reason_code],
    }
    if kind == "auto_refetch" and retry_after_at is not None:
        action["retry_after_at"] = retry_after_at
    if kind == "user_choice":
        action["options"] = [dict(option) for option in (options or ())]
    return action


def validate_next_action(
    action: Mapping[str, Any] | None,
    *,
    token: str,
) -> None:
    """校验 §5.1 的双向约束与 §5.2 每个枚举字段的取值域。不合规即抛错。"""

    if token not in TOKEN_VALUES:
        raise EvidenceCoreError(f"unsupported token: {token!r}")

    if token == TOKEN_VERIFIED:
        if action is not None:
            raise EvidenceCoreError(
                "verified facts must not carry a next_action"
            )
        return

    if action is None:
        raise EvidenceCoreError(
            f"token {token!r} requires a next_action"
        )

    for required in (
        "kind",
        "field_ref",
        "data_type",
        "reason_code",
        "actor",
        "blocking",
        "detail",
    ):
        if required not in action:
            raise EvidenceCoreError(f"next_action is missing {required}")

    if action["kind"] not in NEXT_ACTION_KINDS:
        raise EvidenceCoreError(f"unsupported kind: {action['kind']!r}")
    if action["reason_code"] not in REASON_CODES:
        raise EvidenceCoreError(
            f"unsupported reason_code: {action['reason_code']!r}"
        )
    if action["actor"] not in ACTORS:
        raise EvidenceCoreError(f"unsupported actor: {action['actor']!r}")
    if not isinstance(action["blocking"], bool):
        raise EvidenceCoreError("blocking must be a bool")
    for text_field in ("field_ref", "data_type", "detail"):
        if not isinstance(action[text_field], str) or not action[
            text_field
        ].strip():
            raise EvidenceCoreError(f"{text_field} must be a non-empty string")

    if action["kind"] == "user_choice":
        options = action.get("options")
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
            raise EvidenceCoreError("user_choice requires an options list")
        if not options:
            raise EvidenceCoreError("user_choice requires at least one option")
        for option in options:
            if not isinstance(option, Mapping):
                raise EvidenceCoreError("each option must be a mapping")
            if not str(option.get("option_id", "")).strip():
                raise EvidenceCoreError("each option requires option_id")
            if not str(option.get("label", "")).strip():
                raise EvidenceCoreError("each option requires label")
    elif "options" in action:
        raise EvidenceCoreError("options is only valid for user_choice")

    if action["kind"] != "auto_refetch" and "retry_after_at" in action:
        raise EvidenceCoreError(
            "retry_after_at is only valid for auto_refetch"
        )
    if "retry_after_at" in action and parse_timestamp(
        action["retry_after_at"]
    ) is None:
        raise EvidenceCoreError(
            "retry_after_at must be a timezone-aware ISO-8601 timestamp"
        )


# ---------------------------------------------------------------------------
# 5. 聚合（§2.4、§2.2.2）
# ---------------------------------------------------------------------------


def aggregate_support(
    inputs: Sequence[SupportVerdict | str],
    *,
    derivation_occurred: bool,
    input_fact_ids: Sequence[str] = (),
    absent_scopes: Sequence[Mapping[str, Any]] = (),
) -> SupportAggregate:
    """§2.4 的四分支聚合，加 §2.2.2 的 confirmed_absent 吸收传播。

    ``derivation_occurred`` 为真表示派生事实的值不是某个输入的原样透传。
    两个 sourced 相加即属此列——按契约这判 estimated，偏严是有意的
    （见 evidence-axes.md §2.4 的 roundtrip_duration_seconds 说明）。
    """

    if not inputs:
        raise EvidenceCoreError("aggregation requires at least one input")

    supports: list[str] = []
    absent = False
    scopes: list[Mapping[str, Any]] = [
        MappingProxyType(dict(scope)) for scope in absent_scopes
    ]
    for item in inputs:
        if isinstance(item, SupportVerdict):
            supports.append(item.support)
            absent = absent or item.confirmed_absent
        elif item in SUPPORT_VALUES:
            supports.append(item)
        else:
            raise EvidenceCoreError(f"unsupported aggregation input: {item!r}")

    if SUPPORT_CONFLICTING in supports:
        support = SUPPORT_CONFLICTING
    elif SUPPORT_UNKNOWN in supports:
        support = SUPPORT_UNKNOWN
    elif derivation_occurred or SUPPORT_ESTIMATED in supports:
        support = SUPPORT_ESTIMATED
    else:
        support = SUPPORT_SOURCED

    return SupportAggregate(
        support=support,
        confirmed_absent=absent,
        input_fact_ids=tuple(input_fact_ids),
        absent_scopes=tuple(scopes),
    )


def aggregate_freshness(freshnesses: Sequence[str]) -> str:
    """派生事实的 freshness：最差的赢。undated < stale < fresh。"""

    if not freshnesses:
        raise EvidenceCoreError("aggregation requires at least one freshness")
    for value in freshnesses:
        if value not in FRESHNESS_VALUES:
            raise EvidenceCoreError(f"unsupported freshness value: {value!r}")
    if FRESHNESS_UNDATED in freshnesses:
        return FRESHNESS_UNDATED
    if FRESHNESS_STALE in freshnesses:
        return FRESHNESS_STALE
    return FRESHNESS_FRESH


# ---------------------------------------------------------------------------
# 门面
# ---------------------------------------------------------------------------


def evaluate_fact(
    fact: FactInput,
    policy: FreshnessPolicy,
    *,
    now: datetime,
    retry_after_at: str | None = None,
    options: Sequence[Mapping[str, Any]] | None = None,
) -> FactVerdict:
    """一个事实的完整读时判定：support -> freshness -> token -> next_action。

    这是读取层唯一需要调用的入口。它保证 I2（token 与两轴精确对应）与
    I3a（next_action 双向约束）在单个事实上成立。
    """

    if policy.data_type != fact.data_type:
        raise EvidenceCoreError(
            f"policy data_type {policy.data_type!r} does not match fact "
            f"data_type {fact.data_type!r}"
        )

    verdict = classify_support(fact)
    freshness_verdict = resolve_freshness(
        fact.retrieved_at if fact.retrieved_at is not None else _first_retrieved_at(fact),
        now=now,
        tolerance_seconds=policy.tolerance_seconds,
        refresh_failed=fact.refresh_failed,
        refresh_failed_at=fact.refresh_failed_at,
    )
    freshness = freshness_verdict.value
    token = combine_token(verdict.support, freshness)
    _blocking, requires_conditional = resolve_blocking(
        verdict.support,
        freshness,
        feasibility_critical=policy.feasibility_critical,
        on_stale=policy.on_stale,
    )
    action = build_next_action(
        token=token,
        field_ref=fact.field_name or fact.fact_id,
        data_type=fact.data_type,
        support=verdict.support,
        freshness=freshness,
        feasibility_critical=policy.feasibility_critical,
        on_stale=policy.on_stale,
        capped_by_refresh_failure=freshness_verdict.capped_by_refresh_failure,
        reason=verdict.reason,
        retry_after_at=retry_after_at,
        options=options if options is not None else _conflict_options(fact),
    )
    validate_next_action(action, token=token)
    return FactVerdict(
        fact_id=fact.fact_id,
        token=token,
        support=verdict.support,
        freshness=freshness,
        rule=verdict.rule,
        confirmed_absent=verdict.confirmed_absent,
        next_action=MappingProxyType(action) if action is not None else None,
        reason=verdict.reason,
        requires_conditional=requires_conditional,
    )


def _first_retrieved_at(fact: FactInput) -> str | None:
    for source in fact.sources:
        if source.retrieved_at:
            return source.retrieved_at
    return None


def _conflict_options(fact: FactInput) -> tuple[dict[str, Any], ...] | None:
    """把来源分歧转成可选项：每个分歧来源是一个候选。

    ``user_choice`` 要求 options 非空（§5.2）。对 conflicting 事实而言，互斥
    候选就是各个分歧来源本身——让用户裁决「信哪个来源」是这里唯一诚实的
    问法，系统没有资格替他选。``conflict_details`` 按位置提供人类可读标签。
    """

    if not fact.conflict_source_refs:
        return None
    details = fact.conflict_details
    return tuple(
        {
            "option_id": source_ref,
            "label": (
                details[index] if index < len(details) else str(source_ref)
            ),
            "source_ref": source_ref,
        }
        for index, source_ref in enumerate(fact.conflict_source_refs)
    )
