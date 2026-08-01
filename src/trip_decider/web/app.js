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
  lastResponse: null,
  skippedBlockers: new Set(),
  lockedEventIds: new Set(),
  guidedTimer: null,
  pinnedRunId: new URLSearchParams(window.location.search).get("run_id"),
  mapConfig: null,
  mapConfigPromise: null,
  mapScriptPromise: null,
  map: null,
  mapPayload: null,
  mapPayloadSignature: null,
  mapRenderToken: 0,
  mapMarkers: new Map(),
  mapRoutes: new Map(),
  mapActiveDay: "all",
  selectedEventId: null,
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
  accommodation_budget_total_cny: "住宿总预算",
  accommodation_budget_per_night_cny: "每晚住宿预算",
  rooms: "房间数",
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
  GUIDED_DISCOVERY: "倾向区域比较",
  DIRECT_PLAN: "确定目的地规划",
  PLAN_AUDIT: "已有计划审计",
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

const eventTypeLabels = {
  transit: "交通",
  attraction: "景点",
  meal: "用餐",
  hotel: "住宿",
  buffer: "缓冲",
  rest: "休息",
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
  if ([
    "total_budget_cny",
    "accommodation_budget_total_cny",
    "accommodation_budget_per_night_cny",
  ].includes(field)) {
    return `¥${Number(value).toLocaleString("zh-CN")}`;
  }
  if (field === "rooms") return `${value}间`;
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
  if (["GUIDED_DISCOVERY", "DIRECT_PLAN"].includes(intent.task_mode)) {
    fields.push("destination_anchor");
  }
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
    if ([
      "accommodation_budget_total_cny",
      "accommodation_budget_per_night_cny",
    ].includes(field)) {
      input.type = "number";
      input.min = "1";
      input.step = "100";
    }
    if (field === "rooms") {
      input.type = "number";
      input.min = "1";
      input.step = "1";
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
    ["accommodation_budget_total_cny", intent.accommodation_budget_total_cny],
    ["accommodation_budget_per_night_cny", intent.accommodation_budget_per_night_cny],
    ["rooms", intent.rooms],
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
    if (!value.destination_anchor) {
      value.task_mode = "OPEN_DISCOVERY";
    } else if (!["GUIDED_DISCOVERY", "DIRECT_PLAN"].includes(value.task_mode)) {
      value.task_mode = "GUIDED_DISCOVERY";
    }
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
  value.accommodation_budget_total_cny = form.elements.accommodation_budget_total_cny.value
    ? Number(form.elements.accommodation_budget_total_cny.value)
    : null;
  value.accommodation_budget_per_night_cny = form.elements.accommodation_budget_per_night_cny.value
    ? Number(form.elements.accommodation_budget_per_night_cny.value)
    : null;
  value.rooms = form.elements.rooms.value
    ? Number(form.elements.rooms.value)
    : null;
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

function configureConfirmationActions(intent) {
  const isGuided = intent.task_mode === "GUIDED_DISCOVERY";
  $("#confirm-button").textContent = isGuided
    ? "开始比较区域方案"
    : "确认并开始";
}

function refreshConfirmationGate() {
  const intent = intentFromForm();
  state.intent = intent;
  configureConfirmationActions(intent);
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
  const currentUrl = new URL(window.location.href);
  currentUrl.searchParams.set("run_id", run.run_id);
  window.history.replaceState({}, "", currentUrl);
  state.pinnedRunId = run.run_id;
  renderIntent($("#intent-summary"), run.intent, true);
  configureConfirmationActions(run.intent);
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
  configureConfirmationActions(state.intent);
  renderMissingQuestions(state.intent);
  $("#landing").classList.add("hidden");
  if (mode === "revise_existing") {
    $("#workbench").classList.remove("hidden");
    $("#confirmation").classList.add("editing-existing");
  } else {
    $("#workbench").classList.add("hidden");
    $("#confirmation").classList.remove("editing-existing");
  }
  $("#confirmation").classList.remove("hidden");
  refreshConfirmationGate();
}

function showWorkbench(response) {
  const run = response.run;
  state.lastResponse = response;
  state.runId = run.run_id;
  state.sessionId = response.session.session_id;
  state.intent = run.intent;
  state.lastSequence = Math.max(
    state.lastSequence,
    0,
    ...(response.events || []).map((event) => Number(event.sequence)),
  );
  const currentUrl = new URL(window.location.href);
  if (currentUrl.searchParams.get("run_id") !== run.run_id) {
    currentUrl.searchParams.set("run_id", run.run_id);
    window.history.replaceState({}, "", currentUrl);
    state.pinnedRunId = run.run_id;
  }
  state.confirmationOpen = false;
  $("#confirmation").classList.remove("editing-existing");
  renderIntent($("#confirmed-intent"), run.intent);
  $("#mode-label").textContent = modeLabels[run.intent.task_mode] || "旅行规划";
  $("#landing").classList.add("hidden");
  $("#confirmation").classList.add("hidden");
  $("#workbench").classList.remove("hidden");
  $("#edit-button").disabled = ![
    "COMPLETED",
    "BLOCKED",
    "FAILED",
  ].includes(run.status);
  updateCompactProgress(response.presentation?.compact_progress, run);
  renderResult(run, response.presentation || {});
  renderMapPanel(response.presentation?.map_payload || null);
}

function mapConfig() {
  if (!state.mapConfigPromise) {
    state.mapConfigPromise = getJson("/api/client-config").then((value) => {
      state.mapConfig = value.amap_js || {configured: false, missing: []};
      return state.mapConfig;
    });
  }
  return state.mapConfigPromise;
}

function loadAmap(config) {
  if (window.AMap) return Promise.resolve(window.AMap);
  if (state.mapScriptPromise) return state.mapScriptPromise;
  window._AMapSecurityConfig = {
    securityJsCode: config.security_js_code,
  };
  state.mapScriptPromise = new Promise((resolve, reject) => {
    const callbackName = `tripDeciderAmapReady${Date.now()}`;
    window[callbackName] = () => {
      delete window[callbackName];
      if (window.AMap) {
        resolve(window.AMap);
      } else {
        reject(new Error("高德地图脚本未提供地图对象"));
      }
    };
    const script = document.createElement("script");
    script.async = true;
    script.src = (
      "https://webapi.amap.com/maps?v=2.0"
      + `&key=${encodeURIComponent(config.key)}`
      + `&callback=${encodeURIComponent(callbackName)}`
    );
    script.addEventListener("error", () => {
      delete window[callbackName];
      state.mapScriptPromise = null;
      reject(new Error("高德 JS API 加载失败"));
    }, {once: true});
    document.head.append(script);
  });
  return state.mapScriptPromise;
}

function mapPoint(position) {
  if (
    !position
    || !Number.isFinite(Number(position.longitude))
    || !Number.isFinite(Number(position.latitude))
  ) {
    return null;
  }
  return [Number(position.longitude), Number(position.latitude)];
}

function markerClass(kind) {
  return [
    "station",
    "accommodation",
    "attraction",
    "transit_stop",
  ].includes(kind) ? kind : "transit_stop";
}

function routeColor(mode) {
  return {
    public_transit: "#3678a8",
    walking: "#23805b",
    driving: "#bd6c2f",
    taxi: "#bd6c2f",
    self_driving: "#bd6c2f",
  }[mode] || "#66716b";
}

function markerVisible(marker) {
  return (
    state.mapActiveDay === "all"
    || (
      Array.isArray(marker.day)
      && marker.day.includes(Number(state.mapActiveDay))
    )
  );
}

function routeVisible(route) {
  return (
    state.mapActiveDay === "all"
    || Number(route.day) === Number(state.mapActiveDay)
  );
}

function focusTimelineEvent(eventId) {
  if (!eventId) return;
  const event = document.querySelector(
    `.timeline-event[data-event-id="${CSS.escape(eventId)}"]`,
  );
  if (!event) return;
  event.scrollIntoView({block: "center", behavior: "smooth"});
}

function setSelectedEvent(eventId, {fromMap = false} = {}) {
  state.selectedEventId = eventId || null;
  document.querySelectorAll(".timeline-event.is-selected").forEach((item) => {
    item.classList.remove("is-selected");
  });
  if (eventId) {
    document.querySelectorAll(
      `.timeline-event[data-event-id="${CSS.escape(eventId)}"]`,
    ).forEach((item) => item.classList.add("is-selected"));
  }
  state.mapMarkers.forEach(({overlay, value}) => {
    const selected = eventId && (value.event_id || []).includes(eventId);
    overlay.setzIndex(selected ? 220 : 110);
    const content = overlay.getContent();
    if (content instanceof HTMLElement) {
      content.classList.toggle("is-selected", Boolean(selected));
    }
  });
  state.mapRoutes.forEach(({overlay, value}) => {
    const selected = eventId && value.event_id === eventId;
    overlay.setOptions({
      strokeWeight: selected ? 9 : 6,
      zIndex: selected ? 210 : 100,
    });
  });
  if (fromMap) focusTimelineEvent(eventId);
}

function focusMapEvent(eventId) {
  if (!eventId || !state.map) return;
  const markerEntry = [...state.mapMarkers.values()].find(
    ({value}) => (value.event_id || []).includes(eventId),
  );
  const routeEntry = [...state.mapRoutes.values()].find(
    ({value}) => value.event_id === eventId,
  );
  if (markerEntry && markerEntry.overlay.getMap()) {
    state.map.setZoomAndCenter(
      Math.max(state.map.getZoom(), 13),
      markerEntry.overlay.getPosition(),
    );
  } else if (routeEntry && routeEntry.overlay.getMap()) {
    state.map.setFitView([routeEntry.overlay], false, [72, 72, 72, 72]);
  }
  if (routeEntry) showMapRouteStatus(routeEntry.value);
}

function showMapRouteStatus(route) {
  const status = $("#map-status");
  const mode = transportLabels[route.transport_mode] || "当地交通";
  if (route.route_kind === "railway_schematic") {
    setStatus(
      status,
      `${route.from} → ${route.to}：铁路示意虚线，不代表实际铁路轨迹。`,
    );
    return;
  }
  if (route.evidence_status === "STALE") {
    setStatus(
      status,
      `${route.from} → ${route.to}：${mode}较早数据，采集于 ${
        formatDateTime(route.retrieved_at)
      }；路线以虚线显示。`,
    );
    return;
  }
  setStatus(status, `${route.from} → ${route.to}：${mode}，本次证据。`);
}

function bindTimelineMapEvent(item, event) {
  const eventId = event.event_id;
  if (!eventId) return;
  item.dataset.eventId = String(eventId);
  item.tabIndex = 0;
  item.setAttribute("role", "button");
  item.setAttribute("aria-label", `在地图中定位${event.name || "该事件"}`);
  const activate = () => {
    setSelectedEvent(String(eventId));
    focusMapEvent(String(eventId));
  };
  item.addEventListener("click", activate);
  item.addEventListener("keydown", (keyboardEvent) => {
    if (keyboardEvent.key === "Enter" || keyboardEvent.key === " ") {
      keyboardEvent.preventDefault();
      activate();
    }
  });
}

function renderMapDayTabs(payload) {
  const target = $("#map-day-tabs");
  target.replaceChildren();
  const options = [
    {value: "all", label: "全部行程"},
    ...(payload.day || []).map((day) => ({
      value: String(day.day),
      label: `Day ${day.day}`,
    })),
  ];
  options.forEach(({value, label}) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "map-day-tab";
    button.textContent = label;
    button.classList.toggle("is-active", state.mapActiveDay === value);
    button.addEventListener("click", () => {
      state.mapActiveDay = value;
      renderMapDayTabs(payload);
      applyMapDayFilter();
    });
    target.append(button);
  });
}

function renderRailwayMapCards(payload) {
  const target = $("#railway-map-cards");
  target.replaceChildren();
  (payload.rail_segments || [])
    .filter((segment) => (
      state.mapActiveDay === "all"
      || Number(segment.day) === Number(state.mapActiveDay)
    ))
    .forEach((segment) => {
      const card = document.createElement("article");
      card.className = "railway-map-card";
      const title = document.createElement("strong");
      title.textContent = `${segment.from}站 → ${segment.to}站`;
      const detail = document.createElement("span");
      const fare = Number.isFinite(Number(segment.fare_cny))
        ? ` · ¥${Number(segment.fare_cny).toLocaleString("zh-CN")}`
        : " · 票价待核验";
      detail.textContent = `${segment.train_code || "铁路"} · ${
        eventClock(segment.start_at)
      }–${eventClock(segment.end_at)}${fare}`;
      const note = document.createElement("small");
      note.textContent = (
        segment.evidence_status === "STALE" && segment.retrieved_at
          ? `较早数据，采集于 ${formatDateTime(segment.retrieved_at)}；不绘制铁路轨迹`
          : "仅显示车站和时间费用，不绘制铁路轨迹"
      );
      card.addEventListener("click", () => {
        setSelectedEvent(String(segment.event_id));
        focusMapEvent(String(segment.event_id));
      });
      card.append(title, detail, note);
      target.append(card);
    });
}

function renderMapMissingGeometry(payload) {
  const target = $("#map-missing-geometry");
  target.replaceChildren();
  const missingRoutes = (payload.route_polylines || []).filter((route) => (
    route.geometry_status !== "EXISTING_POLYLINE"
    && routeVisible(route)
  ));
  if (!missingRoutes.length) return;
  const title = document.createElement("strong");
  title.textContent = "待核验路线";
  const list = document.createElement("ul");
  missingRoutes.forEach((route) => {
    const item = document.createElement("li");
    item.textContent = route.geometry_status === "ENDPOINTS_ONLY"
      ? `${route.from} → ${route.to}：已有端点，但缺少该交通方式的真实路线；不画直线`
      : `${route.from} → ${route.to}：当前版本未保存端点坐标或路线几何`;
    list.append(item);
  });
  target.append(title, list);
}

function mapMarkerContent(marker) {
  const root = document.createElement("button");
  root.type = "button";
  root.className = `map-marker map-marker-${markerClass(marker.kind)}`;
  root.textContent = marker.display_name || marker.name;
  root.title = marker.display_name || marker.name;
  return root;
}

function markerEvent(marker) {
  const values = marker.event_id || [];
  if (state.mapActiveDay === "all") return values[0] || null;
  return values.find((eventId) => {
    const timeline = document.querySelector(
      `.timeline-event[data-event-id="${CSS.escape(eventId)}"]`,
    );
    return Number(timeline?.dataset.day) === Number(state.mapActiveDay);
  }) || values[0] || null;
}

function syncMapOverlays(payload, AMap) {
  const nextMarkerIds = new Set();
  (payload.markers || []).forEach((marker) => {
    const point = mapPoint(marker.position);
    if (!point) return;
    nextMarkerIds.add(marker.marker_id);
    const previous = state.mapMarkers.get(marker.marker_id);
    if (previous) {
      previous.value = marker;
      previous.overlay.setPosition(point);
      previous.overlay.setContent(mapMarkerContent(marker));
      return;
    }
    const overlay = new AMap.Marker({
      position: point,
      content: mapMarkerContent(marker),
      anchor: "bottom-center",
      title: marker.display_name || marker.name,
      zIndex: 110,
    });
    overlay.on("click", () => {
      const current = state.mapMarkers.get(marker.marker_id)?.value || marker;
      const eventId = markerEvent(current);
      setSelectedEvent(eventId, {fromMap: true});
    });
    state.mapMarkers.set(marker.marker_id, {overlay, value: marker});
  });
  state.mapMarkers.forEach(({overlay}, markerId) => {
    if (!nextMarkerIds.has(markerId)) {
      overlay.setMap(null);
      state.mapMarkers.delete(markerId);
    }
  });

  const nextRouteIds = new Set();
  (payload.route_polylines || []).forEach((route) => {
    const path = (route.polyline || []).map(mapPoint).filter(Boolean);
    if (path.length < 2) return;
    nextRouteIds.add(route.route_id);
    const options = {
      path,
      strokeColor: routeColor(route.transport_mode),
      strokeWeight: 6,
      strokeOpacity: route.route_kind === "railway_schematic" ? 0.6 : 0.92,
      strokeStyle: (
        route.evidence_status === "STALE"
        || route.route_kind === "railway_schematic"
      ) ? "dashed" : "solid",
      lineJoin: "round",
      lineCap: "round",
      showDir: route.route_kind === "local",
      zIndex: 100,
    };
    const previous = state.mapRoutes.get(route.route_id);
    if (previous) {
      previous.value = route;
      previous.overlay.setOptions(options);
      return;
    }
    const overlay = new AMap.Polyline(options);
    overlay.on("click", () => {
      const current = state.mapRoutes.get(route.route_id)?.value || route;
      setSelectedEvent(current.event_id, {fromMap: true});
      showMapRouteStatus(current);
    });
    state.mapRoutes.set(route.route_id, {overlay, value: route});
  });
  state.mapRoutes.forEach(({overlay}, routeId) => {
    if (!nextRouteIds.has(routeId)) {
      overlay.setMap(null);
      state.mapRoutes.delete(routeId);
    }
  });
}

function applyMapDayFilter() {
  if (!state.map) return;
  const visible = [];
  state.mapMarkers.forEach(({overlay, value}) => {
    const show = markerVisible(value);
    overlay.setMap(show ? state.map : null);
    if (show) visible.push(overlay);
  });
  state.mapRoutes.forEach(({overlay, value}) => {
    const show = routeVisible(value);
    overlay.setMap(show ? state.map : null);
    if (show) visible.push(overlay);
  });
  if (visible.length) {
    state.map.setFitView(visible, false, [72, 72, 72, 72]);
  }
  setSelectedEvent(state.selectedEventId);
}

async function renderMapPanel(payload) {
  const column = $("#map-column");
  if (!payload || !Array.isArray(payload.day) || !payload.day.length) {
    column.classList.add("hidden");
    $("#workbench").classList.remove("has-map");
    return;
  }
  column.classList.remove("hidden");
  $("#workbench").classList.add("has-map");
  state.mapPayload = payload;
  const validDays = new Set((payload.day || []).map((day) => String(day.day)));
  if (state.mapActiveDay !== "all" && !validDays.has(state.mapActiveDay)) {
    state.mapActiveDay = "all";
  }
  $("#map-plan-version").textContent = Number.isInteger(payload.plan_version)
    ? `版本 ${payload.plan_version}`
    : "";
  renderMapDayTabs(payload);
  $("#railway-map-cards").replaceChildren();
  $("#map-missing-geometry").replaceChildren();
  const status = $("#map-status");
  const canvas = $("#map-canvas");
  const token = ++state.mapRenderToken;
  let config;
  try {
    config = await mapConfig();
  } catch {
    setStatus(status, "无法读取地图配置；未显示地图。", true);
    canvas.classList.add("hidden");
    return;
  }
  if (token !== state.mapRenderToken) return;
  if (!config.configured) {
    setStatus(
      status,
      `地图未配置：请设置 ${(config.missing || []).join(" 和 ")}。未显示假地图。`,
      true,
    );
    canvas.classList.add("hidden");
    return;
  }
  canvas.classList.remove("hidden");
  try {
    const AMap = await loadAmap(config);
    if (token !== state.mapRenderToken) return;
    if (!state.map) {
      state.map = new AMap.Map(canvas, {
        viewMode: "2D",
        zoom: 10,
        resizeEnable: true,
      });
    }
    const signature = JSON.stringify(payload);
    if (signature !== state.mapPayloadSignature) {
      syncMapOverlays(payload, AMap);
      state.mapPayloadSignature = signature;
    }
    applyMapDayFilter();
    const drawableMarkers = (payload.markers || []).filter(
      (marker) => Boolean(mapPoint(marker.position)),
    ).length;
    const drawableRoutes = (payload.route_polylines || []).filter(
      (route) => (route.polyline || []).map(mapPoint).filter(Boolean).length >= 2,
    ).length;
    if (!drawableMarkers) {
      setStatus(
        status,
        "真实底图已加载；当前 plan version 未保存地点坐标，因此没有可绘制 Marker 或路线。",
        true,
      );
    } else {
      const staleRoutes = (payload.route_polylines || []).filter(
        (route) => route.evidence_status === "STALE",
      ).length;
      setStatus(
        status,
        `已显示 ${drawableMarkers} 个地点、${drawableRoutes} 段路线${
          staleRoutes ? `；${staleRoutes} 段为较早数据虚线` : ""
        }。`,
      );
    }
  } catch {
    setStatus(status, "高德 JS API 加载失败；未显示假地图。", true);
    canvas.classList.add("hidden");
  }
}

function formatElapsed(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (value < 60) return `${Math.floor(value)} 秒`;
  const minutes = Math.floor(value / 60);
  return `${minutes} 分 ${Math.floor(value % 60)} 秒`;
}

function updateCompactProgress(progress, run) {
  const panel = $("#compact-progress");
  const active = (
    run.status !== "AWAITING_CONFIRMATION"
    && progress
    && progress.state !== "completed"
  );
  panel.classList.toggle("hidden", !active);
  $(".app-shell").classList.toggle("progress-active", Boolean(active));
  if (state.guidedTimer) {
    clearInterval(state.guidedTimer);
    state.guidedTimer = null;
  }
  if (!active) return;

  const render = () => {
    const latest = state.lastResponse?.presentation?.compact_progress || progress;
    const latestRun = state.lastResponse?.run || run;
    let elapsed = Number(latest.elapsed_seconds) || 0;
    if (latest.state === "running" && latestRun.started_at) {
      const started = Date.parse(latestRun.started_at);
      if (Number.isFinite(started)) {
        elapsed = Math.max(elapsed, (Date.now() - started) / 1000);
      }
    }
    const percent = Math.max(
      0,
      Math.min(99, Number(latest.percent_complete) || 0),
    );
    $("#compact-progress-fill").style.width = `${percent}%`;
    $("#compact-progress-percent").textContent = `${percent}%`;
    $("#compact-progress-task").textContent =
      latest.current_task || "理解旅行需求";
    $("#compact-progress-elapsed").textContent =
      `已用 ${formatElapsed(elapsed)}`;
    panel.querySelector("[role='progressbar']").setAttribute(
      "aria-valuenow",
      String(percent),
    );
  };
  render();
  if (progress.state === "running") {
    state.guidedTimer = setInterval(render, 1000);
  }
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
        "点击“继续查询”重试失败项，或点击“手动补充”填写缺失条件。",
      ],
      "补充必要条件后可从当前任务继续。",
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
    ["继续查询", continueCurrentRun, "primary"],
    ["手动补充", () => editCurrentRun(true), "secondary"],
    ["暂时跳过", skipVisibleBlockers, "ghost"],
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

function eventClock(value) {
  if (typeof value !== "string") return "时间待定";
  const match = value.match(/T(\d{2}:\d{2})/);
  return match ? match[1] : value;
}

function eventDescription(event) {
  const details = [];
  if (typeof event.location === "string" && event.location) {
    details.push(event.location);
  }
  if (event.from && event.to) {
    details.push(`${event.from} → ${event.to}`);
  }
  if (Number.isFinite(event.duration_seconds)) {
    details.push(`${Math.round(event.duration_seconds / 60)} 分钟`);
  }
  if (Number.isFinite(event.distance_meters)) {
    details.push(`${(event.distance_meters / 1000).toFixed(1)} 公里`);
  }
  if (Number.isFinite(event.planning_allocation_minutes)) {
    details.push(`游览 ${event.planning_allocation_minutes} 分钟`);
  }
  const fare = event.fare;
  if (fare && Number.isFinite(fare.amount_cny)) {
    details.push(`约 ¥${fare.amount_cny}`);
  }
  return details.join(" · ");
}

function renderEvidenceStatuses(target, presentation) {
  const section = document.createElement("section");
  const title = document.createElement("h3");
  title.textContent = "数据新鲜度";
  section.append(title);
  const list = document.createElement("ul");
  (presentation.evidence_statuses || []).forEach((item) => {
    const row = document.createElement("li");
    const status = {
      LIVE: "本次查询",
      STALE: "较早数据",
      MISSING: "尚未取得",
    }[item.status] || "待核验";
    const collected = item.retrieved_at
      ? ` · 采集于 ${formatDateTime(item.retrieved_at)}`
      : "";
    row.textContent = `${item.label}：${status}（${item.count || 0}）${collected}`;
    list.append(row);
  });
  section.append(list);
  target.append(section);
}

function renderTimeline(target, plan) {
  const dayCount = (plan.days || []).length;
  (plan.days || []).forEach((day) => {
    const section = document.createElement("section");
    section.className = "timeline-day";
    const title = document.createElement("h3");
    title.textContent = `Day ${day.day} · ${day.date || "日期待定"}`;
    section.append(title);
    const list = document.createElement("div");
    list.className = "timeline-events";
    (day.events || []).forEach((event) => {
      const item = document.createElement("article");
      item.className = `timeline-event event-${event.type || "other"}`;
      item.dataset.day = String(day.day);
      const type = eventTypeLabels[event.type] || "行程";
      const range = `${eventClock(event.start_at)}–${eventClock(event.end_at)}`;
      const detail = eventDescription(event);
      const time = document.createElement("time");
      time.textContent = range;
      const body = document.createElement("div");
      const heading = document.createElement("h4");
      heading.textContent = `${type} · ${event.name || "未命名事件"}`;
      const description = document.createElement("p");
      description.textContent = detail || "费用或时长待核验";
      const why = document.createElement("small");
      why.textContent = event.why || "按当前旅行条件安排";
      body.append(heading, description, why);
      if (event.type === "attraction") {
        const features = document.createElement("p");
        features.className = "event-features";
        features.textContent = Array.isArray(event.features) && event.features.length
          ? `特色：${event.features.join("、")}`
          : "特色待核验";
        body.append(features);
        body.append(attractionControls(event, dayCount));
      }
      item.append(time, body);
      bindTimelineMapEvent(item, event);
      if (state.selectedEventId === event.event_id) {
        item.classList.add("is-selected");
      }
      list.append(item);
    });
    if (!list.childElementCount) {
      const empty = document.createElement("p");
      empty.textContent = "当天仍在补充真实数据。";
      list.append(empty);
    }
    section.append(list);
    target.append(section);
  });
}

function renderLocalTransitReferences(target, plan) {
  const routes = Array.isArray(plan.planning_input?.local_transit_events)
    ? plan.planning_input.local_transit_events
    : [];
  if (!routes.length) return;
  const section = document.createElement("section");
  section.className = "guidance-card";
  const title = document.createElement("h3");
  title.textContent = "已核验的当地交通";
  const note = document.createElement("p");
  note.textContent = (
    "以下为地图返回的公交时长与距离；具体酒店未选，"
    + "每日首末段仍需在酒店确定后细化。"
  );
  const list = document.createElement("ul");
  routes.forEach((route) => {
    const item = document.createElement("li");
    const freshness = route.schedule_status === "STALE"
      ? "较早数据"
      : "本次查询";
    item.textContent = `${route.from} → ${route.to}：${
      formatDurationSeconds(route.duration_seconds)
    } · ${Number.isFinite(route.distance_meters)
      ? `${(route.distance_meters / 1000).toFixed(1)}公里`
      : "距离待核验"} · ${Number.isFinite(route.fare?.amount_cny)
      ? `约 ¥${route.fare.amount_cny}`
      : "费用待核验"} · ${freshness}`;
    list.append(item);
  });
  section.append(title, note, list);
  target.append(section);
}

function attractionControls(event, dayCount) {
  const controls = document.createElement("div");
  controls.className = "event-controls";
  const attractionId = event.attraction_id;

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "button ghost compact";
  remove.textContent = "删除";
  remove.addEventListener("click", () => submitRevision({
    removed_attraction_ids: [attractionId],
    locked_event_ids: [...state.lockedEventIds],
  }));

  const move = document.createElement("select");
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "换到…";
  move.append(placeholder);
  for (let day = 1; day <= dayCount; day += 1) {
    const option = document.createElement("option");
    option.value = String(day);
    option.textContent = `Day ${day}`;
    move.append(option);
  }
  move.addEventListener("change", () => {
    if (!move.value) return;
    submitRevision({
      forced_days: {[attractionId]: Number(move.value)},
      locked_event_ids: [...state.lockedEventIds],
    });
  });

  const duration = document.createElement("input");
  duration.type = "number";
  duration.min = "15";
  duration.max = "720";
  duration.step = "15";
  duration.value = String(event.planning_allocation_minutes || 120);
  duration.setAttribute("aria-label", `${event.name}游玩分钟`);
  const durationButton = document.createElement("button");
  durationButton.type = "button";
  durationButton.className = "button ghost compact";
  durationButton.textContent = "改时长";
  durationButton.addEventListener("click", () => submitRevision({
    event_duration_minutes: {
      [event.event_id]: Number(duration.value),
    },
    locked_event_ids: [...state.lockedEventIds],
  }));

  const lock = document.createElement("label");
  lock.className = "event-lock";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.lockedEventIds.has(event.event_id);
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.lockedEventIds.add(event.event_id);
    else state.lockedEventIds.delete(event.event_id);
  });
  lock.append(checkbox, document.createTextNode("锁定"));

  controls.append(remove, move, duration, durationButton, lock);
  return controls;
}

function renderBudget(target, summary) {
  const section = document.createElement("section");
  section.className = "budget-card";
  const title = document.createElement("h3");
  title.textContent = "预算拆分";
  const list = document.createElement("div");
  list.className = "budget-list";
  (summary || []).forEach((row) => {
    const item = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = row.label;
    const value = document.createElement("span");
    const parts = [];
    if (Number(row.known_cny) > 0) {
      parts.push(`已知 ¥${Number(row.known_cny).toFixed(0)}`);
    }
    if (Number(row.estimated_cny) > 0) {
      parts.push(`估算 ¥${Number(row.estimated_cny).toFixed(0)}`);
    }
    if (row.unknown) parts.push("另有金额待核验");
    value.textContent = parts.length ? parts.join(" · ") : "金额待核验";
    item.append(label, value);
    list.append(item);
  });
  section.append(title, list);
  target.append(section);
}

function renderAccommodationChoices(target, choices) {
  if (!choices || !Array.isArray(choices.candidates)) return;
  const section = document.createElement("section");
  section.className = "accommodation-card";
  const title = document.createElement("h3");
  title.textContent = "住宿选择";
  const budget = document.createElement("p");
  const budgetParts = [];
  if (Number.isFinite(choices.budget_total_cny)) {
    budgetParts.push(`住宿总预算 ¥${choices.budget_total_cny}`);
  }
  if (Number.isFinite(choices.budget_per_night_cny)) {
    budgetParts.push(`每晚 ¥${choices.budget_per_night_cny}`);
  }
  if (Number.isInteger(choices.rooms)) budgetParts.push(`${choices.rooms}间房`);
  budget.textContent = budgetParts.length
    ? budgetParts.join(" · ")
    : "未填写住宿预算；可在返回修改中补充。";
  const priceNotice = document.createElement("p");
  priceNotice.className = "page-status";
  priceNotice.textContent = choices.price_filter_status === "UNAVAILABLE_NO_PRICE_SOURCE"
    ? "当前未取得真实房价来源，不会冒充预算筛选完成。"
    : "住宿价格已取得实时来源。";
  const list = document.createElement("div");
  list.className = "hotel-choice-list";
  choices.candidates.forEach((hotel) => {
    const item = document.createElement("article");
    const name = document.createElement("strong");
    name.textContent = hotel.name || "住宿候选";
    const meta = document.createElement("p");
    meta.textContent = `${hotel.area || "区域待核验"} · ${
      hotel.price?.status === "UNKNOWN" ? "价格待核验" : hotel.price?.amount_cny
    } · ${hotel.source || "来源待核验"}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button secondary compact";
    button.textContent = choices.current_base?.name === hotel.name
      ? "当前住宿基地"
      : "选择并重算交通";
    button.disabled = choices.current_base?.name === hotel.name;
    button.addEventListener("click", () => selectHotel(hotel.hotel_id));
    item.append(name, meta, button);
    list.append(item);
  });
  section.append(title, budget, priceNotice, list);
  target.append(section);
}

async function selectHotel(hotelId) {
  try {
    const response = await postJson(
      `/api/trips/${state.runId}/evidence`,
      {hotel_id: hotelId},
    );
    showWorkbench(response);
    connectEvents();
  } catch (error) {
    const message = document.createElement("p");
    message.className = "page-status error";
    message.textContent = `住宿选择未应用：${error.message}`;
    $("#result-area").prepend(message);
  }
}

function renderRevisionSummary(target, revision, runRevision = null) {
  if (!revision) return;
  const section = document.createElement("section");
  section.className = "revision-summary";
  const title = document.createElement("h3");
  title.textContent = "本次修改";
  const list = document.createElement("ul");
  const changes = [];
  if (runRevision?.pace) {
    changes.push(
      `旅行节奏已切换为${paceLabels[runRevision.pace] || runRevision.pace}；`
      + "未受影响的日期和顺序继续保留。",
    );
  }
  (revision.changes || []).forEach((change) => {
    if (change.action === "moved_time") {
      changes.push(`Day ${change.day} 出发时间由 ${change.from} 调整到 ${change.to}；${change.reason}`);
    }
  });
  (revision.diff?.attraction_changes || []).forEach((change) => {
    if (change.action === "unchanged") return;
    changes.push(`${change.label}：${change.reason}`);
  });
  (revision.conflicts || []).forEach((conflict) => {
    changes.push(`冲突：${conflict.message || "当前修改与原约束冲突"}`);
  });
  (changes.length ? changes : ["原有主要安排保持不变。"]).forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    list.append(item);
  });
  section.append(title, list);
  target.append(section);
}

function renderRevisionControls(target, plan) {
  const section = document.createElement("section");
  section.className = "revision-controls";
  const title = document.createElement("h3");
  title.textContent = "修改行程";
  const pace = document.createElement("select");
  [
    ["relaxed", "轻松"],
    ["standard", "标准"],
    ["intensive", "紧凑"],
  ].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = state.intent?.pace === value;
    pace.append(option);
  });
  const paceButton = document.createElement("button");
  paceButton.type = "button";
  paceButton.className = "button secondary";
  paceButton.textContent = "切换节奏";
  paceButton.addEventListener("click", () => submitRevision({
    pace: pace.value,
    locked_event_ids: [...state.lockedEventIds],
  }));
  const text = document.createElement("input");
  text.type = "text";
  text.placeholder = "例如：第二天九点以后出发";
  text.setAttribute("aria-label", "自然语言修改行程");
  const textButton = document.createElement("button");
  textButton.type = "button";
  textButton.className = "button primary";
  textButton.textContent = "应用修改";
  textButton.addEventListener("click", () => submitRevision(null, text.value));
  const hint = document.createElement("p");
  hint.textContent = (
    plan.status === "PARTIAL_PLAN_WITH_CONFLICTS"
      ? "当前已有部分有效行程；冲突会保留在结果中供继续调整。"
      : "删除、换天和时长可在每个景点下直接操作。"
  );
  section.append(title, pace, paceButton, text, textButton, hint);
  target.append(section);
}

function blockerKey(blocker, index) {
  return blocker.blocker_id || blocker.code || `blocker-${index}`;
}

function renderBlockers(target, plan) {
  (plan.conditional_blockers || []).forEach((blocker, index) => {
    const key = blockerKey(blocker, index);
    if (state.skippedBlockers.has(key)) return;
    const section = document.createElement("section");
    const title = document.createElement("h3");
    title.textContent = "条件冲突与备选";
    const reason = document.createElement("p");
    reason.textContent = blocker.reason || "仍有一项条件需要补充。";
    const actions = document.createElement("div");
    actions.className = "blocked-actions";
    [
      ["继续查询", continueCurrentRun, "primary"],
      ["手动补充", () => editCurrentRun(true), "secondary"],
      [
        "暂时跳过",
        () => {
          state.skippedBlockers.add(key);
          if (state.lastResponse) showWorkbench(state.lastResponse);
        },
        "ghost",
      ],
    ].forEach(([label, handler, style]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `button ${style}`;
      button.textContent = label;
      button.addEventListener("click", handler);
      actions.append(button);
    });
    section.append(title, reason, actions);
    target.append(section);
  });
}

function formatDurationSeconds(value) {
  if (!Number.isFinite(value)) return "待核验";
  const totalMinutes = Math.round(value / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours ? `${hours}小时${minutes ? `${minutes}分钟` : ""}` : `${minutes}分钟`;
}

function renderGuidedComparison(result, run) {
  const target = $("#result-area");
  target.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("h2");
  title.textContent = run.intent.task_mode === "OPEN_DISCOVERY"
    ? "动态目的地方案"
    : "倾向区域方案比较";
  const badge = document.createElement("span");
  const expected = Number(result.expected_option_count) || Number(
    state.lastResponse?.presentation?.compact_progress?.total_count,
  ) || 0;
  const completed = Array.isArray(result.options) ? result.options.length : 0;
  badge.textContent = run.status === "RUNNING"
    ? `${completed}/${expected} 已完成`
    : "粗粒度核验已结束";
  heading.append(title, badge);
  target.append(heading);

  const cards = document.createElement("div");
  cards.className = "guided-option-grid";
  const selectable = (
    run.status === "COMPLETED"
    && ["OPEN_DISCOVERY", "GUIDED_DISCOVERY"].includes(run.intent.task_mode)
  );
  (result.options || []).forEach((option) => {
    const card = document.createElement("article");
    card.className = "guided-option-card";
    const name = document.createElement("h3");
    name.textContent = option.name || "区域方案";
    const status = document.createElement("p");
    status.className = "guided-option-status";
    status.textContent = planLabels[option.feasibility_status]
      || "仍需继续核验";
    const transport = option.roundtrip_transport || {};
    const rows = [
      ["往返交通", transport.duration_seconds === null
        ? "待核验"
        : formatDurationSeconds(transport.duration_seconds)],
      ["已知费用", Number.isFinite(transport.known_cost_cny)
        ? `¥${Number(transport.known_cost_cny).toLocaleString("zh-CN")}`
        : "待核验"],
      ["可游玩时间", formatDurationSeconds(option.playable_time_seconds)],
      ["当地交通难度", option.local_transport_difficulty?.status === "MISSING"
        ? "待核验"
        : String(option.local_transport_difficulty?.value || "待核验")],
      ["主题", Array.isArray(option.themes) && option.themes.length
        ? option.themes.join("、")
        : "待核验"],
      ["体力", option.physical_intensity || "待核验"],
      ["预算余量", Number.isFinite(option.budget_headroom_after_known_transport_cny)
        ? `扣除已知铁路后 ¥${Number(
          option.budget_headroom_after_known_transport_cny,
        ).toLocaleString("zh-CN")}`
        : "待核验"],
      ["粗计划状态", planLabels[option.coarse_plan_status]
        || "仍需继续核验"],
    ];
    const detail = document.createElement("dl");
    rows.forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label;
      const description = document.createElement("dd");
      description.textContent = value;
      detail.append(term, description);
    });
    const missingTitle = document.createElement("strong");
    missingTitle.textContent = "证据缺失";
    const missing = document.createElement("ul");
    (option.evidence_missing || ["当前仍缺少详细证据。"]).forEach((item) => {
      const row = document.createElement("li");
      row.textContent = item;
      missing.append(row);
    });
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button primary";
    button.textContent = selectable ? "选择该方案并详细规划" : "正在进入详细规划";
    button.disabled = !selectable;
    button.addEventListener("click", () => selectGuidedOption(option.destination_id));
    card.append(name, status, detail, missingTitle, missing, button);
    cards.append(card);
  });
  if (!cards.childElementCount) {
    const waiting = document.createElement("p");
    waiting.className = "guided-waiting";
    waiting.textContent = "查询已开始；第一个候选完成后会立即显示在这里。";
    cards.append(waiting);
  }
  target.append(cards);
  $("#result-status").textContent = selectable
    ? "请选择方案"
    : `${completed}/${expected} 已完成`;
}

function renderPlanningHandoff(handoff) {
  const target = $("#result-area");
  target.replaceChildren();
  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("h2");
  title.textContent = `${handoff.destination_anchor || "已选方案"}详细规划`;
  const badge = document.createElement("span");
  badge.textContent = "沿用比较证据";
  heading.append(title, badge);

  const summary = document.createElement("div");
  summary.className = "result-summary";
  const transport = handoff.roundtrip_transport || {};
  [
    ["往返交通", formatDurationSeconds(transport.duration_seconds)],
    ["已知交通费用", Number.isFinite(transport.known_cost_cny)
      ? `¥${Number(transport.known_cost_cny).toLocaleString("zh-CN")}`
      : "待补充"],
    ["可游玩时间", formatDurationSeconds(handoff.playable_time_seconds)],
    ["当前状态", planLabels[handoff.feasibility_status] || "继续核验中"],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    const name = document.createElement("span");
    name.textContent = label;
    const content = document.createElement("strong");
    content.textContent = value;
    row.append(name, content);
    summary.append(row);
  });

  const railway = handoff.railway || {};
  const facts = document.createElement("section");
  facts.className = "guidance-card";
  const factsTitle = document.createElement("h3");
  factsTitle.textContent = "已取得的交通与住宿";
  const factsList = document.createElement("ul");
  [
    railway.outbound
      ? `去程 ${railway.outbound.train_code}：${eventClock(
        railway.outbound.departure_at,
      )}–${eventClock(railway.outbound.arrival_at)}`
      : "去程铁路待核验",
    railway.return
      ? `返程 ${railway.return.train_code}：${eventClock(
        railway.return.departure_at,
      )}–${eventClock(railway.return.arrival_at)}`
      : "返程铁路待核验",
    handoff.hotel_area?.name
      ? `住宿片区：${handoff.hotel_area.name}（具体酒店未选择）`
      : "住宿片区待核验",
  ].forEach((value) => {
    const row = document.createElement("li");
    row.textContent = value;
    factsList.append(row);
  });
  facts.append(factsTitle, factsList);

  const days = document.createElement("div");
  days.className = "guidance-grid progressive-days";
  (handoff.days || []).forEach((day) => {
    const card = document.createElement("section");
    const dayTitle = document.createElement("h3");
    dayTitle.textContent = `Day ${day.day} · ${day.date}`;
    const list = document.createElement("ul");
    const values = [];
    if (day.day === 1 && railway.outbound) {
      values.push(`跨城铁路：${railway.outbound.origin_station} → ${railway.outbound.destination_station}`);
      values.push("抵达缓冲与入住手续将随详细排程生成");
    }
    if (day.day === (handoff.days || []).length && railway.return) {
      values.push(`返程铁路：${railway.return.origin_station} → ${railway.return.destination_station}`);
      values.push("退房与候车缓冲将随详细排程生成");
    }
    (handoff.attractions || []).forEach((attraction, index) => {
      const assignedDay = Math.min(index + 2, (handoff.days || []).length);
      if (assignedDay === day.day) {
        values.push(`${attraction.name}：${
          attraction.features?.join("、") || "特色待核验"
        }（时间待排）`);
      }
    });
    (values.length ? values : ["当天内容正在逐项补入"]).forEach((value) => {
      const row = document.createElement("li");
      row.textContent = value;
      list.append(row);
    });
    card.append(dayTitle, list);
    days.append(card);
  });

  const routes = document.createElement("section");
  routes.className = "guidance-card";
  const routesTitle = document.createElement("h3");
  routesTitle.textContent = "景点间交通";
  const routesList = document.createElement("ul");
  (handoff.local_transit || []).forEach((route) => {
    const row = document.createElement("li");
    row.textContent = `${route.from} → ${route.to}：${
      formatDurationSeconds(route.duration_seconds)
    } · ${Number.isFinite(route.distance_meters)
      ? `${(route.distance_meters / 1000).toFixed(1)}公里`
      : "距离待核验"} · ${Number.isFinite(route.fare?.amount_cny)
      ? `约 ¥${route.fare.amount_cny}`
      : "费用待核验"}`;
    routesList.append(row);
  });
  if (!routesList.childElementCount) {
    const waiting = document.createElement("li");
    waiting.textContent = "当地交通正在查询，铁路和已取得内容不会被清空。";
    routesList.append(waiting);
  }
  routes.append(routesTitle, routesList);
  target.append(heading, summary, facts, days, routes);
  $("#result-status").textContent = "正在补充详细规划";
}

function renderCompleted(result, presentation, run) {
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

  const lifecycle = document.createElement("p");
  lifecycle.className = "page-status";
  if (run.status === "RUNNING") {
    lifecycle.textContent = "正在生成新版本；当前继续显示上一版行程。";
  } else if (run.status === "BLOCKED" || run.status === "FAILED") {
    const reasons = {
      RAILWAY_ACTION_STALLED: "铁路查询超过30秒没有新进展",
      MAP_ACTION_STALLED: "当地交通查询超过30秒没有新进展",
      WEB_EVIDENCE_REQUIRED: "仍需补充网页证据",
      USER_INPUT_REQUIRED: "仍需用户补充信息",
    };
    lifecycle.classList.add("error");
    lifecycle.textContent = `本次修改未切换：${
      reasons[run.error_code] || "新版本未能完成"
    }；以下继续显示上一版行程。`;
  }

  const summary = document.createElement("div");
  summary.className = "result-summary";
  const statements = [
    ["可发布", plan.publishable === true ? "是" : "否"],
    [
      "详细行程",
      presentation.detailed_itinerary_ready
        ? "已满足展示条件"
        : `继续补充（当前 ${presentation.attraction_count || 0} 个景点、${
          presentation.local_transit_count || 0
        } 段当地交通）`,
    ],
    [
      "行程规模",
      `${presentation.day_count || 0} 天 · ${
        presentation.event_count || 0
      } 个事件`,
    ],
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
  const evidenceGrid = document.createElement("div");
  evidenceGrid.className = "guidance-grid";
  renderEvidenceStatuses(evidenceGrid, presentation);
  renderBudget(evidenceGrid, presentation.budget_summary);
  renderAccommodationChoices(
    evidenceGrid,
    presentation.accommodation_choices,
  );

  const timeline = document.createElement("div");
  timeline.className = "guidance-grid";
  renderLocalTransitReferences(timeline, plan);
  renderTimeline(timeline, plan);
  renderBlockers(timeline, plan);
  renderRevisionSummary(timeline, plan.revision, run.revision);
  renderRevisionControls(timeline, plan);

  const actions = document.createElement("div");
  actions.className = "blocked-actions";
  const continueButton = document.createElement("button");
  continueButton.type = "button";
  continueButton.className = "button primary";
  continueButton.textContent = "继续完善行程";
  continueButton.addEventListener("click", continueCurrentRun);
  actions.append(continueButton);

  target.append(heading);
  if (lifecycle.textContent) target.append(lifecycle);
  target.append(summary, evidenceGrid, timeline, actions);
  $("#result-status").textContent = presentation.detailed_itinerary_ready
    ? "详细行程"
    : "条件化粗计划";
}

function renderResult(run, presentation = {}) {
  const result = run.result;
  if (!result) {
    const progress = presentation.compact_progress;
    if (progress?.kind === "guided_comparison") {
      $("#result-column").classList.remove("hidden");
      $("#workbench").classList.add("has-result");
      renderGuidedComparison(
        {
          stage: "guided_discovery",
          expected_option_count: progress.total_count,
          options: progress.partial_options || [],
        },
        run,
      );
      return;
    }
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
  if (
    ["open_discovery", "guided_discovery"].includes(result.stage)
    && run.intent.task_mode === "DIRECT_PLAN"
    && presentation.planning_handoff
  ) {
    renderPlanningHandoff(presentation.planning_handoff);
    return;
  }
  if (["open_discovery", "guided_discovery"].includes(result.stage)) {
    renderGuidedComparison(result, run);
    return;
  }
  const plan = result.plan || {};
  const missing = plan.missing || result.context?.missing_domains || [];
  const conflicting = plan.conflicting || result.context?.conflicting_domains || [];
  const hasReadablePlan = Array.isArray(plan.days) && plan.days.length > 0;
  if (
    ((run.status === "FAILED" || run.status === "BLOCKED")
      && !hasReadablePlan)
    || plan.status === "CONTEXT_INCOMPLETE"
    || ((!Array.isArray(plan.days) || !plan.days.length)
      && (missing.length || conflicting.length))
  ) {
    renderInsufficient(result, run);
    return;
  }
  renderCompleted(result, presentation, run);
}

async function submitRevision(revision, text = null) {
  try {
    const payload = text === null ? {revision} : {text};
    const response = await postJson(
      `/api/trips/${state.runId}/revisions`,
      payload,
    );
    showWorkbench(response);
  } catch (error) {
    const message = document.createElement("p");
    message.className = "page-status error";
    message.textContent = `修改未应用：${error.message}`;
    $("#result-area").prepend(message);
  }
}

function editCurrentRun(focusMissing) {
  showEditableIntent(state.intent, "revise_existing");
  if (focusMissing) {
    const missing = missingFields(state.intent);
    const field = missing[0] || "origin";
    document.querySelector(`[name="${field}"]`)?.focus();
  }
}

function skipVisibleBlockers() {
  const blockers = state.lastResponse?.run?.result?.plan?.conditional_blockers;
  (Array.isArray(blockers) ? blockers : []).forEach((blocker, index) => {
    state.skippedBlockers.add(blockerKey(blocker, index));
  });
  if (state.lastResponse) showWorkbench(state.lastResponse);
  $("#result-status").textContent = "已暂时收起待完善项";
}

async function selectGuidedOption(destinationId) {
  try {
    const selected = await postJson(
      `/api/trips/${state.runId}/candidates/${encodeURIComponent(destinationId)}/select`,
      {},
    );
    showWorkbench(selected);
    connectEvents();
    const progressed = await postJson(
      `/api/trips/${state.runId}/execute`,
      {},
    );
    showWorkbench(progressed);
    if (progressed.run.status === "RUNNING" && !state.eventSource) {
      connectEvents();
    }
  } catch (error) {
    $("#result-status").textContent = "进入详细规划失败";
    const message = document.createElement("p");
    message.className = "page-status error";
    message.textContent = error.message;
    $("#result-area").append(message);
  }
}

async function continueCurrentRun() {
  try {
    const response = await postJson(
      `/api/trips/${state.runId}/execute`,
      {},
    );
    showWorkbench(response);
    if (response.run.status === "RUNNING") connectEvents();
  } catch (error) {
    $("#result-status").textContent = "继续完善失败";
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
    `/api/trips/${state.runId}/events?after=${state.lastSequence}`,
  );
  state.eventSource = source;
  source.addEventListener("agent_event", async () => {
    try {
      const response = await getJson(`/api/trips/${state.runId}`);
      showWorkbench(response);
      if (
        ["COMPLETED", "BLOCKED", "FAILED"].includes(response.run.status)
      ) {
        source.close();
        state.eventSource = null;
      }
    } catch (error) {
      $("#result-status").textContent = "状态更新失败";
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
    if (state.confirmationMode === "revise_existing") {
      const revised = await postJson(
        `/api/trips/${state.runId}/revisions`,
        {intent: correctedIntent},
      );
      showWorkbench(revised);
      if (revised.run.status === "RUNNING") connectEvents();
      return;
    }
    const confirmed = await postJson(
      `/api/trips/${state.runId}/confirm`,
      {intent: correctedIntent},
    );
    showWorkbench(confirmed);
    connectEvents();
    await postJson(`/api/trips/${state.runId}/execute`, {});
  } catch (error) {
    setStatus(status, error.message, true);
    button.disabled = false;
  }
}

async function pollCurrentRun() {
  if (!state.pinnedRunId) return;
  if (state.confirmationOpen) return;
  try {
    const path = `/api/trips/${encodeURIComponent(state.pinnedRunId)}`;
    const response = await getJson(path);
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

async function createNewTrip() {
  const input = $("#new-trip-text");
  const button = $("#new-trip-button");
  const text = input.value.trim();
  if (!text) {
    setStatus($("#landing-status"), "请先输入这次旅行需求。", true);
    return;
  }
  button.disabled = true;
  setStatus($("#landing-status"), "正在提取本次旅行条件…");
  try {
    const response = await postJson("/api/trips", {text});
    showConfirmation(response);
  } catch (error) {
    setStatus($("#landing-status"), error.message, true);
    button.disabled = false;
  }
}

async function loadHomeHistory() {
  const target = $("#history-list");
  try {
    const response = await getJson("/api/trips");
    target.replaceChildren();
    const runs = Array.isArray(response.runs) ? response.runs : [];
    runs.slice(0, 12).forEach((run) => {
      const link = document.createElement("a");
      link.className = "history-item";
      link.href = `/?run_id=${encodeURIComponent(run.run_id)}`;
      const title = document.createElement("strong");
      title.textContent = [run.origin, run.destination].filter(Boolean).join(" → ")
        || (Array.isArray(run.themes) && run.themes.length ? run.themes.join("、") : "待确认旅行任务");
      const meta = document.createElement("span");
      meta.textContent = `${formatDateTime(run.created_at)} · ${
        modeLabels[run.task_mode] || "旅行规划"
      }`;
      link.append(title, meta);
      target.append(link);
    });
    if (!runs.length) {
      const empty = document.createElement("p");
      empty.textContent = "还没有历史行程。";
      target.append(empty);
    }
    const continueLink = $("#continue-last-link");
    if (response.continue_run_id) {
      continueLink.href = `/?run_id=${encodeURIComponent(response.continue_run_id)}`;
      continueLink.classList.remove("hidden");
    } else {
      continueLink.classList.add("hidden");
    }
  } catch (error) {
    setStatus($("#landing-status"), "历史行程暂时无法读取。", true);
  }
}

$("#confirm-button").addEventListener("click", confirmAndExecute);
$("#intent-form").addEventListener("input", refreshConfirmationGate);
$("#intent-form").addEventListener("change", refreshConfirmationGate);
$("#edit-button").addEventListener("click", () => editCurrentRun(false));
$("#new-trip-button").addEventListener("click", createNewTrip);
if (state.pinnedRunId) {
  pollCurrentRun();
  state.pollTimer = window.setInterval(pollCurrentRun, 1000);
} else {
  loadHomeHistory();
}
