"""Generic, in-memory China Railway schedule and fare evidence."""

from __future__ import annotations

import http.cookiejar
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation


_RAIL_ORIGIN = "https://kyfw.12306.cn"
_STATION_JS_PATH = "/otn/resources/js/framework/station_name.js"
_PRICE_PATH = "/otn/leftTicket/queryTicketPrice"
_TIMEOUT_SECONDS = 15
_TRANSPORT_RETRIES = 1
_RETRY_WAIT_SECONDS = 1
_MAX_RESPONSE_BYTES = 4_000_000
# 采集语义词，不带轴词表影子（§1.4.1 在取值域上的延伸）。
_RAIL_ACQUISITIONS = {"live_fetch", "cache_fallback", "not_acquired"}


def rail_snapshot_metadata(
    acquisition: str,
    *,
    retrieved_at: str | None = None,
    attempted_at: str | None = None,
) -> dict[str, object]:
    """采集元数据：这次取到的是实时数据还是回退数据。

    `acquisition` 记录采集过程发生了什么，**不是新鲜度判断**。名与值都不带
    轴词表的影子（persistence-v2.md §1.4.1）——旧的 `status: LIVE/STALE` 两
    头都撞脸 freshness 轴，读代码的人会把它读成"现在新不新鲜"，而那是读取
    时刻的函数，任何落盘的答案都是错的。

    预渲染的 `display` 字符串一并删除：把展示逻辑烘进盘，且实测无人消费。
    """

    if acquisition not in _RAIL_ACQUISITIONS:
        raise ValueError("invalid rail snapshot acquisition")
    if acquisition in {"live_fetch", "cache_fallback"} and not retrieved_at:
        raise ValueError(f"{acquisition} rail snapshot requires retrieved_at")
    if acquisition == "not_acquired" and retrieved_at is not None:
        raise ValueError("not_acquired rail snapshot cannot claim retrieved_at")
    return {
        "acquisition": acquisition,
        "retrieved_at": retrieved_at,
        "attempted_at": attempted_at,
        "availability_semantics": (
            "current_at_retrieval_only"
            if acquisition == "live_fetch"
            else "not_current_availability"
            if acquisition == "cache_fallback"
            else "availability_unknown"
        ),
    }


@dataclass(frozen=True)
class _RailFailure(Exception):
    stage: str
    http_status: int | None = None
    python_exception_type: str = "RuntimeError"
    response_bytes_received: bool = False


@dataclass(frozen=True)
class _Train:
    train_no: str
    train_code: str
    origin_station: str
    destination_station: str
    origin_code: str
    destination_code: str
    origin_station_no: str
    destination_station_no: str
    seat_types: str
    departure_at: datetime
    arrival_at: datetime
    duration_seconds: int
    second_class_availability: str


class _RailClient:
    def __init__(self) -> None:
        cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar)
        )
        self.network_attempts = 0
        self._left_ticket_path: str | None = None

    def initialize_web_session(self) -> None:
        body = self._get("/otn/leftTicket/init")
        if not body:
            raise _RailFailure(
                stage="rail_session_initialize",
                python_exception_type="EmptyResponseError",
            )
        try:
            text = body.decode("utf-8")
            match = re.search(
                r"CLeftTicketUrl\s*=\s*'(leftTicket/query[A-Za-z0-9_]*)'",
                text,
            )
            if match is None:
                raise ValueError("left-ticket query path was not declared")
            self._left_ticket_path = "/otn/" + match.group(1)
        except (UnicodeError, ValueError) as error:
            raise _RailFailure(
                stage="rail_session_parse",
                python_exception_type=type(error).__name__,
                response_bytes_received=True,
            ) from None

    def _get(
        self,
        path: str,
        parameters: dict[str, str] | None = None,
    ) -> bytes:
        query = (
            "?" + urllib.parse.urlencode(parameters)
            if parameters
            else ""
        )
        headers = {
            "Accept": (
                "text/html,application/xhtml+xml,*/*;q=0.8"
                if path == "/otn/leftTicket/init"
                else (
                    "text/javascript,*/*;q=0.8"
                    if path == _STATION_JS_PATH
                    else "application/json,text/javascript,*/*;q=0.8"
                )
            ),
            "Referer": _RAIL_ORIGIN + "/otn/leftTicket/init",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
        }
        if path not in {
            "/otn/leftTicket/init",
            _STATION_JS_PATH,
        }:
            headers["X-Requested-With"] = "XMLHttpRequest"
        request = urllib.request.Request(
            _RAIL_ORIGIN + path + query,
            method="GET",
            headers=headers,
        )
        for retry_index in range(_TRANSPORT_RETRIES + 1):
            self.network_attempts += 1
            try:
                with self._opener.open(
                    request,
                    timeout=_TIMEOUT_SECONDS,
                ) as response:
                    body = response.read(_MAX_RESPONSE_BYTES + 1)
                    status = int(response.status)
            except urllib.error.HTTPError as error:
                try:
                    body = error.read(_MAX_RESPONSE_BYTES + 1)
                except Exception:
                    body = b""
                finally:
                    error.close()
                raise _RailFailure(
                    stage="rail_http",
                    http_status=int(error.code),
                    python_exception_type=type(error).__name__,
                    response_bytes_received=bool(body),
                ) from None
            except (
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                OSError,
            ) as error:
                if retry_index < _TRANSPORT_RETRIES:
                    time.sleep(_RETRY_WAIT_SECONDS)
                    continue
                raise _RailFailure(
                    stage="rail_transport",
                    python_exception_type=type(error).__name__,
                ) from None
            if not 200 <= status < 300:
                raise _RailFailure(
                    stage="rail_http",
                    http_status=status,
                    python_exception_type="HTTPStatusError",
                    response_bytes_received=bool(body),
                )
            if len(body) > _MAX_RESPONSE_BYTES:
                raise _RailFailure(
                    stage="rail_response_window",
                    http_status=status,
                    python_exception_type="ResponseTooLargeError",
                    response_bytes_received=True,
                )
            return bytes(body)
        raise AssertionError("unreachable rail transport state")

    def station_codes(self) -> tuple[dict[str, str], dict[str, str]]:
        body = self._get(_STATION_JS_PATH)
        try:
            text = body.decode("utf-8")
            match = re.search(r"station_names\s*=\s*'([^']*)'", text)
            if match is None:
                raise ValueError("station table was not found")
            name_to_code: dict[str, str] = {}
            code_to_name: dict[str, str] = {}
            for row in match.group(1).split("@"):
                if not row:
                    continue
                fields = row.split("|")
                if len(fields) < 3 or not fields[1] or not fields[2]:
                    raise ValueError("malformed station row")
                name_to_code[fields[1]] = fields[2]
                code_to_name[fields[2]] = fields[1]
        except (UnicodeError, ValueError) as error:
            raise _RailFailure(
                stage="rail_station_parse",
                python_exception_type=type(error).__name__,
                response_bytes_received=True,
            ) from None
        return name_to_code, code_to_name

    def query_direct(
        self,
        *,
        travel_date: date,
        origin_code: str,
        destination_code: str,
        station_names: dict[str, str],
    ) -> list[_Train]:
        if self._left_ticket_path is None:
            raise _RailFailure(
                stage="rail_session_initialize",
                python_exception_type="MissingQueryPathError",
            )
        body = self._get(
            self._left_ticket_path,
            {
                "leftTicketDTO.train_date": travel_date.isoformat(),
                "leftTicketDTO.from_station": origin_code,
                "leftTicketDTO.to_station": destination_code,
                "purpose_codes": "ADULT",
            },
        )
        try:
            document = json.loads(body.decode("utf-8"))
            data = document["data"]
            rows = data["result"]
            if document.get("status") is not True or not isinstance(
                rows,
                list,
            ):
                raise ValueError("rail result status is not successful")
            trains: list[_Train] = []
            for row in rows:
                if not isinstance(row, str):
                    raise TypeError("train row must be text")
                fields = row.split("|")
                if len(fields) <= 35:
                    raise ValueError("train row is incomplete")
                if (
                    fields[11] != "Y"
                    or not fields[3].startswith(("G", "D", "C"))
                    or fields[30] in {"", "无", "*"}
                ):
                    continue
                departure_at = datetime.combine(
                    travel_date,
                    datetime.strptime(fields[8], "%H:%M").time(),
                )
                arrival_at = datetime.combine(
                    travel_date,
                    datetime.strptime(fields[9], "%H:%M").time(),
                )
                if arrival_at < departure_at:
                    arrival_at += timedelta(days=1)
                duration_parts = fields[10].split(":")
                if len(duration_parts) != 2:
                    raise ValueError("invalid train duration")
                duration_seconds = (
                    int(duration_parts[0]) * 3600
                    + int(duration_parts[1]) * 60
                )
                trains.append(
                    _Train(
                        train_no=fields[2],
                        train_code=fields[3],
                        origin_station=station_names[fields[6]],
                        destination_station=station_names[fields[7]],
                        origin_code=fields[6],
                        destination_code=fields[7],
                        origin_station_no=fields[16],
                        destination_station_no=fields[17],
                        seat_types=fields[35],
                        departure_at=departure_at,
                        arrival_at=arrival_at,
                        duration_seconds=duration_seconds,
                        second_class_availability=fields[30],
                    )
                )
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeError,
            json.JSONDecodeError,
        ) as error:
            raise _RailFailure(
                stage="rail_schedule_parse",
                python_exception_type=type(error).__name__,
                response_bytes_received=True,
            ) from None
        return trains

    def second_class_price(
        self,
        *,
        train: _Train,
        travel_date: date,
    ) -> Decimal:
        body = self._get(
            _PRICE_PATH,
            {
                "train_no": train.train_no,
                "from_station_no": train.origin_station_no,
                "to_station_no": train.destination_station_no,
                "seat_types": train.seat_types,
                "train_date": travel_date.isoformat(),
            },
        )
        try:
            document = json.loads(body.decode("utf-8"))
            data = document["data"]
            if document.get("status") is not True or not isinstance(
                data,
                dict,
            ):
                raise ValueError("rail price status is not successful")
            raw_price = data["O"]
            if not isinstance(raw_price, str):
                raise TypeError("second-class price must be text")
            normalized = (
                raw_price.replace("¥", "").replace("￥", "").strip()
            )
            price = Decimal(normalized)
            if price < 0:
                raise ValueError("negative rail price")
        except (
            KeyError,
            TypeError,
            ValueError,
            InvalidOperation,
            UnicodeError,
            json.JSONDecodeError,
        ) as error:
            raise _RailFailure(
                stage="rail_price_parse",
                python_exception_type=type(error).__name__,
                response_bytes_received=True,
            ) from None
        return price


def _train_payload(train: _Train, price: Decimal) -> dict[str, object]:
    return {
        "train_code": train.train_code,
        "origin_station": train.origin_station,
        "destination_station": train.destination_station,
        "departure_at": train.departure_at.isoformat(timespec="minutes"),
        "arrival_at": train.arrival_at.isoformat(timespec="minutes"),
        "transfer_count": 0,
        "duration_seconds": train.duration_seconds,
        "second_class_fare_cny_per_person": float(price),
        "second_class_availability": train.second_class_availability,
    }


def search_live_station_names(
    query: str,
    *,
    limit: int = 30,
) -> dict[str, object]:
    """Search the current 12306 station index without retaining its bytes."""

    token = query.strip()
    if not token:
        raise ValueError("station query must be non-empty text")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
        or limit > 100
    ):
        raise ValueError("station result limit is invalid")
    client = _RailClient()
    attempted_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    try:
        names, _codes = client.station_codes()
    except _RailFailure as error:
        return {
            "support": "unknown",
            "domain": "railway_station_index",
            "missing_reason": error.stage,
            "network_attempts": client.network_attempts,
            "attempted_at": attempted_at,
        }
    matches = [name for name in names if token in name][:limit]
    return {
        "support": "sourced",
        "domain": "railway_station_index",
        "query": token,
        "station_names": matches,
        "retrieved_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "network_attempts": client.network_attempts,
        "source": {
            "provider": "中国铁路12306",
            "scope": "当前车站名称索引",
            "retrieved_at": attempted_at,
        },
    }


def query_intercity_rail(
    *,
    origin: str,
    destination: str,
    earliest_departure_at: str,
    latest_return_at: str,
    travelers: int = 1,
    budget_cny: float | None = None,
) -> dict[str, object]:
    """Query a direct round trip for arbitrary exact station names.

    Missing stations or schedules remain explicit ``missing`` evidence. The
    function never substitutes another station, route, provider, or static
    destination fact.
    """

    origin_name = origin.strip()
    destination_name = destination.strip()
    if not origin_name or not destination_name or origin_name == destination_name:
        raise ValueError("origin and destination must be distinct text")
    try:
        earliest = datetime.fromisoformat(earliest_departure_at)
        latest = datetime.fromisoformat(latest_return_at)
    except ValueError:
        raise ValueError("travel window must use ISO local datetime") from None
    if (
        earliest.tzinfo is not None
        or latest.tzinfo is not None
        or latest <= earliest
    ):
        raise ValueError("invalid local travel window")
    if (
        not isinstance(travelers, int)
        or isinstance(travelers, bool)
        or travelers < 1
    ):
        raise ValueError("travelers must be a positive integer")
    if budget_cny is not None and (
        not isinstance(budget_cny, (int, float))
        or isinstance(budget_cny, bool)
        or float(budget_cny) <= 0
    ):
        raise ValueError("budget_cny must be positive or null")

    attempted_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    client = _RailClient()
    try:
        client.initialize_web_session()
        name_to_code, code_to_name = client.station_codes()
        missing_stations = [
            name
            for name in (origin_name, destination_name)
            if name not in name_to_code
        ]
        if missing_stations:
            return {
                "support": "unknown",
                "domain": "railway",
                "missing_reason": "exact_station_identity_not_found",
                "missing_station_count": len(missing_stations),
                "attempted_at": attempted_at,
                "network_attempts": client.network_attempts,
            }
        origin_code = name_to_code[origin_name]
        destination_code = name_to_code[destination_name]
        outbound_options = [
            train
            for train in client.query_direct(
                travel_date=earliest.date(),
                origin_code=origin_code,
                destination_code=destination_code,
                station_names=code_to_name,
            )
            if train.departure_at >= earliest
        ]
        return_options = [
            train
            for train in client.query_direct(
                travel_date=latest.date(),
                origin_code=destination_code,
                destination_code=origin_code,
                station_names=code_to_name,
            )
            if train.arrival_at <= latest
        ]
        missing_legs = [
            label
            for label, options in (
                ("outbound", outbound_options),
                ("return", return_options),
            )
            if not options
        ]
        if missing_legs:
            return {
                "support": "unknown",
                "domain": "railway",
                "missing_reason": "direct_train_not_found_in_window",
                "missing_legs": missing_legs,
                "attempted_at": attempted_at,
                "network_attempts": client.network_attempts,
            }
        outbound = min(
            outbound_options,
            key=lambda item: (
                item.arrival_at,
                item.departure_at,
                item.train_code,
            ),
        )
        inbound = max(
            return_options,
            key=lambda item: (
                item.arrival_at,
                item.departure_at,
                item.train_code,
            ),
        )
        outbound_price = client.second_class_price(
            train=outbound,
            travel_date=earliest.date(),
        )
        inbound_price = client.second_class_price(
            train=inbound,
            travel_date=latest.date(),
        )
    except _RailFailure as error:
        return {
            "support": "unknown",
            "domain": "railway",
            "missing_reason": error.stage,
            "failure": {
                "stage": error.stage,
                "http_status": error.http_status,
                "python_exception_type": error.python_exception_type,
                "response_bytes_received": error.response_bytes_received,
            },
            "attempted_at": attempted_at,
            "network_attempts": client.network_attempts,
        }

    retrieved_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    total = (outbound_price + inbound_price) * travelers
    return {
        "support": "sourced",
        "domain": "railway",
        "origin": origin_name,
        "destination": destination_name,
        "travel_window": {
            "earliest_departure_at": earliest.isoformat(
                timespec="minutes"
            ),
            "latest_return_at": latest.isoformat(timespec="minutes"),
        },
        "outbound": _train_payload(outbound, outbound_price),
        "return": _train_payload(inbound, inbound_price),
        "roundtrip_fare_cny": float(total),
        "roundtrip_duration_seconds": (
            outbound.duration_seconds + inbound.duration_seconds
        ),
        "travelers": travelers,
        "within_total_budget": (
            float(total) <= float(budget_cny)
            if budget_cny is not None
            else None
        ),
        "snapshot": rail_snapshot_metadata(
            "live_fetch",
            retrieved_at=retrieved_at,
            attempted_at=attempted_at,
        ),
        "network_attempts": client.network_attempts,
        "source": {
            "provider": "中国铁路12306",
            "url": "https://kyfw.12306.cn/otn/leftTicket/init",
            "scope": "直达列车时刻、采集时余票与二等座票价",
            "retrieved_at": retrieved_at,
        },
        "conditions": [
            "车次、余票和票价仅代表采集时快照。",
            "未找到直达车时保持missing，不自动推断换乘方案。",
        ],
    }


__all__ = [
    "query_intercity_rail",
    "rail_snapshot_metadata",
    "search_live_station_names",
]
