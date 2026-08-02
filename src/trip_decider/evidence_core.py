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
    "combine_token",
    "classify_support",
    "compute_freshness",
    "confirmed_absent",
    "evaluate_fact",
    "is_confirmed_absent",
    "parse_timestamp",
    "resolve_blocking",
    "resolve_freshness",
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
