"use strict";

const state = {
  runId: null,
  sessionId: null,
  intent: null,
  lastSequence: 0,
  eventSource: null,
  pollTimer: null,
  confirmationMode: "confirm_existing",
  confirmationOpen: false,
};

const $ = (selector) => document.querySelector(selector);

const fieldLabels = {
  origin: "出发地",
  earliest_departure_at: "最早出发",
  latest_return_at: "最晚返回",
  travelers: "人数",
  total_budget_cny: "总预算",
  pace: "节奏",
  transport_preferences: "交通偏好",
  destination_anchor: "目的地",
};

const questions = {
  origin: "从哪里出发？",
  earliest_departure_at: "最早什么时候可以出发？",
  latest_return_at: "最晚什么时候需要返回？",
  travelers: "一共有几位旅行者？",
  total_budget_cny: "这次旅行的总预算是多少？",
  pace: "希望轻松、标准还是紧凑？",
  transport_preferences: "跨城交通偏好是什么？",
  destination_anchor: "这次优先规划哪个目的地？",
};

const paceLabels = {
  relaxed: "轻松",
  standard: "标准",
  intensive: "紧凑",
  custom: "自定义",
};

const transportLabels = {
  high_speed_rail: "高铁",
  rail: "铁路",
  driving: "自驾",
  flight: "飞机",
  walking: "步行",
  public_transit: "公共交通",
};

const modeLabels = {
  OPEN_DISCOVERY: "开放目的地发现",
  ANCHORED_PLAN: "锚定目的地规划",
  PLAN_AUDIT: "已有计划审计",
};

const runLabels = {
  AWAITING_CONFIRMATION: "等待确认",
  CONFIRMED: "已确认",
  RUNNING: "执行中",
  COMPLETED: "已完成",
  BLOCKED: "受阻",
  FAILED: "执行失败",
};

const planLabels = {
  CONTEXT_INCOMPLETE: "信息不足，暂不能规划",
  NEEDS_USER_DECISION: "需要用户决定",
  CONTEXT_READY: "规划上下文已就绪",
  PARTIAL_PLAN_WITH_CONFLICTS: "已有部分行程，仍有冲突",
  CONDITIONALLY_FEASIBLE: "条件可行",
  conditionally_feasible: "条件可行",
  FEASIBLE: "可行",
  feasible: "可行",
  NO_PLAN_FOUND: "暂未找到可行安排",
  no_plan_found: "暂未找到可行安排",
};

const domainLabels = {
  railway: "跨城铁路时刻与票价",
  map: "目的地身份与当地路线",
  web: "开放时间、门票等网页事实",
  user_input: "用户确认的旅行条件",
};

const toolLabels = {
  parse_intent: "需求合同",
  railway: "跨城铁路",
  map: "地图与地点",
  web: "网页事实",
  destination_context: "目的地上下文",
  planner: "行程规划",
  validator: "可行性校验",
};

const eventStatusLabels = {
  started: "开始",
  running: "进行中",
  completed: "完成",
  failed: "失败",
};

function setStatus(target, message, error = false) {
  target.textContent = message;
  target.classList.toggle("error", error);
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const value = await response.json();
  if (!response.ok) {
    throw new Error(value.message || value.error || `请求失败（${response.status}）`);
  }
  return value;
}

async function getJson(path) {
  const response = await fetch(path, {cache: "no-store"});
  const value = await response.json();
  if (!response.ok) {
    throw new Error(value.message || value.error || `请求失败（${response.status}）`);
  }
  return value;
}

function formatDateTime(value) {
  if (!value) return "待补充";
  const match = String(value).match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/,
  );
  if (!match) return String(value);
  return `${Number(match[1])}年${Number(match[2])}月${Number(match[3])}日 ${match[4]}:${match[5]}`;
}

function formatIntentValue(field, value) {
  if (value === null || value === undefined || value === "") return "待补充";
  if (field === "earliest_departure_at" || field === "latest_return_at") {
    return formatDateTime(value);
  }
  if (field === "travelers") return `${value}人`;
  if (field === "total_budget_cny") {
    return `¥${Number(value).toLocaleString("zh-CN")}`;
  }
  if (field === "pace") return paceLabels[value] || "自定义";
  if (field === "transport_preferences") {
    if (!Array.isArray(value) || !value.length) return "待补充";
    return value.map((item) => transportLabels[item] || "其他交通").join("、");
  }
  return String(value);
}

function requiredFields(intent) {
  const fields = [
    "origin",
    "earliest_departure_at",
    "latest_return_at",
    "travelers",
    "total_budget_cny",
    "pace",
    "transport_preferences",
  ];
  if (intent.task_mode === "ANCHORED_PLAN") fields.push("destination_anchor");
  return fields;
}

function missingFields(intent) {
  const explicit = Array.isArray(intent.missing_fields) ? intent.missing_fields : [];
  const inferred = requiredFields(intent).filter((field) => {
    const value = intent[field];
    return value === null
      || value === undefined
      || value === ""
      || (Array.isArray(value) && value.length === 0);
  });
  return [...new Set([...inferred, ...explicit])];
}

function inputForField(field, value) {
  let input;
  if (field === "pace") {
    input = document.createElement("select");
    [
      ["", "请选择"],
      ["relaxed", "轻松"],
      ["standard", "标准"],
      ["intensive", "紧凑"],
      ["custom", "自定义"],
    ].forEach(([optionValue, label]) => {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = label;
      input.append(option);
    });
  } else if (field === "transport_preferences") {
    input = document.createElement("select");
    [
      ["", "请选择"],
      ["high_speed_rail", "高铁"],
      ["rail", "铁路"],
      ["driving", "自驾"],
      ["flight", "飞机"],
      ["public_transit", "公共交通"],
    ].forEach(([optionValue, label]) => {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = label;
      input.append(option);
    });
  } else {
    input = document.createElement("input");
    input.type = {
      earliest_departure_at: "datetime-local",
      latest_return_at: "datetime-local",
      travelers: "number",
      total_budget_cny: "number",
    }[field] || "text";
    if (field === "travelers") {
      input.min = "1";
      input.step = "1";
    }
    if (field === "total_budget_cny") {
      input.min = "1";
      input.step = "100";
    }
  }
  input.name = field;
  input.id = `intent-${field}`;
  const normalized = field === "transport_preferences"
    ? (Array.isArray(value) ? value[0] || "" : "")
    : value ?? "";
  input.value = String(normalized);
  input.setAttribute("aria-label", fieldLabels[field]);
  return input;
}

function renderIntent(target, intent, editable = false) {
  target.replaceChildren();
  const rows = [
    ["origin", intent.origin],
    ["earliest_departure_at", intent.earliest_departure_at],
    ["latest_return_at", intent.latest_return_at],
    ["travelers", intent.travelers],
    ["total_budget_cny", intent.total_budget_cny],
    ["pace", intent.pace],
    ["transport_preferences", intent.transport_preferences],
    ["destination_anchor", intent.destination_anchor],
  ];
  const list = document.createElement("div");
  list.className = "intent-list";
  rows.forEach(([field, value]) => {
    const row = document.createElement("div");
    row.className = "intent-row";
    const label = document.createElement("span");
    label.textContent = fieldLabels[field];
    const content = editable
      ? inputForField(field, value)
      : document.createElement("strong");
    if (!editable) content.textContent = formatIntentValue(field, value);
    row.append(label, content);
    list.append(row);
  });
  target.append(list);
}

function intentFromForm() {
  const form = $("#intent-form");
  const value = {...state.intent};
  value.origin = form.elements.origin.value.trim() || null;
  value.destination_anchor =
    form.elements.destination_anchor.value.trim() || null;
  if (value.task_mode !== "PLAN_AUDIT") {
    value.task_mode = value.destination_anchor
      ? "ANCHORED_PLAN"
      : "OPEN_DISCOVERY";
  }
  value.earliest_departure_at =
    form.elements.earliest_departure_at.value || null;
  value.latest_return_at =
    form.elements.latest_return_at.value || null;
  value.travelers = form.elements.travelers.value
    ? Number(form.elements.travelers.value)
    : null;
  value.total_budget_cny = form.elements.total_budget_cny.value
    ? Number(form.elements.total_budget_cny.value)
    : null;
  value.pace = form.elements.pace.value || null;
  value.transport_preferences = form.elements.transport_preferences.value
    ? [form.elements.transport_preferences.value]
    : [];
  value.missing_fields = [];
  return value;
}

function renderMissingQuestions(intent) {
  const missing = missingFields(intent);
  const panel = $("#missing-panel");
  const list = $("#missing-questions");
  list.replaceChildren();
  missing.forEach((field) => {
    const item = document.createElement("li");
    item.textContent = questions[field] || `请补充${fieldLabels[field] || "缺失条件"}。`;
    list.append(item);
  });
  panel.classList.toggle("hidden", missing.length === 0);
  $("#confirm-button").disabled = missing.length > 0;
  return missing;
}

function refreshConfirmationGate() {
  const intent = intentFromForm();
  state.intent = intent;
  const missing = renderMissingQuestions(intent);
  setStatus(
    $("#confirmation-status"),
    missing.length
      ? "请补充上方缺失条件。"
      : "条件完整；确认后才会开始查询真实数据。",
    missing.length > 0,
  );
}

function showConfirmation(response) {
  const run = response.run;
  state.runId = run.run_id;
  state.sessionId = response.session.session_id;
  state.intent = run.intent;
  state.lastSequence = Math.max(
    0,
    ...response.events.map((event) => Number(event.sequence)),
  );
  state.confirmationMode = "confirm_existing";
  state.confirmationOpen = true;
  renderIntent($("#intent-summary"), run.intent, true);
  const missing = renderMissingQuestions(run.intent);
  setStatus(
    $("#confirmation-status"),
    missing.length
      ? "旅行条件尚不完整，当前不能执行。"
      : "条件完整；确认后才会开始查询真实数据。",
    missing.length > 0,
  );
  $("#landing").classList.add("hidden");
  $("#workbench").classList.add("hidden");
  $("#confirmation").classList.remove("hidden");
}

function showEditableIntent(intent, mode = "create_replacement") {
  state.intent = {...intent, missing_fields: []};
  state.confirmationMode = mode;
  state.confirmationOpen = true;
  renderIntent($("#intent-summary"), state.intent, true);
  renderMissingQuestions(state.intent);
  $("#landing").classList.add("hidden");
  $("#workbench").classList.add("hidden");
  $("#confirmation").classList.remove("hidden");
  refreshConfirmationGate();
}

function showWorkbench(response) {
  const run = response.run;
  state.runId = run.run_id;
  state.sessionId = response.session.session_id;
  state.intent = run.intent;
  state.confirmationOpen = false;
  renderIntent($("#confirmed-intent"), run.intent);
  $("#mode-label").textContent = modeLabels[run.intent.task_mode] || "旅行规划";
  $("#run-status").textContent = runLabels[run.status] || "处理中";
  $("#landing").classList.add("hidden");
  $("#confirmation").classList.add("hidden");
  $("#workbench").classList.remove("hidden");
  $("#edit-button").disabled = ![
    "COMPLETED",
    "BLOCKED",
    "FAILED",
  ].includes(run.status);
  renderEvents(response.events);
  updateProgress(response.events, run);
  renderResult(run);
}

function progressStage(event) {
  const tool = event.details?.tool;
  if (event.event_type?.startsWith("intent.") || event.event_type === "run.started") {
    return "understand";
  }
  if (["railway", "map", "web"].includes(tool)) return "collect";
  if (["destination_context", "validator"].includes(tool)) return "validate";
  if (tool === "planner" || event.event_type === "run.completed") return "plan";
  return null;
}

function setProgressState(step, status) {
  const item = document.querySelector(`#progress-grid [data-step="${step}"]`);
  if (!item) return;
  const labels = {
    waiting: "等待",
    running: "进行中",
    completed: "已完成",
    blocked: "受阻",
  };
  item.dataset.state = status;
  item.querySelector("em").textContent = labels[status];
}

function updateProgress(events, run) {
  const order = ["understand", "collect", "validate", "plan"];
  const states = Object.fromEntries(order.map((step) => [step, "waiting"]));
  if (run.status !== "AWAITING_CONFIRMATION") {
    states.understand = "completed";
  }

  events.forEach((event) => {
    const stage = progressStage(event);
    if (!stage) return;
    if (event.status === "started" || event.status === "running") {
      states[stage] = "running";
    } else if (event.status === "completed") {
      states[stage] = "completed";
    } else if (event.status === "failed") {
      states[stage] = "blocked";
    }
  });

  const result = run.result;
  const missing = result?.plan?.missing
    || result?.context?.missing_domains
    || [];
  const conflicting = result?.plan?.conflicting
    || result?.context?.conflicting_domains
    || [];
  if (run.status === "COMPLETED" && missing.length) {
    states.collect = "blocked";
    states.validate = "waiting";
    states.plan = "waiting";
  } else if (run.status === "COMPLETED" && conflicting.length) {
    states.collect = "completed";
    states.validate = "blocked";
    states.plan = "waiting";
  } else if (run.status === "COMPLETED") {
    order.forEach((step) => {
      states[step] = "completed";
    });
  } else if (run.status === "FAILED" || run.status === "BLOCKED") {
    const lastStarted = [...events]
      .reverse()
      .map(progressStage)
      .find(Boolean) || "collect";
    states[lastStarted] = "blocked";
    const blockedIndex = order.indexOf(lastStarted);
    order.slice(blockedIndex + 1).forEach((step) => {
      states[step] = "waiting";
    });
  }
  order.forEach((step) => setProgressState(step, states[step]));

  const blocked = Object.values(states).includes("blocked");
  $("#run-status").textContent = blocked
    ? "存在阻塞"
    : runLabels[run.status] || "处理中";
  const runningStep = order.find((step) => states[step] === "running");
  const message = $("#run-message");
  if (blocked) {
    message.querySelector("p").textContent =
      "真实数据或约束存在阻塞，请查看右侧说明。";
  } else if (runningStep) {
    const label = document.querySelector(
      `#progress-grid [data-step="${runningStep}"] strong`,
    ).textContent;
    message.querySelector("p").textContent = `${label}正在进行。`;
  } else if (run.status === "COMPLETED") {
    message.querySelector("p").textContent = "本次运行已结束。";
  } else {
    message.querySelector("p").textContent = "等待下一步执行。";
  }
}

function renderEvents(events) {
  const target = $("#event-stream");
  target.replaceChildren();
  events.forEach((event) => {
    const item = document.createElement("div");
    item.className = "event-row";
    const tool = event.details?.tool;
    const label = toolLabels[tool]
      || (event.event_type?.startsWith("intent.") ? "需求确认" : "运行状态");
    const name = document.createElement("strong");
    name.textContent = label;
    const status = document.createElement("span");
    status.textContent = eventStatusLabels[event.status] || "更新";
    const time = document.createElement("time");
    time.textContent = new Date(event.occurred_at).toLocaleTimeString(
      "zh-CN",
      {hour12: false, hour: "2-digit", minute: "2-digit"},
    );
    item.append(name, status, time);
    target.append(item);
  });
  state.lastSequence = Math.max(
    state.lastSequence,
    0,
    ...events.map((event) => Number(event.sequence)),
  );
}

function domainList(values) {
  if (!Array.isArray(values) || !values.length) return [];
  return values.map((value) => domainLabels[value] || "尚未识别的数据");
}

function appendList(section, values, fallback) {
  const list = document.createElement("ul");
  const items = values.length ? values : [fallback];
  items.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  });
  section.append(list);
}

function renderInsufficient(result, run) {
  const target = $("#result-area");
  target.replaceChildren();
  const context = result?.context || {};
  const plan = result?.plan || {};
  const missing = domainList(plan.missing || context.missing_domains);
  const conflicting = domainList(plan.conflicting || context.conflicting_domains);

  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("h2");
  title.textContent = "暂时无法形成可靠行程";
  const badge = document.createElement("span");
  badge.textContent = planLabels[plan.status] || (
    ["FAILED", "BLOCKED"].includes(run.status) ? "执行受阻" : "信息不足"
  );
  heading.append(title, badge);

  const grid = document.createElement("div");
  grid.className = "guidance-grid";
  const sections = [
    [
      "还缺哪些信息",
      missing,
      "当前没有可安全展示的完整证据。",
    ],
    [
      "为什么暂时无法规划",
      conflicting.length
        ? conflicting.map((item) => `${item}存在冲突。`)
        : ["关键数据不足时，系统不会用猜测补成行程。"],
      "关键数据不足时，系统不会用猜测补成行程。",
    ],
    [
      "用户下一步需要做什么",
      [
        "请让 Codex 补充缺失条件，或在真实数据源恢复后重新执行。",
      ],
      "请让 Codex 补充必要条件后重新执行。",
    ],
  ];
  sections.forEach(([label, values, fallback]) => {
    const section = document.createElement("section");
    const titleElement = document.createElement("h3");
    titleElement.textContent = label;
    section.append(titleElement);
    appendList(section, values, fallback);
    grid.append(section);
  });
  const actions = document.createElement("div");
  actions.className = "blocked-actions";
  [
    ["重新查询", retryCurrentRun, "primary"],
    ["手动补充", () => editCurrentRun(true), "secondary"],
    ["返回修改", () => editCurrentRun(false), "ghost"],
  ].forEach(([label, handler, style]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `button ${style}`;
    button.textContent = label;
    button.addEventListener("click", handler);
    actions.append(button);
  });
  target.append(heading, grid, actions);
  $("#result-status").textContent = "暂时受阻";
}

function renderCompleted(result) {
  const target = $("#result-area");
  target.replaceChildren();
  const plan = result.plan || {};
  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("h2");
  title.textContent = "旅行规划结果";
  const badge = document.createElement("span");
  badge.textContent = planLabels[plan.status] || "结果已生成";
  heading.append(title, badge);

  const summary = document.createElement("div");
  summary.className = "result-summary";
  const statements = [
    ["可发布", plan.publishable === true ? "是" : "否"],
    ["能力边界", "结果只覆盖已取得并通过校验的证据。"],
  ];
  statements.forEach(([label, value]) => {
    const row = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = label;
    const content = document.createElement("strong");
    content.textContent = value;
    row.append(name, content);
    summary.append(row);
  });
  target.append(heading, summary);
  $("#result-status").textContent = "已生成";
}

function renderResult(run) {
  const result = run.result;
  if (!result) {
    if (run.status === "FAILED" || run.status === "BLOCKED") {
      $("#result-column").classList.remove("hidden");
      $("#workbench").classList.add("has-result");
      renderInsufficient(null, run);
    } else {
      $("#result-column").classList.add("hidden");
      $("#workbench").classList.remove("has-result");
    }
    return;
  }
  $("#result-column").classList.remove("hidden");
  $("#workbench").classList.add("has-result");
  const plan = result.plan || {};
  const missing = plan.missing || result.context?.missing_domains || [];
  const conflicting = plan.conflicting || result.context?.conflicting_domains || [];
  if (
    run.status === "FAILED"
    || run.status === "BLOCKED"
    || plan.status === "CONTEXT_INCOMPLETE"
    || missing.length
    || conflicting.length
  ) {
    renderInsufficient(result, run);
    return;
  }
  renderCompleted(result);
}

function editCurrentRun(focusMissing) {
  showEditableIntent(state.intent, "create_replacement");
  if (focusMissing) {
    const missing = missingFields(state.intent);
    const field = missing[0] || "origin";
    document.querySelector(`[name="${field}"]`)?.focus();
  }
}

async function retryCurrentRun() {
  $("#run-status").textContent = "正在重新查询";
  try {
    const response = await postJson(
      `/api/agent/runs/${state.runId}/retry`,
      {},
    );
    showWorkbench(response);
    connectEvents();
  } catch (error) {
    $("#run-status").textContent = "重新查询失败";
    const target = $("#result-area");
    const message = document.createElement("p");
    message.className = "page-status error";
    message.textContent = error.message;
    target.append(message);
  }
}

function connectEvents() {
  state.eventSource?.close();
  const source = new EventSource(
    `/api/agent/sessions/${state.sessionId}/events?after=${state.lastSequence}`,
  );
  state.eventSource = source;
  source.addEventListener("agent_event", async () => {
    try {
      const response = await getJson(`/api/agent/runs/${state.runId}`);
      showWorkbench(response);
      if (
        ["COMPLETED", "BLOCKED", "FAILED"].includes(response.run.status)
      ) {
        source.close();
        state.eventSource = null;
      }
    } catch (error) {
      $("#run-status").textContent = "状态更新失败";
    }
  });
}

async function confirmAndExecute() {
  const button = $("#confirm-button");
  const status = $("#confirmation-status");
  const correctedIntent = intentFromForm();
  state.intent = correctedIntent;
  if (missingFields(correctedIntent).length) {
    setStatus(status, "旅行条件尚不完整，不能执行。", true);
    return;
  }
  button.disabled = true;
  setStatus(status, "正在确认旅行条件…");
  try {
    if (state.confirmationMode === "create_replacement") {
      const created = await postJson(
        "/api/agent/runs",
        {intent: correctedIntent},
      );
      state.runId = created.run.run_id;
      state.sessionId = created.session.session_id;
    }
    const confirmed = await postJson(
      `/api/agent/runs/${state.runId}/confirm`,
      {intent: correctedIntent},
    );
    showWorkbench(confirmed);
    connectEvents();
    await postJson(`/api/agent/runs/${state.runId}/execute`, {});
  } catch (error) {
    setStatus(status, error.message, true);
    button.disabled = false;
  }
}

async function pollCurrentRun() {
  if (state.confirmationOpen) return;
  try {
    const response = await getJson("/api/agent/current");
    if (!response.run) return;
    const isNewRun = response.run.run_id !== state.runId;
    if (isNewRun || response.run.status !== "AWAITING_CONFIRMATION") {
      if (response.run.status === "AWAITING_CONFIRMATION") {
        showConfirmation(response);
      } else {
        showWorkbench(response);
        if (response.run.status === "RUNNING" && !state.eventSource) {
          connectEvents();
        }
      }
    }
  } catch {
    setStatus($("#landing-status"), "本地产品服务暂时不可用。", true);
  }
}

async function loadRuntime() {
  try {
    const config = await getJson("/api/client-config");
    $("#runtime-status").textContent = config.ai.display;
  } catch {
    $("#runtime-status").textContent = "本地运行时不可用";
  }
}

$("#confirm-button").addEventListener("click", confirmAndExecute);
$("#intent-form").addEventListener("input", refreshConfirmationGate);
$("#intent-form").addEventListener("change", refreshConfirmationGate);
$("#edit-button").addEventListener("click", () => editCurrentRun(false));
loadRuntime();
pollCurrentRun();
state.pollTimer = window.setInterval(pollCurrentRun, 1000);
