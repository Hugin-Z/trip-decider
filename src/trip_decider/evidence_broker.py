"""Cross-run evidence cache with exact provenance and freshness boundaries.

The broker is the only production component allowed to reuse evidence across
runs.  A new run must attempt its live collector first; callers may invoke
``stale_after_failure`` only after that attempt returned unusable evidence.
Catalog and fixture material is rejected at publication time.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Callable
from uuid import uuid4

from trip_decider.evidence_projection import item_retrieved_at
from trip_decider.travel_agent import (
    default_runtime_root,
    EvidenceItem,
    EvidenceStatus,
    TravelAgentError,
    TravelIntent,
)


@dataclass(frozen=True)
class FreshnessPolicy:
    data_type: str
    stale_ttl_seconds: int
    stale_allowed: bool


FRESHNESS_POLICIES: dict[str, FreshnessPolicy] = {
    "seat_availability": FreshnessPolicy(
        "seat_availability", 0, False
    ),
    "hotel_price": FreshnessPolicy("hotel_price", 0, False),
    "railway_schedule_fare": FreshnessPolicy(
        "railway_schedule_fare", 6 * 60 * 60, True
    ),
    "route_duration": FreshnessPolicy(
        "route_duration", 6 * 60 * 60, True
    ),
    "poi_coordinate": FreshnessPolicy(
        "poi_coordinate", 30 * 24 * 60 * 60, True
    ),
    "opening_hours": FreshnessPolicy(
        "opening_hours", 24 * 60 * 60, True
    ),
    "ticket_price": FreshnessPolicy(
        "ticket_price", 24 * 60 * 60, True
    ),
    "destination_profile": FreshnessPolicy(
        "destination_profile", 24 * 60 * 60, True
    ),
}


@dataclass(frozen=True)
class EvidenceQuery:
    """Exact cache lookup contract, excluding the resulting evidence."""

    provider: str
    origin: str
    destination: str
    query_parameters: Mapping[str, object]
    earliest_departure_at: str
    latest_return_at: str
    data_type: str

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise TravelAgentError("evidence query provider is required")
        if self.data_type not in FRESHNESS_POLICIES:
            raise TravelAgentError("evidence query data_type is unsupported")
        _canonical_json(self.query_parameters)

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "origin": self.origin,
            "destination": self.destination,
            "query_parameters": deepcopy(dict(self.query_parameters)),
            "earliest_departure_at": self.earliest_departure_at,
            "latest_return_at": self.latest_return_at,
            "data_type": self.data_type,
        }

    @property
    def identity(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True)
class _CacheRecord:
    record_id: str
    run_id: str
    query: EvidenceQuery
    collected_at: str
    stale_ttl_seconds: int
    evidence: EvidenceItem

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "run_id": self.run_id,
            "query": self.query.to_dict(),
            "collected_at": self.collected_at,
            "stale_ttl_seconds": self.stale_ttl_seconds,
            "evidence": self.evidence.to_dict(),
        }


Clock = Callable[[], datetime]


class EvidenceBroker:
    """Persist and retrieve exact cross-run evidence after live failure."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._root = Path(root).resolve() if root is not None else None
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._records: dict[str, _CacheRecord] = {}
        if self._root is not None:
            self._root.mkdir(parents=True, exist_ok=True)
            self._load()

    def publish(
        self,
        *,
        run_id: str,
        query: EvidenceQuery,
        evidence: EvidenceItem,
        collected_at: str,
    ) -> None:
        """Publish sourced live evidence; non-stale data is never cached."""

        policy = FRESHNESS_POLICIES[query.data_type]
        if not policy.stale_allowed:
            return
        if not evidence.status.is_usable:
            return
        collected = _parse_datetime(collected_at, "collected_at")
        if collected > self._clock() + timedelta(minutes=5):
            raise TravelAgentError("evidence collection time is in the future")
        _validate_sources(query, evidence)
        record = _CacheRecord(
            record_id=str(uuid4()),
            run_id=_required_text(run_id, "run_id"),
            query=query,
            collected_at=collected.isoformat(timespec="seconds"),
            stale_ttl_seconds=policy.stale_ttl_seconds,
            evidence=deepcopy(evidence),
        )
        with self._lock:
            current = self._records.get(query.identity)
            if current is None or _parse_datetime(
                current.collected_at,
                "stored collected_at",
            ) <= collected:
                self._records[query.identity] = record
                self._persist()

    def stale_after_failure(
        self,
        *,
        run_id: str,
        query: EvidenceQuery,
        live_failure: EvidenceItem,
    ) -> EvidenceItem | None:
        """Return STALE evidence only after a live attempt failed."""

        if _is_usable_live(query, live_failure):
            raise TravelAgentError(
                "stale lookup requires an unusable live result"
            )
        policy = FRESHNESS_POLICIES[query.data_type]
        if not policy.stale_allowed:
            return None
        with self._lock:
            record = self._records.get(query.identity)
            if record is None or record.run_id == run_id:
                return None
            if record.query.to_dict() != query.to_dict():
                raise TravelAgentError("evidence cache identity collision")
            collected = _parse_datetime(
                record.collected_at,
                "stored collected_at",
            )
            age = (self._clock() - collected).total_seconds()
            if age < 0 or age > record.stale_ttl_seconds:
                return None
            return _stale_projection(record, live_failure)

    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    def _persist(self) -> None:
        if self._root is None:
            return
        payload = {
            "schema_version": "1",
            "records": [
                record.to_dict()
                for _identity, record in sorted(self._records.items())
            ],
        }
        _atomic_json(self._root / "records.json", payload)

    def _load(self) -> None:
        assert self._root is not None
        path = self._root / "records.json"
        if not path.exists():
            return
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise TravelAgentError("evidence broker cache is unreadable") from error
        if (
            not isinstance(document, Mapping)
            or document.get("schema_version") != "1"
            or not isinstance(document.get("records"), list)
        ):
            raise TravelAgentError("evidence broker cache has invalid shape")
        for value in document["records"]:
            record = _record_from_mapping(value)
            self._records[record.query.identity] = record


def evidence_collected_at(evidence: EvidenceItem) -> str | None:
    """采集时刻，按 persistence-v2.md §1.3.1 的归一顺序取。

    这曾是同一段查找的第三份手写副本（另两份在 guided_discovery 与
    trip_read_model）。归一规则只许有一处实现。
    """

    return item_retrieved_at(evidence.to_dict())


def evidence_query(
    *,
    provider: str,
    origin: str | None,
    destination: str | None,
    query_parameters: Mapping[str, object],
    earliest_departure_at: str | None,
    latest_return_at: str | None,
    data_type: str,
) -> EvidenceQuery:
    return EvidenceQuery(
        provider=provider.strip(),
        origin=(origin or "").strip(),
        destination=(destination or "").strip(),
        query_parameters=deepcopy(dict(query_parameters)),
        earliest_departure_at=earliest_departure_at or "",
        latest_return_at=latest_return_at or "",
        data_type=data_type,
    )


def query_for_intent_domain(
    intent: TravelIntent,
    domain: str,
    *,
    route_inputs: tuple[str, list[str]] | None = None,
) -> EvidenceQuery:
    """Build the exact production query identity for one evidence domain."""

    parameters: dict[str, object] = {
        "travelers": intent.travelers,
        "total_budget_cny": intent.total_budget_cny,
        "transport_preferences": list(intent.transport_preferences),
    }
    provider = "中国铁路12306"
    data_type = "railway_schedule_fare"
    if domain == "web":
        provider = "高德地图 Web 服务"
        data_type = "destination_profile"
        parameters.update(
            {
                "themes": list(intent.themes),
                "accommodation_budget_total_cny": (
                    intent.accommodation_budget_total_cny
                ),
                "accommodation_budget_per_night_cny": (
                    intent.accommodation_budget_per_night_cny
                ),
                "rooms": intent.rooms,
            }
        )
    elif domain == "map":
        provider = "高德地图 Web 服务"
        data_type = "route_duration" if route_inputs is not None else "poi_coordinate"
        parameters = {
            "transport_preferences": list(intent.transport_preferences),
            "route_inputs": (
                [route_inputs[0], *route_inputs[1]]
                if route_inputs is not None
                else []
            ),
        }
    elif domain != "railway":
        raise TravelAgentError("evidence domain is unsupported")
    return evidence_query(
        provider=provider,
        origin=intent.origin,
        destination=intent.destination_anchor,
        query_parameters=parameters,
        earliest_departure_at=intent.earliest_departure_at,
        latest_return_at=intent.latest_return_at,
        data_type=data_type,
    )


def _is_usable_live(
    query: EvidenceQuery,
    evidence: EvidenceItem,
) -> bool:
    if not evidence.status.is_usable:
        return False
    value = evidence.value
    if not isinstance(value, Mapping):
        return True
    if query.data_type == "route_duration":
        routes = value.get("local_transit")
        return (
            value.get("local_transit_outcome")
            in {"AVAILABLE", "PARTIAL"}
            and isinstance(routes, list)
            and bool(routes)
        )
    return True


def _stale_projection(
    record: _CacheRecord,
    live_failure: EvidenceItem,
) -> EvidenceItem:
    value = deepcopy(record.evidence.value)
    if not isinstance(value, Mapping):
        raise TravelAgentError("cached evidence value must be an object")
    normalized = deepcopy(dict(value))
    # 只留采集时刻与 data_type。旧代码还写 status="STALE" 与 expires_at——
    # 那是把新鲜度判定连同它的有效期一起冻进盘里，而两者都是读取时刻的函数：
    # 读取层拿 retrieved_at + 策略表就能算出来，算出来的才会随 now 变。
    normalized["retrieved_at"] = record.collected_at
    normalized["data_type"] = record.query.data_type
    normalized["refresh_failure"] = {
        "missing_reason": live_failure.missing_reason,
    }
    if record.query.data_type == "railway_schedule_fare":
        snapshot = normalized.get("snapshot")
        attempted_at = None
        if isinstance(live_failure.value, Mapping):
            attempted_at = live_failure.value.get("attempted_at")
        normalized["snapshot"] = {
            **(dict(snapshot) if isinstance(snapshot, Mapping) else {}),
            "acquisition": "cache_fallback",
            "retrieved_at": record.collected_at,
            "attempted_at": attempted_at,
        }
        for direction in ("outbound", "return"):
            train = normalized.get(direction)
            if isinstance(train, Mapping):
                stale_train = deepcopy(dict(train))
                for key in tuple(stale_train):
                    if "availability" in str(key).lower():
                        stale_train[key] = "UNKNOWN"
                stale_train["second_class_availability"] = "UNKNOWN"
                normalized[direction] = stale_train
    elif record.query.data_type == "route_duration":
        routes = normalized.get("local_transit")
        if isinstance(routes, list):
            stale_routes: list[object] = []
            for route in routes:
                if not isinstance(route, Mapping):
                    stale_routes.append(deepcopy(route))
                    continue
                stale_route = deepcopy(dict(route))
                stale_route["retrieved_at"] = record.collected_at
                if "fare" in stale_route:
                    stale_route["fare"] = {
                        "status": "unknown",
                        "amount_cny": None,
                    }
                stale_routes.append(stale_route)
            normalized["local_transit"] = stale_routes
    elif record.query.data_type == "destination_profile":
        normalized["hotel_price_status"] = "UNKNOWN"
        hotels = normalized.get("hotel_candidates")
        if isinstance(hotels, list):
            sanitized_hotels: list[object] = []
            for hotel in hotels:
                if not isinstance(hotel, Mapping):
                    sanitized_hotels.append(deepcopy(hotel))
                    continue
                sanitized = deepcopy(dict(hotel))
                for key in tuple(sanitized):
                    if "price" in str(key).lower():
                        sanitized[key] = None
                sanitized["price_status"] = "UNKNOWN"
                sanitized_hotels.append(sanitized)
            normalized["hotel_candidates"] = sanitized_hotels
    return EvidenceItem(
        evidence_id=record.evidence.evidence_id,
        domain=record.evidence.domain,
        # support 保留缓存记录的原值，不得提升。缓存是原样重放，不是重新采集
        # ——一个 estimated 值经过一次降级就变成 sourced，会直接违反 I2。
        # 裁决 8.1 的硬性前提（p3b-gate-inventory.md）。
        status=record.evidence.status,
        value=normalized,
        sources=record.evidence.sources,
    )


def _validate_sources(
    query: EvidenceQuery,
    evidence: EvidenceItem,
) -> None:
    if not evidence.sources:
        raise TravelAgentError("cacheable evidence requires sources")
    providers = {
        str(source.get("provider", "")).strip()
        for source in evidence.sources
        if str(source.get("provider", "")).strip()
    }
    if providers != {query.provider}:
        raise TravelAgentError(
            "evidence provider does not match the cache query"
        )
    serialized = _canonical_json(
        {
            "sources": [dict(source) for source in evidence.sources],
            "value": evidence.value,
        }
    )
    lowered = serialized.lower()
    if any(token in lowered for token in ("fixture", "golden", "catalog")):
        raise TravelAgentError(
            "fixture or catalog evidence cannot enter the production broker"
        )
    if not all(
        isinstance(source.get("retrieved_at"), str)
        and str(source["retrieved_at"])
        for source in evidence.sources
    ):
        raise TravelAgentError(
            "cacheable evidence sources require retrieved_at"
        )


def _record_from_mapping(value: object) -> _CacheRecord:
    if not isinstance(value, Mapping):
        raise TravelAgentError("evidence broker record must be an object")
    query_value = value.get("query")
    evidence_value = value.get("evidence")
    if not isinstance(query_value, Mapping) or not isinstance(
        evidence_value,
        Mapping,
    ):
        raise TravelAgentError("evidence broker record is incomplete")
    parameters = query_value.get("query_parameters")
    if not isinstance(parameters, Mapping):
        raise TravelAgentError("evidence broker query parameters are invalid")
    query = EvidenceQuery(
        provider=_required_text(query_value.get("provider"), "provider"),
        origin=_required_string(query_value.get("origin"), "origin"),
        destination=_required_string(
            query_value.get("destination"),
            "destination",
        ),
        query_parameters=deepcopy(dict(parameters)),
        earliest_departure_at=_required_string(
            query_value.get("earliest_departure_at"),
            "earliest_departure_at",
        ),
        latest_return_at=_required_string(
            query_value.get("latest_return_at"),
            "latest_return_at",
        ),
        data_type=_required_text(query_value.get("data_type"), "data_type"),
    )
    ttl = value.get("stale_ttl_seconds")
    if not isinstance(ttl, int) or isinstance(ttl, bool) or ttl < 0:
        raise TravelAgentError("evidence broker TTL is invalid")
    if ttl != FRESHNESS_POLICIES[query.data_type].stale_ttl_seconds:
        raise TravelAgentError("evidence broker TTL no longer matches policy")
    evidence = EvidenceItem.from_mapping(evidence_value)
    _validate_sources(query, evidence)
    collected_at = _required_text(
        value.get("collected_at"),
        "collected_at",
    )
    _parse_datetime(collected_at, "collected_at")
    return _CacheRecord(
        record_id=_required_text(value.get("record_id"), "record_id"),
        run_id=_required_text(value.get("run_id"), "run_id"),
        query=query,
        collected_at=collected_at,
        stale_ttl_seconds=ttl,
        evidence=evidence,
    )


def _parse_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise TravelAgentError(f"{field} must be ISO datetime") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TravelAgentError(f"{field} must be non-empty text")
    return value.strip()


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TravelAgentError(f"{field} must be text")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise TravelAgentError(
            "evidence query must be canonical JSON data"
        ) from None


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


_DEFAULT_BROKER: EvidenceBroker | None = None


def default_cache_root() -> Path:
    """证据缓存根目录，与 runtime 根同源（travel_agent.default_runtime_root）。"""

    return default_runtime_root().parent / "evidence-cache"


def default_evidence_broker() -> EvidenceBroker:
    """进程级默认 broker，首次调用时才建目录读盘（invariants.md I11）。"""

    global _DEFAULT_BROKER
    if _DEFAULT_BROKER is None:
        _DEFAULT_BROKER = EvidenceBroker(default_cache_root())
    return _DEFAULT_BROKER


def reset_default_evidence_broker() -> None:
    """丢弃已构造的默认 broker。仅供测试隔离使用。"""

    global _DEFAULT_BROKER
    _DEFAULT_BROKER = None


__all__ = [
    "default_cache_root",
    "default_evidence_broker",
    "reset_default_evidence_broker",
    "EvidenceBroker",
    "EvidenceQuery",
    "FRESHNESS_POLICIES",
    "FreshnessPolicy",
    "evidence_collected_at",
    "evidence_query",
    "query_for_intent_domain",
]
