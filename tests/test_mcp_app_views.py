"""Presentation-only MCP App envelopes for plan, verification, and maps."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest

from trip_decider.mcp_adapter import TripMCPAdapter
from trip_decider.mcp_app import load_trip_mcp_app_html
from trip_decider.travel_agent import EvidenceItem, EvidenceStatus


STAMP = "2026-08-05T09:00:00+08:00"

BADGE_STYLE = {
    "verified": "#18794e",
    "sourced_stale": "#9a6700",
    "estimated": "#9a6700",
    "conflicting": "#c9372c",
    "unknown": "#667085",
}


def _walk(node: dict[str, object]):
    yield node
    for child in node.get("children", []):
        if isinstance(child, dict):
            yield from _walk(child)


def _node_text(node: dict[str, object]) -> str:
    return str(node.get("text") or "") + "".join(
        _node_text(child)
        for child in node.get("children", [])
        if isinstance(child, dict)
    )


def _has_class(node: dict[str, object], name: str) -> bool:
    return name in str(node.get("className") or "").split()


def _nodes(
    root: dict[str, object],
    *,
    tag: str | None = None,
    class_name: str | None = None,
) -> list[dict[str, object]]:
    return [
        node
        for node in _walk(root)
        if (tag is None or node.get("tag") == tag)
        and (class_name is None or _has_class(node, class_name))
    ]


def _badge_styles(html: str) -> dict[str, str]:
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    result: dict[str, str] = {}
    for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
        background = re.search(r"\bbackground:\s*([^;]+)", declarations)
        if background is None:
            continue
        for token in re.findall(r'\.token\[data-token="([^"]+)"\]', selectors):
            result[token] = background.group(1).strip().lower()
    return result


def _render_resource(payload: dict[str, object]) -> dict[str, object]:
    """Execute the shipped MCP App script against a minimal deterministic DOM."""

    node = shutil.which("node")
    if node is None:
        raise AssertionError("content-level MCP App tests require Node.js")
    html = load_trip_mcp_app_html()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    harness = f"""
class FakeNode {{
  constructor(tag) {{
    this.tagName = tag;
    this.children = [];
    this._text = "";
    this.className = "";
    this.dataset = {{}};
    this.style = {{}};
    this.attributes = {{}};
    this.classList = {{
      add: (...names) => {{
        const values = new Set(this.className.split(/\\s+/).filter(Boolean));
        names.forEach((name) => values.add(name));
        this.className = [...values].join(" ");
      }},
    }};
  }}
  set textContent(value) {{ this._text = String(value ?? ""); this.children = []; }}
  get textContent() {{ return this._text + this.children.map((child) => child.textContent).join(""); }}
  append(...nodes) {{ nodes.filter(Boolean).forEach((node) => this.children.push(node)); }}
  replaceChildren(...nodes) {{ this.children = []; this._text = ""; this.append(...nodes); }}
  setAttribute(name, value) {{ this.attributes[name] = String(value); }}
  addEventListener() {{}}
  get childElementCount() {{ return this.children.length; }}
}}
const app = new FakeNode("main");
global.document = {{
  getElementById: () => app,
  createElement: (tag) => new FakeNode(tag),
  createElementNS: (_namespace, tag) => new FakeNode(tag),
  documentElement: new FakeNode("html"),
}};
global.window = {{
  parent: null,
  addEventListener() {{}},
  innerWidth: 900,
  openai: {{toolOutput: {json.dumps(payload, ensure_ascii=False)}}},
}};
window.parent = window;
window.postMessage = () => {{}};
global.requestAnimationFrame = () => {{}};
global.ResizeObserver = class {{ observe() {{}} }};
{script}
const serialize = (node) => ({{
  tag: node.tagName,
  className: node.className,
  text: node._text,
  dataset: node.dataset,
  attributes: node.attributes,
  children: node.children.map(serialize),
}});
process.stdout.write(JSON.stringify(serialize(app)));
"""
    completed = subprocess.run(
        [node, "-"],
        input=harness,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "MCP App resource did not render:\n" + completed.stderr
        )
    return json.loads(completed.stdout)


def _rail_item() -> dict[str, object]:
    return EvidenceItem(
        evidence_id="rail-live",
        domain="railway",
        status=EvidenceStatus.SOURCED,
        value={"outbound": {"train_code": "G100"}},
        sources=({"provider": "中国铁路12306", "retrieved_at": STAMP},),
    ).to_dict()


def _web_item() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="web-live",
        domain="web",
        status=EvidenceStatus.SOURCED,
        value={
            "attractions": [
                {
                    "name": "坐标景点",
                    "location": {
                        "longitude": 117.8,
                        "latitude": 29.25,
                        "coordinate_system": "GCJ-02",
                    },
                }
            ]
        },
        sources=({"provider": "高德地图", "retrieved_at": STAMP},),
    )


class _Application:
    def current_run_evidence(self, _run_id: str) -> dict[str, object]:
        return {"railway": _rail_item()}

    def guided_evidence_for_selection(
        self,
        _run_id: str,
        _destination_id: str,
    ) -> dict[str, EvidenceItem]:
        return {"web": _web_item()}


class _MixedCoordinateApplication(_Application):
    def guided_evidence_for_selection(
        self,
        _run_id: str,
        _destination_id: str,
    ) -> dict[str, EvidenceItem]:
        return {
            "web": EvidenceItem(
                evidence_id="web-mixed-coordinate",
                domain="web",
                status=EvidenceStatus.SOURCED,
                value={
                    "attractions": [
                        {
                            "name": "坐标景点甲",
                            "location": {
                                "longitude": 117.80,
                                "latitude": 29.25,
                                "coordinate_system": "GCJ-02",
                            },
                        },
                        {"name": "缺坐标景点"},
                        {
                            "name": "坐标景点乙",
                            "location": {
                                "longitude": 117.82,
                                "latitude": 29.27,
                                "coordinate_system": "GCJ-02",
                            },
                        },
                    ]
                },
                sources=({"provider": "高德地图", "retrieved_at": STAMP},),
            )
        }


class _Query:
    def __init__(self, application: _Application) -> None:
        self.application_service = application

    @staticmethod
    def candidates(_run_id: str) -> dict[str, object]:
        return {
            "candidates": [
                {"destination_id": "candidate-one", "name": "候选甲"}
            ]
        }

    @staticmethod
    def current_plan(_run_id: str) -> dict[str, object]:
        return {
            "plan_version": 1,
            "plan": {
                "days": [
                    {
                        "day": 1,
                        "date": "2026-08-10",
                        "events": [
                            {
                                "event_id": "rail-outbound",
                                "type": "transit",
                                "name": "G100",
                                "fact_refs": [
                                    "rail-live#outbound.train_code"
                                ],
                            }
                        ],
                    }
                ]
            },
        }

    @staticmethod
    def trip(_run_id: str) -> dict[str, object]:
        return {
            "presentation": {
                "evidence_statuses": [
                    {
                        "domain": "railway",
                        "label": "跨城铁路",
                        "token": "verified",
                        "retrieved_at": STAMP,
                    }
                ],
                "map_payload": {
                    "markers": [
                        {
                            "marker_id": "point-one",
                            "name": "坐标景点",
                            "position": {
                                "longitude": 117.8,
                                "latitude": 29.25,
                            },
                        }
                    ],
                    "route_polylines": [],
                },
            }
        }


class MCPAppEnvelopeCase(unittest.TestCase):
    def setUp(self) -> None:
        application = _Application()
        self.adapter = TripMCPAdapter(application, _Query(application))

    def test_plan_renders_five_badge_styles_and_budget_status_rows(self) -> None:
        tokens = list(BADGE_STYLE)
        payload = {
            "view": "plan",
            "run_id": "run-five-badges",
            "current_version": 3,
            "plan": {
                "plan_version": 3,
                "planning_state": "PLAN_READY",
                "plan": {
                    "days": [
                        {
                            "day": 1,
                            "date": "2026-08-10",
                            "events": [
                                {
                                    "event_id": "event-with-five-badges",
                                    "name": "五态证据事件",
                                    "start_at": "2026-08-10T09:00",
                                    "end_at": "2026-08-10T10:00",
                                    "detail": "内容级渲染测试",
                                }
                            ],
                        }
                    ]
                },
            },
            "event_evidence": {
                "event-with-five-badges": {
                    "badges": [
                        {
                            "label": f"徽章-{token}",
                            "token": token,
                            "retrieved_at": STAMP,
                            "sources": [{"provider": "测试来源"}],
                        }
                        for token in tokens
                    ],
                    "unresolved_fact_refs": [],
                }
            },
            "trip": {
                "presentation": {
                    "budget_summary": [
                        {
                            "label": "铁路",
                            "known_cny": 120,
                            "estimated_cny": 0,
                            "unknown": False,
                        },
                        {
                            "label": "住宿",
                            "known_cny": 0,
                            "estimated_cny": 380,
                            "unknown": False,
                        },
                        {
                            "label": "当地交通",
                            "known_cny": 0,
                            "estimated_cny": 0,
                            "unknown": True,
                        },
                    ],
                    "evidence_statuses": [],
                    "map_payload": {"markers": [], "route_polylines": []},
                }
            },
        }

        rendered = _render_resource(payload)

        badges = _nodes(rendered, tag="span", class_name="token")
        self.assertEqual(tokens, [badge["dataset"]["token"] for badge in badges])
        self.assertEqual(BADGE_STYLE, {
            token: _badge_styles(load_trip_mcp_app_html())[token]
            for token in tokens
        })
        budget_body = _nodes(rendered, tag="tbody")[0]
        rows = [
            [_node_text(cell) for cell in row["children"]]
            for row in budget_body["children"]
        ]
        self.assertEqual(
            [
                ["铁路", "¥120", "已知"],
                ["住宿", "¥380", "估算"],
                ["当地交通", "—", "含待核验金额"],
            ],
            rows,
        )

    def test_verification_renders_exact_summary_and_adjacent_conflicts(self) -> None:
        findings = [
            {
                "index": index,
                "verdict": "sourced",
                "claim": {"train_code": f"G10{index}"},
                "observed": {"train_code": f"G10{index}"},
                "mismatches": [],
                "retrieved_at": STAMP,
                "suggested_action": None,
            }
            for index in range(1, 4)
        ]
        findings.extend(
            [
                {
                    "index": 4,
                    "verdict": "conflicting",
                    "claim": {"train_code": "G400"},
                    "observed": {"train_code": "G401"},
                    "mismatches": [
                        {
                            "field": "train_code",
                            "claimed": "G400",
                            "observed": "G401",
                        }
                    ],
                    "retrieved_at": STAMP,
                    "suggested_action": "采用实查车次",
                },
                {
                    "index": 5,
                    "verdict": "conflicting",
                    "claim": {"train_code": "G500", "price_cny": 100},
                    "observed": {"train_code": "G500", "price_cny": 120},
                    "mismatches": [
                        {
                            "field": "price_cny",
                            "claimed": 100,
                            "observed": 120,
                        }
                    ],
                    "retrieved_at": STAMP,
                    "suggested_action": "采用实查票价",
                },
                {
                    "index": 6,
                    "verdict": "unknown",
                    "claim": {"train_code": "G600"},
                    "observed": None,
                    "mismatches": [],
                    "retrieved_at": None,
                    "suggested_action": "稍后重查",
                },
            ]
        )
        payload = self.adapter._verification_view(
            {
                "verify_id": "verify-six",
                "status": "COMPLETE",
                "total": 6,
                "checked": 6,
                "pending": 0,
                "findings": findings,
            }
        )

        rendered = _render_resource(payload)

        subtitles = [
            _node_text(node)
            for node in _nodes(rendered, tag="p", class_name="subtitle")
        ]
        self.assertIn(
            "6 条：3 sourced / 2 conflicting / 1 unknown",
            subtitles,
        )
        pairs = _nodes(rendered, tag="div", class_name="diff-value")
        self.assertEqual(2, len(pairs))
        self.assertEqual(
            ["声称：G400", "实查：G401"],
            [_node_text(child) for child in pairs[0]["children"]],
        )
        self.assertEqual(
            ["声称：100", "实查：120"],
            [_node_text(child) for child in pairs[1]["children"]],
        )

    def test_map_point_count_matches_only_pois_with_coordinates(self) -> None:
        application = _MixedCoordinateApplication()
        adapter = TripMCPAdapter(application, _Query(application))
        payload = adapter.render_trip_candidates("run-map-count")

        markers = payload["candidate_maps"]["candidate-one"]["markers"]
        self.assertEqual(2, len(markers))
        self.assertNotIn("缺坐标景点", {marker["name"] for marker in markers})

        rendered = _render_resource(payload)
        points = _nodes(rendered, tag="circle", class_name="map-point")
        labels = {
            _node_text(node)
            for node in _nodes(rendered, tag="text", class_name="map-label")
        }
        self.assertEqual(2, len(points))
        self.assertEqual({"坐标景点甲", "坐标景点乙"}, labels)
        self.assertNotIn("缺坐标景点", labels)


class MCPAppResourceShapeCase(unittest.TestCase):
    def test_single_resource_contains_all_three_renderers(self) -> None:
        html = load_trip_mcp_app_html()
        for renderer in ("renderCandidates", "renderPlan", "renderVerification"):
            self.assertIn(renderer, html)
        self.assertIn("mapFigure", html)


if __name__ == "__main__":
    unittest.main()
