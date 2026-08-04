"""STDIO MCP transport for the trip-decider application service.

The server is a thin transport adapter.  Tool implementations delegate to
``TripMCPAdapter``, which in turn calls only ``TripApplicationService`` and
``TripQueryService``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from trip_decider.mcp_adapter import TripMCPAdapter
from trip_decider.mcp_app import (
    TRIP_MCP_APP_MIME_TYPE,
    TRIP_MCP_APP_URI,
    load_trip_mcp_app_html,
)
from trip_decider.trip_services import (
    default_trip_services,
    TripServices,
    build_trip_services,
)


_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_MUTATING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
_ADVANCING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
from trip_decider.runtime_owner import RuntimeOwner
_VERIFYING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)

_APP_CALLABLE_META = {
    "ui": {"visibility": ["model", "app"]},
    "openai/widgetAccessible": True,
}
_APP_RENDER_META = {
    "ui": {
        "resourceUri": TRIP_MCP_APP_URI,
        "visibility": ["model", "app"],
    },
    "openai/outputTemplate": TRIP_MCP_APP_URI,
    "openai/widgetAccessible": True,
}


def build_mcp_server(adapter: TripMCPAdapter) -> MCPServer:
    """Create the headless tool server around an injected application bundle."""

    server = MCPServer(
        name="trip-decider",
        title="Trip Decider",
        description=(
            "出可查证的中国国内行程：车次来自实时查询的 12306，当地交通来自"
            "实时查询的高德路线。每个事实都带证据状态（sourced / estimated / "
            "unknown）和采集时间，查不到的就标 unknown，不靠模型记忆补。"
        ),
        instructions=(
            "【什么时候该用】用户要的行程需要「真的存在、真的到得了、真的没过期」"
            "时用本服务，而不是自己检索后凭记忆排行程。典型信号：问某趟车次是否"
            "真的有、问票价、问几点到、问信息是不是最新的、要一份能核对出处的"
            "行程、手里已有外部查询结果要交给系统核验。\n"
            "【和自己检索的区别】自己检索排出的行程没有出处也没有时效，"
            "说不出哪一条是查到的、哪一条是推的、什么时候查的。本服务的每个"
            "事实都带 support 与 retrieved_at，缺数据时明说 unknown 而不是填一个"
            "看起来合理的值。\n"
            "【最短路径】create_trip_task → confirm_trip_intent → "
            "advance_trip_task，然后一直跟着返回体里的 next_call 走。"
            "每个返回体都带 next_call，说明该调哪个工具、缺哪个字段——"
            "不需要自己推断状态机。\n"
            "【一条硬规则】不要编造证据。提交 sourced 证据必须带 sources；"
            "没查到就提交 status=\"missing\"，系统会把它如实标成 unknown。"
        ),
        version="0.1.0",
    )

    @server.resource(
        TRIP_MCP_APP_URI,
        name="trip-decider-workspace",
        title="Trip Decider 交互工作台",
        description=(
            "交互工作台：渲染目的地比较与已安装行程，每条数据旁标注证据状态与"
            "采集时间。不持有业务状态。"
        ),
        mime_type=TRIP_MCP_APP_MIME_TYPE,
        meta={"ui": {"prefersBorder": True}},
    )
    def trip_decider_workspace() -> str:
        return load_trip_mcp_app_html()

    @server.tool(
        name="create_trip_task",
        title="创建旅行任务",
        description=(
            "开一个新的行程任务。行程建成后，车次来自实时查询的 12306、"
            "当地交通来自实时查询的高德，每个事实带证据状态与采集时间。\n"
            "【什么时候用】用户说了想去哪/什么时候去/几个人/预算，"
            "并且希望行程是真的可行、可核对出处的。目的地说不准也能用——"
            "只给个方向（甚至完全不给）时系统会实查候选再比较。\n"
            "【intent 示例】地名原样填用户说的，下面用占位名示形状：\n"
            '{"origin": "<出发城市>", "destination_anchor": "<目的地区域>",\n'
            ' "destination_expression": "<用户原话，如「…那一带」>",\n'
            ' "earliest_departure_at": "2026-08-04T12:00",\n'
            ' "latest_return_at": "2026-08-07T22:00",\n'
            ' "travelers": 2, "total_budget_cny": 6000,\n'
            ' "pace": "relaxed", "transport_preferences": ["rail"],\n'
            ' "themes": ["自然", "古村"]}\n'
            "【易错点】时间是**不带时区的本地 ISO**（2026-08-04T12:00），"
            "带 Z 或 +08:00 会被拒。destination_anchor 是区域/城市名；"
            "完全不知道去哪就省略它，任务会走开放式发现。\n"
            "【task_mode】可不填，系统按 destination_expression 判断并在返回体的 "
            "classification_basis 里说明判断依据。要强制指定就显式写 "
            '"DIRECT_PLAN"（已确定目的地）或 "GUIDED_DISCOVERY"（要在区域内比较）。'
        ),
        annotations=_MUTATING,
        structured_output=True,
    )
    def create_trip_task(intent: dict[str, Any]) -> dict[str, Any]:
        return adapter.create_trip_task(intent)

    @server.tool(
        name="confirm_trip_intent",
        title="确认旅行需求",
        description=(
            "确认需求，之后任务才会开始实查。\n"
            "【什么时候用】create_trip_task 刚返回、条件核对无误时立刻调。"
            "任务在确认前不会发出任何查询。\n"
            "【最常见的用法】只传 run_id。create_trip_task 已经收下条件了，"
            "这一步就是「确认可以开跑」。\n"
            "【要改条件才传 intent】传了就整份替换，"
            "字段同 create_trip_task。\n"
            "【幂等】已经确认过、又没带 intent，会直接返回当前状态而不报错——"
            "不确定确认过没有，重复调一次是安全的。"
        ),
        annotations=_MUTATING,
        structured_output=True,
    )
    def confirm_trip_intent(
        run_id: str,
        intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return adapter.confirm_trip_intent(run_id, intent)

    @server.tool(
        name="advance_trip_task",
        title="推进旅行任务",
        description=(
            "推进任务到下一个检查点。**这是主循环**：确认之后反复调它，"
            "直到拿到行程或它要你补东西。\n"
            "【什么时候用】确认之后的每一步都用它，包括任务卡住时。"
            "拿不准现在该做什么，调它就对了。\n"
            "【它会做什么】真的去查 12306 车次与高德路线，然后停在四种检查点之一："
            "候选比较完成（去 select_trip_candidate）、行程可展示"
            "（去 show_trip_plan）、需要补证据（去 submit_trip_evidence）、"
            "还在跑（再调一次）。\n"
            "【不用自己判断下一步】返回体带 next_call，直接照着调。\n"
            "【被阻塞了也调它】任务卡住时它会重试可重试的那部分；"
            "重试不了的会在 next_call 里给出别的出路。\n"
            "【wait_seconds】0–30 之间，默认 10。实查车次通常要 20–40 秒，"
            "所以第一次多半会返回「还在跑」，再调一次即可，不是出错。"
        ),
        annotations=_ADVANCING,
        meta=_APP_CALLABLE_META,
        structured_output=True,
    )
    def advance_trip_task(
        run_id: str,
        wait_seconds: float = 10.0,
    ) -> dict[str, Any]:
        return adapter.advance_trip_task(
            run_id,
            wait_seconds=wait_seconds,
        )

    @server.tool(
        name="read_trip",
        title="读取旅行任务",
        description=(
            "只读地看任务的某一面，不推进任何状态。\n"
            "【view 取值】\n"
            '"overview"（默认）任务全貌 + 各域证据的新鲜度；\n'
            '"plan" 当前已安装行程（含每段的证据依赖）；\n'
            '"missing" 还缺什么、每一项该由谁补——**要补证据前先看这个**；\n'
            '"candidates" 候选比较结果；\n'
            '"map" 地图标记与路线；\n'
            '"audit" 审计结论。\n'
            "【想知道某条信息是否过期就用它】overview 里每个域都带 token 与 "
            "retrieved_at，能直接回答「这个数据是什么时候查的、现在还算不算数」。"
        ),
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def read_trip(
        run_id: str,
        view: str = "overview",
    ) -> dict[str, Any]:
        return adapter.read_trip(run_id, view=view)

    @server.tool(
        name="show_trip_candidates",
        title="展示目的地比较",
        description=(
            "展示目的地候选比较：每个候选都带**实查的**往返车次、净可玩时长、"
            "已知交通花费，以及各域证据的采集时间。\n"
            "【什么时候调】advance_trip_task 返回 checkpoint="
            "\"CANDIDATES_READY\" 之后。不确定就先 read_trip(view=\"candidates\")。\n"
            "【落选的也会说明】到不了或时间不够的候选会给出被排除的理由，"
            "不是静默消失。\n"
            "【比较没跑成时】列表里会有一张标着 comparison_status=\"not_compared\" "
            "的退路卡——那是用户报的区域本身，可以直接选它跳过比较。\n"
            "不支持 MCP Apps 的客户端拿到的结构化结果是完整的。"
        ),
        annotations=_READ_ONLY,
        meta={
            **_APP_RENDER_META,
            "openai/toolInvocation/invoking": "正在展示目的地方案…",
            "openai/toolInvocation/invoked": "目的地方案已展示",
        },
        structured_output=True,
    )
    def show_trip_candidates(run_id: str) -> dict[str, Any]:
        return adapter.render_trip_candidates(run_id)

    @server.tool(
        name="show_trip_plan",
        title="展示当前行程",
        description=(
            "展示当前行程：逐日时间轴、预算、缺口、路线摘要与修改入口。\n"
            "【可核对】每个事件都说得出自己出自哪条证据、那条证据什么时候采的。"
            "跨城段给车次号与起讫时刻；当地交通段给坐哪条线、在哪上下车、"
            "在哪换乘、票价与步行距离。查不到的项显示为待核验，不填看似合理的值。\n"
            "【什么时候调】checkpoint=\"PLAN_OR_PARTIAL_RESULT_READY\" 之后。\n"
            "【部分可展示也会给】证据没齐时给的是带缺口标注的草稿，"
            "不是空结果——缺什么写在 missing 里。"
        ),
        annotations=_READ_ONLY,
        meta={
            **_APP_RENDER_META,
            "openai/toolInvocation/invoking": "正在展示行程…",
            "openai/toolInvocation/invoked": "行程已展示",
        },
        structured_output=True,
    )
    def show_trip_plan(run_id: str) -> dict[str, Any]:
        return adapter.render_trip_plan(run_id)

    @server.tool(
        name="select_trip_candidate",
        title="选择目的地候选",
        description=(
            "选定一个目的地，在**同一个任务**里继续做详细规划"
            "（已采到的证据会被复用，不重查）。\n"
            "【什么时候用】候选比较完成、用户在几个候选里挑定了一个之后。"
            "只有一个候选也要显式选，那一步同时把任务切到详细规划。\n"
            "【candidate_id 从哪来】show_trip_candidates 或 "
            "read_trip(view=\"candidates\") 返回的每张卡上的 destination_id，"
            "原样传回。不要自己拼 id。\n"
            "【也能选退路卡】比较没跑成时列表里那张 "
            "comparison_status=\"not_compared\" 的卡也可以选，"
            "等于「跳过比较，直接规划这个区域」。"
        ),
        annotations=_MUTATING,
        meta=_APP_CALLABLE_META,
        structured_output=True,
    )
    def select_trip_candidate(
        run_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        return adapter.select_trip_candidate(run_id, candidate_id)

    @server.tool(
        name="submit_trip_evidence",
        title="提交旅行证据",
        description=(
            "把**你在外部查到的**结果交给系统核验并纳入行程。\n"
            "【什么时候用】系统自己没查到（checkpoint="
            "\"NEED_USER_INPUT_OR_EVIDENCE\"），而你手上有可靠结果；"
            "或者用户直接给了车次/住宿信息要求按它排。\n"
            "【evidence 示例】只有三个键是必须的：\n"
            '{"action_id": "railway",\n'
            ' "value": {"outbound": {"train_code": "G1234",\n'
            '                        "origin_station": "<出发站全称>",\n'
            '                        "destination_station": "<到达站全称>",\n'
            '                        "departure_at": "2026-08-04T13:12",\n'
            '                        "arrival_at": "2026-08-04T16:28"},\n'
            '            "return": { …同样五个字段… }},\n'
            ' "sources": [{"provider": "中国铁路12306",\n'
            '              "retrieved_at": "2026-08-04T10:00:00+08:00"}]}\n'
            "【不用填的】domain（恒等于 action_id）、evidence_id（自动生成）、"
            "status（有 value 即 sourced）。\n"
            "【action_id 取值】\"railway\" 车次｜\"web\" 目的地与景点事实｜"
            "\"map\" 当地交通。\n"
            "【必填字段以系统为准】被拒时报错会逐个点名缺哪个键；"
            "也可以先 read_trip(view=\"missing\") 看当前待补动作的 "
            "required_fields / optional_fields。\n"
            "【没查到就如实说】提交 "
            '{"action_id": "railway", "status": "missing", '
            '"missing_reason": "…"}，系统会标 unknown。'
            "**不要编一个看起来合理的车次**——本服务的全部价值在于每个事实"
            "都追得到出处。"
        ),
        annotations=_MUTATING,
        meta=_APP_CALLABLE_META,
        structured_output=True,
    )
    def submit_trip_evidence(
        run_id: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        return adapter.submit_trip_evidence(run_id, evidence)

    @server.tool(
        name="revise_trip_plan",
        title="修改当前行程",
        description=(
            "改行程，原子地装上新版本（旧版本保留，可对比）。\n"
            "【什么时候用】用户说「第二天太赶」「想慢一点」「把某个景点去掉」。\n"
            "【revision 示例】\n"
            '{"pace": "relaxed", "user_message": "第二天太赶，想慢一点"}\n'
            "【改的是约束不是像素】给意图（节奏、是否安排夜间活动、"
            "去掉哪个景点），系统重排并重新核对证据；不接受直接编辑时间轴。\n"
            "【改完仍然可核对】新版本的每个事件同样带证据依赖与采集时间。"
        ),
        annotations=_MUTATING,
        meta=_APP_CALLABLE_META,
        structured_output=True,
    )
    def revise_trip_plan(
        run_id: str,
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        return adapter.revise_trip_plan(run_id, revision)

    @server.tool(
        name="audit_trip_plan",
        title="审计已有攻略或计划",
        description=(
            "审计一份**别处来的**行程或攻略：逐条指出哪些说法有出处、"
            "哪些是查不到的、哪些自相矛盾。不排新行程。\n"
            "【什么时候用】用户贴来一份小红书/公众号攻略问「这个靠谱吗」，"
            "或者要核对别的工具排出的行程。\n"
            "【二选一】plan 传结构化行程对象，content 传攻略原文文本。\n"
            "【run_id 可不传】不传就自动开一个独立的审计任务，"
            "不会影响正在进行的行程任务。"
        ),
        annotations=_MUTATING,
        structured_output=True,
    )
    def audit_trip_plan(
        run_id: str | None = None,
        plan: dict[str, Any] | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        return adapter.audit_trip_plan(
            run_id=run_id,
            plan=plan,
            content=content,
        )

    @server.tool(
        name="verify_itinerary",
        title="核实已有行程",
        description=(
            "核验 AI 或人排好的行程：逐条对照 12306 实查，标出哪条是真的、"
            "哪条冲突、哪条查无实据。不排新行程，只核你手上这份。\n"
            "【什么时候用】用户贴来一份行程或攻略问「这个靠谱吗」；"
            "你自己（或别的工具）凭检索排了行程，想在给出前核一遍车次是否真实；"
            "用户问「这趟车真的有吗 / 这个票价对不对」。\n"
            "【assertions 示例】按 schema 提交断言列表：\n"
            '[{"train_code": "G1234",\n'
            '  "origin_station": "<出发站全称>",\n'
            '  "destination_station": "<到达站全称>",\n'
            '  "departure_at": "2026-08-11T12:40",\n'
            '  "arrival_at": "2026-08-11T16:28",\n'
            '  "price_cny": 149.0}]\n'
            "【必填四项】train_code、origin_station、destination_station、"
            "departure_at。arrival_at 与 price_cny 可选，给了就一起核。\n"
            "【站名要全称】12306 用的是车站全称，只写城市名核不到，"
            "会如实返回 unknown 并提示换全称。\n"
            "【三档结论】sourced 查到且对得上（附实查值与采集时间）｜"
            "conflicting 查到但对不上（附两边的值）｜unknown 查无实据。"
            "**unknown 不等于假**——可能是超出预售期、站名写法不同或网络故障，"
            "返回体会给出建议动作。\n"
            "【总评是计数不是评分】格式如「5 条断言：3 sourced / 1 conflicting"
            " / 1 unknown，建议出发前确认第 2、4 条」。\n"
            "【范围】v0 只核铁路域。住宿、门票、当地交通未核验——"
            "没核不等于没问题，返回体里明写了这一点。\n"
            "【一次最多 12 条】超了会要求分批，不会静默截断。\n"
            "【立刻返回，不要等】本工具**秒回**一个 verify_id 加首批结论"
            "（形状问题当场就能判）。实查 12306 在后台跑，用 "
            "read_verification(verify_id) 取增量——返回体的 next_call 会告诉你"
            "还剩几条。相同 assertions 在结果保留期内会复用同一 verify_id，"
            "不会重复打 12306。已核出的部分是最终结论，不会再变。"
        ),
        annotations=_VERIFYING,
        structured_output=True,
    )
    def verify_itinerary(
        assertions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return adapter.verify_itinerary(assertions)

    @server.tool(
        name="read_verification",
        title="取核验结果",
        description=(
            "取一份进行中或已完成的核验结果。verify_itinerary 立刻返回 "
            "verify_id，实查 12306 在后台推进，用这个取增量。\n"
            "【什么时候用】verify_itinerary 或上一次 read_verification 的返回体里 "
            "status 是 RUNNING 或 FINALIZING。FINALIZING 表示结论已经到齐、"
            "后台正在提交终态，再取一次即可。\n"
            "【怎么用】read_verification(verify_id=\"verify-…\")，"
            "把上一次返回的 verify_id 原样传回。每条断言约 2 秒，"
            "隔几秒取一次即可。\n"
            "【收工只看 status】completed/failed 才是终态；不要用 pending==0 "
            "判断收工，pending 只表示尚未得到结论的条数。\n"
            "【已核出的不会变】增量只增不改，可以在部分结果上先下判断。\n"
            "【结果保留一小时】服务重启或超时后 verify_id 失效，"
            "会明确报「这个 id 不存在」而不是假装还在跑。"
        ),
        annotations=_READ_ONLY,
        structured_output=True,
    )
    def read_verification(verify_id: str) -> dict[str, Any]:
        return adapter.read_verification(verify_id)

    return server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the trip-decider headless MCP server over STDIO."
    )
    parser.add_argument(
        "--runtime-root",
        type=Path,
        help=(
            "Explicit sessions directory. Omit to use the same default "
            "runtime as Standalone Web."
        ),
    )
    parser.add_argument(
        "--with-web",
        action="store_true",
        help="Also serve Standalone Web from the exact same in-process runtime.",
    )
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=8765)
    return parser


def _services_for(arguments: argparse.Namespace) -> TripServices:
    if arguments.runtime_root is None:
        return default_trip_services()
    return build_trip_services(arguments.runtime_root)


def main() -> int:
    arguments = _parser().parse_args()
    services = _services_for(arguments)
    runtime_root = services.application.store.runtime_root
    if runtime_root is None:
        raise RuntimeError("MCP runtime root is not configured")
    owner = RuntimeOwner(runtime_root)
    owner.acquire()
    web_server = None
    web_thread = None
    try:
        if arguments.with_web:
            from trip_decider import product_web

            product_web.configure_services(
                services.application,
                services.query,
            )
            web_server = product_web.make_server(
                arguments.web_host,
                arguments.web_port,
            )
            web_thread = threading.Thread(
                target=web_server.serve_forever,
                name="trip-decider-shared-web",
                daemon=True,
            )
            web_thread.start()
            host, port = web_server.server_address
            print(
                f"trip-decider shared web: http://{host}:{port}/",
                file=sys.stderr,
                flush=True,
            )
        server = build_mcp_server(
            TripMCPAdapter(services.application, services.query)
        )
        server.run("stdio")
    finally:
        if web_server is not None:
            web_server.shutdown()
            web_server.server_close()
        if web_thread is not None:
            web_thread.join(timeout=5)
        owner.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_mcp_server", "main"]
