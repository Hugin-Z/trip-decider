const state = {
  draftRevision: 0,
  submittedDraft: null,
  submittedFingerprint: null,
  discoveryRequest: null,
  recommendations: [],
  detail: null,
  localPlanRequest: null,
  completePlan: null,
  resultsStale: false,
  clientConfig: null,
  map: null,
  mapMarkers: [],
  mapRoutes: [],
};

const paceProfiles = {
  relaxed: {
    physicalLevel: "low",
    earlyStart: false,
    nightActivity: false,
    transportTolerance: "low",
    depthPreference: "deep",
    maxAttractions: 1,
    earliestDeparture: "08:00",
    latestReturn: "19:00",
    lunchMinutes: 75,
    dinnerMinutes: 75,
    interEventBuffer: 20,
    arrivalBuffer: 45,
    railWait: 60,
    middayRest: 45,
    maxDailyActive: 650,
    maxContinuous: 90,
    maxTransfers: 1,
    defaultNight: false,
    dropLowPriority: true,
  },
  standard: {
    physicalLevel: "moderate",
    earlyStart: true,
    nightActivity: true,
    transportTolerance: "moderate",
    depthPreference: "balanced",
    maxAttractions: 2,
    earliestDeparture: "07:15",
    latestReturn: "20:30",
    lunchMinutes: 60,
    dinnerMinutes: 60,
    interEventBuffer: 10,
    arrivalBuffer: 30,
    railWait: 45,
    middayRest: 30,
    maxDailyActive: 720,
    maxContinuous: 120,
    maxTransfers: 2,
    defaultNight: true,
    dropLowPriority: true,
  },
  intensive: {
    physicalLevel: "high",
    earlyStart: true,
    nightActivity: true,
    transportTolerance: "high",
    depthPreference: "highlights",
    maxAttractions: 3,
    earliestDeparture: "06:30",
    latestReturn: "22:00",
    lunchMinutes: 60,
    dinnerMinutes: 60,
    interEventBuffer: 10,
    arrivalBuffer: 30,
    railWait: 45,
    middayRest: 30,
    maxDailyActive: 840,
    maxContinuous: 180,
    maxTransfers: 3,
    defaultNight: true,
    dropLowPriority: false,
  },
};

const $ = (selector) => document.querySelector(selector);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function setStatus(node, text, error = false) {
  node.textContent = text;
  node.classList.toggle("error", error);
}

function selectedValues(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)]
    .map((input) => input.value);
}

function travelWindow() {
  const earliestText = $("#earliest-departure-at").value;
  const latestText = $("#latest-return-at").value;
  if (!earliestText || !latestText) return null;
  const earliest = new Date(earliestText);
  const latest = new Date(latestText);
  const milliseconds = latest.getTime() - earliest.getTime();
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) return null;
  return {
    earliestDepartureAt: earliestText,
    latestReturnAt: latestText,
    durationHours: milliseconds / 3600000,
    days: milliseconds / 86400000,
  };
}

function updateDurationReadout() {
  const output = $("#available-duration");
  const window = travelWindow();
  if (!window) {
    output.textContent = "时间窗无效或尚未完整填写";
    output.classList.add("invalid");
    return;
  }
  const days = Math.floor(window.durationHours / 24);
  const hours = Math.round(window.durationHours - days * 24);
  output.textContent = `${window.durationHours.toFixed(1)} 小时（${days} 天 ${hours} 小时）`;
  output.classList.remove("invalid");
}

function readDiscoveryForm({validate = true} = {}) {
  const window = travelWindow();
  const themes = selectedValues("theme");
  const pace = document.querySelector('input[name="pace"]:checked')?.value || "";
  const transports = selectedValues("transport");
  if (validate && !window) throw new Error("请填写有效的最早出发和最晚返回时间。");
  if (validate && !themes.length) throw new Error("请至少选择一个旅行主题。");
  if (validate && !pace) throw new Error("请选择旅行节奏。");
  if (validate && !transports.length) throw new Error("请至少选择一种交通偏好。");
  return {
    intent_text: $("#intent-text").value.trim(),
    origin: $("#origin").value.trim(),
    earliest_departure_at: window?.earliestDepartureAt || "",
    latest_return_at: window?.latestReturnAt || "",
    total_budget: Number($("#budget").value),
    travelers: Number($("#travelers").value),
    themes,
    pace,
    transport_preferences: transports,
  };
}

function requestFingerprint(request) {
  return JSON.stringify(request);
}

function markResultsStale() {
  if (!state.submittedDraft) return;
  const current = readDiscoveryForm({validate: false});
  const stale = requestFingerprint(current) !== state.submittedFingerprint;
  state.resultsStale = stale;
  $("#stale-results").classList.toggle("hidden", !stale);
  $("#plan-stale-results").classList.toggle("hidden", !stale);
  $("#discover-result-content").classList.toggle("is-stale", stale);
}

function updateProgress(containerSelector, statuses, activeId = null) {
  const container = $(containerSelector);
  container?.classList.remove("hidden");
  for (const node of container?.querySelectorAll("li") || []) {
    const identifier = node.dataset.progress || node.dataset.planProgress;
    const status = identifier === activeId
      ? "active"
      : statuses?.find((item) => item.id === identifier)?.status || "not_started";
    node.className = status;
  }
}

function progressSnapshot(completedIds = [], activeId = null) {
  const ids = ["understand", "intercity", "local_route", "facts", "plan"];
  return ids.map((id) => ({
    id,
    status: completedIds.includes(id)
      ? "completed"
      : (id === activeId ? "active" : "not_started"),
  }));
}

async function postJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) {
    const message = result.message || result.error || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return result;
}

async function getJson(path) {
  const response = await fetch(path, {headers: {"Accept": "application/json"}});
  const result = await response.json();
  if (!response.ok) {
    throw new Error(result.message || result.error || `HTTP ${response.status}`);
  }
  return result;
}

function setRuntimeBadge(selector, configured, text) {
  const node = $(selector);
  node.textContent = text;
  node.classList.toggle("unconfigured", !configured);
}

async function loadClientConfiguration() {
  try {
    state.clientConfig = await getJson("/api/client-config");
    setRuntimeBadge(
      "#ai-status",
      state.clientConfig.ai.configured,
      state.clientConfig.ai.display,
    );
    setRuntimeBadge(
      "#map-config-status",
      state.clientConfig.amap_js.configured,
      state.clientConfig.amap_js.display,
    );
    setRuntimeBadge(
      "#map-runtime-status",
      state.clientConfig.amap_js.configured,
      state.clientConfig.amap_js.display,
    );
    if (!state.clientConfig.amap_js.configured) {
      showMapState(
        "地图未配置",
        `缺少 ${state.clientConfig.amap_js.missing.join("、")}；不会显示假地图。`,
        true,
      );
    }
  } catch (error) {
    setRuntimeBadge("#ai-status", false, "AI配置读取失败");
    setRuntimeBadge("#map-config-status", false, "地图配置读取失败");
    showMapState("地图配置读取失败", error.message, true);
  }
}

function showMapState(title, message, error = false) {
  const node = $("#map-state");
  node.replaceChildren(
    element("strong", "", title),
    element("p", "", message),
  );
  node.classList.remove("hidden");
  node.classList.toggle("error", error);
}

let amapLoading = null;
function loadAmap() {
  if (window.AMap) return Promise.resolve(window.AMap);
  if (amapLoading) return amapLoading;
  const config = state.clientConfig?.amap_js;
  if (!config?.configured) {
    return Promise.reject(new Error("地图未配置"));
  }
  amapLoading = new Promise((resolve, reject) => {
    window._AMapSecurityConfig = {
      securityJsCode: config.security_js_code,
    };
    const script = document.createElement("script");
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(config.key)}`;
    script.async = true;
    script.onload = () => {
      if (window.AMap) resolve(window.AMap);
      else reject(new Error("高德 JS API 未返回 AMap 对象"));
    };
    script.onerror = () => reject(new Error("高德 JS API 加载失败"));
    document.head.append(script);
  });
  return amapLoading;
}

function planLocations(plan) {
  const locations = [];
  for (const day of plan.days || []) {
    for (const activity of day.activities || []) {
      const location = activity.location;
      if (
        location
        && Number.isFinite(Number(location.longitude))
        && Number.isFinite(Number(location.latitude))
      ) {
        locations.push({
          dayNumber: day.day_number,
          name: activity.name,
          longitude: Number(location.longitude),
          latitude: Number(location.latitude),
        });
      }
    }
  }
  return locations;
}

async function renderAmapPlan(plan) {
  const locations = planLocations(plan);
  if (!locations.length) {
    showMapState(
      "尚无可绘制地点",
      "计划结果没有带坐标的已解析 POI；地图不会使用文字标签伪造标记。",
    );
    return;
  }
  try {
    const AMap = await loadAmap();
    if (!state.map) {
      state.map = new AMap.Map("amap-container", {
        zoom: 10,
        viewMode: "2D",
      });
    } else {
      state.map.clearMap();
    }
    state.mapMarkers = locations.map((location, index) => {
      const marker = new AMap.Marker({
        position: [location.longitude, location.latitude],
        title: location.name,
        label: {
          content: `Day ${location.dayNumber} · ${index + 1}`,
          direction: "top",
        },
      });
      marker.on("click", () => {
        const info = new AMap.InfoWindow({
          content: `<div>${escapeHtml(location.name)}<br>Day ${location.dayNumber}</div>`,
          offset: new AMap.Pixel(0, -28),
        });
        info.open(state.map, marker.getPosition());
      });
      return marker;
    });
    state.map.add(state.mapMarkers);
    state.map.setFitView(state.mapMarkers, false, [48, 48, 48, 48]);
    $("#map-state").classList.add("hidden");

    const routeMode = state.localPlanRequest?.transport_mode || "driving";
    const byDay = new Map();
    locations.forEach((location) => {
      if (!byDay.has(location.dayNumber)) byDay.set(location.dayNumber, []);
      byDay.get(location.dayNumber).push(location);
    });
    const pluginName = routeMode === "walking" ? "AMap.Walking" : "AMap.Driving";
    AMap.plugin(pluginName, () => {
      for (const dayLocations of byDay.values()) {
        for (let index = 1; index < dayLocations.length; index += 1) {
          const previous = dayLocations[index - 1];
          const current = dayLocations[index];
          const route = routeMode === "walking"
            ? new AMap.Walking({map: state.map, hideMarkers: true})
            : new AMap.Driving({map: state.map, hideMarkers: true});
          route.search(
            new AMap.LngLat(previous.longitude, previous.latitude),
            new AMap.LngLat(current.longitude, current.latitude),
            () => {},
          );
          state.mapRoutes.push(route);
        }
      }
    });
  } catch (error) {
    showMapState("真实地图加载失败", error.message, true);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function summaryChip(text) {
  return element("span", "summary-chip", text);
}

function renderRequestSummary(request) {
  const container = $("#request-summary");
  container.replaceChildren(
    summaryChip(`${request.origin} 出发`),
    summaryChip(`最早 ${request.earliest_departure_at}`),
    summaryChip(`最晚 ${request.latest_return_at}`),
    summaryChip(`可用 ${Number(request.available_duration_hours).toFixed(1)} 小时`),
    summaryChip(`总预算 ¥${request.total_budget}`),
    summaryChip(`${request.travelers} 人`),
    summaryChip(request.themes.join(" · ")),
    summaryChip(`${request.pace}节奏`),
    summaryChip(request.transport_preferences.join(" / ")),
  );
}

function metric(label, value, pending = false) {
  const row = element("div", "metric");
  row.append(element("span", "", label));
  const strong = element("strong", pending ? "pending" : "", value);
  row.append(strong);
  return row;
}

function durationText(seconds) {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) {
    return "UNKNOWN";
  }
  const minutes = Math.round(Number(seconds) / 60);
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return `${hours}小时${String(remainder).padStart(2, "0")}分`;
}

function riskText(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && value.stage) {
    return `数据获取阶段：${value.stage}`;
  }
  return "存在尚未分类的真实数据风险";
}

function destinationCard(card, index) {
  const article = element(
    "article",
    `destination-card${index === 0 ? " featured" : ""}`,
  );
  const topline = element("div", "card-topline");
  topline.append(
    element("span", "rank-badge", String(index + 1).padStart(2, "0")),
    element("span", "confidence", `数据可信度：${card.confidence}`),
  );
  const title = element("h3", "", card.name);
  const region = element("p", "region", card.region_label);
  const summary = element("p", "card-summary", card.summary);
  const tags = element("div", "tag-row");
  card.themes.forEach((theme) => tags.append(element("span", "tag", theme)));
  const metrics = element("div", "metric-list");
  const transportKnown = card.roundtrip_transport_duration_seconds !== null
    && Number.isFinite(Number(card.roundtrip_transport_duration_seconds));
  const costKnown = card.roundtrip_transport_cost_cny !== null
    && Number.isFinite(Number(card.roundtrip_transport_cost_cny));
  metrics.append(
    metric(
      "建议天数",
      `${card.suggested_days.min}–${card.suggested_days.max} 天`,
    ),
    metric(
      "往返交通时间",
      transportKnown
        ? durationText(card.roundtrip_transport_duration_seconds)
        : card.intercity_time.status,
      !transportKnown,
    ),
    metric(
      "已知交通费用",
      costKnown
        ? `¥${Number(card.roundtrip_transport_cost_cny).toFixed(1)}`
        : card.budget_range.status,
      !costKnown,
    ),
    metric("推荐进入门户", card.recommended_gateway || "UNKNOWN", !card.recommended_gateway),
    metric(
      "铁路快照",
      card.rail_snapshot?.display || "UNKNOWN · 未取得可用铁路快照",
      card.rail_snapshot?.status !== "LIVE",
    ),
    metric("可行状态", card.feasibility_status, card.feasibility_status === "UNKNOWN"),
    metric("体力强度", card.intensity),
    metric("季节适配", card.season_fit),
  );
  const reasons = element("ul", "reason-list");
  card.match_reasons.forEach((reason) => {
    reasons.append(element("li", "", reason));
  });
  const missing = element(
    "p",
    "card-missing",
    `缺失：${card.missing_fields.join("、")}`,
  );
  const feasibility = element("div", "feasibility-note");
  const conditionList = element("ul", "reason-list");
  card.feasibility_conditions.forEach((condition) => {
    conditionList.append(element("li", "", condition));
  });
  const riskList = element("ul", "reason-list risks");
  card.feasibility_risks.forEach((risk) => {
    riskList.append(element("li", "", riskText(risk)));
  });
  feasibility.append(
    element("strong", "", "条件与风险"),
    conditionList,
    riskList,
  );
  const choose = element(
    "button",
    "button secondary full",
    `选择 ${card.name}，查看规划结构`,
  );
  choose.type = "button";
  choose.addEventListener("click", () => selectDestination(card.destination_id));
  article.append(
    topline,
    title,
    region,
    summary,
    tags,
    metrics,
    reasons,
    feasibility,
    missing,
    choose,
  );
  return article;
}

function renderRecommendations(result) {
  state.discoveryRequest = result.request;
  state.recommendations = result.preliminary_candidates;
  state.detail = null;
  state.localPlanRequest = null;
  state.completePlan = null;
  state.resultsStale = false;
  renderRequestSummary(result.request);
  const grid = $("#destination-grid");
  grid.replaceChildren(
    ...result.preliminary_candidates.map(
      (card, index) => destinationCard(card, index),
    ),
  );
  $("#discover-empty").classList.add("hidden");
  $("#discover-result-content").classList.remove("hidden", "is-stale");
  $("#stale-results").classList.add("hidden");
  $("#plan-section").classList.add("hidden");
  $("#discover-stage-pill").classList.add("active");
  $("#plan-stage-pill").classList.remove("active");
  updateProgress("#query-progress", result.progress || []);
}

function applyAIInterpretation(result) {
  if (result.status !== "COMPLETED") return;
  const currentThemes = selectedValues("theme");
  if (!currentThemes.length) {
    document.querySelectorAll('input[name="theme"]').forEach((input) => {
      input.checked = result.themes.includes(input.value);
    });
  }
  if (!document.querySelector('input[name="pace"]:checked') && result.pace) {
    const pace = document.querySelector(
      `input[name="pace"][value="${CSS.escape(result.pace)}"]`,
    );
    if (pace) pace.checked = true;
  }
  if (!selectedValues("transport").length) {
    document.querySelectorAll('input[name="transport"]').forEach((input) => {
      input.checked = result.transport_preferences.includes(input.value);
    });
  }
}

function assertRequestConsistency(submitted, normalized) {
  const scalarPairs = [
    ["origin", submitted.origin, normalized.origin],
    ["earliest_departure_at", submitted.earliest_departure_at, normalized.earliest_departure_at],
    ["latest_return_at", submitted.latest_return_at, normalized.latest_return_at],
    ["total_budget", submitted.total_budget, normalized.total_budget],
    ["travelers", submitted.travelers, normalized.travelers],
    ["pace", submitted.pace, normalized.pace],
  ];
  for (const [field, expected, actual] of scalarPairs) {
    if (expected !== actual) {
      throw new Error(`结果条件与已提交请求不一致：${field}`);
    }
  }
  for (const field of ["themes", "transport_preferences"]) {
    if (JSON.stringify(submitted[field]) !== JSON.stringify(normalized[field])) {
      throw new Error(`结果条件与已提交请求不一致：${field}`);
    }
  }
}

async function submitDiscovery(event) {
  event?.preventDefault();
  const button = $("#discover-form button[type='submit']");
  const status = $("#form-status");
  button.disabled = true;
  $("#discover-empty").classList.add("hidden");
  $("#query-progress").classList.remove("hidden");
  updateProgress("#query-progress", progressSnapshot([], "understand"), "understand");
  setStatus(status, "正在理解需求…");
  try {
    let draft = readDiscoveryForm({validate: false});
    let interpretationStatus = "NOT_REQUESTED";
    if (draft.intent_text) {
      const interpretation = await postJson("/api/interpret-intent", {
        intent_text: draft.intent_text,
      });
      interpretationStatus = interpretation.status;
      applyAIInterpretation(interpretation);
      if (interpretation.status === "AI_NOT_CONFIGURED") {
        setStatus(
          status,
          "AI未配置；将使用你明确填写的结构化条件，不生成AI解释。",
        );
      }
    }
    draft = readDiscoveryForm();
    state.draftRevision += 1;
    updateProgress(
      "#query-progress",
      progressSnapshot(["understand"], "intercity"),
      "intercity",
    );
    setStatus(status, "正在验证跨城交通并计算候选…");
    const result = await postJson("/api/discover", {
      ...draft,
      ai_interpretation_status: interpretationStatus,
    });
    assertRequestConsistency(draft, result.request);
    state.submittedDraft = JSON.parse(JSON.stringify(draft));
    state.submittedFingerprint = requestFingerprint(draft);
    renderRecommendations(result);
    setStatus(
      status,
      `已返回 ${result.preliminary_candidates.length} 个初步候选；现实可行性仍需动态证据验证。`,
    );
  } catch (error) {
    setStatus(status, error.message, true);
    $("#discover-empty").classList.toggle(
      "hidden",
      Boolean(state.discoveryRequest),
    );
    updateProgress(
      "#query-progress",
      [{id: "understand", status: "failed"}],
    );
  } finally {
    button.disabled = false;
  }
}

function plannerDefaultField(id, label, value, type = "number") {
  const wrapper = element("label", "stacked-label", label);
  const input = element("input");
  input.id = id;
  input.type = type;
  input.value = String(value);
  if (type === "number") {
    const numericRules = {
      "max-attractions-per-day": ["1", "6", "1"],
      "max-daily-active-minutes": ["240", "960", "15"],
      "max-continuous-attraction-minutes": ["45", "240", "15"],
      "max-transfers-per-day": ["0", "6", "1"],
    };
    const [minimum, maximum, step] = numericRules[id] || ["5", "240", "5"];
    input.min = minimum;
    input.max = maximum;
    input.step = step;
  }
  wrapper.append(input);
  return wrapper;
}

function selectControl(id, label, options, selected) {
  const wrapper = element("label", "stacked-label", label);
  const select = element("select");
  select.id = id;
  options.forEach(([value, text]) => {
    const option = element("option", "", text);
    option.value = value;
    option.selected = value === selected;
    select.append(option);
  });
  wrapper.append(select);
  return wrapper;
}

function checkboxControl(id, label, checked) {
  const wrapper = element("label", "checkbox-control");
  const input = element("input");
  input.id = id;
  input.type = "checkbox";
  input.checked = checked;
  wrapper.append(input, element("span", "", label));
  return wrapper;
}

function applyPaceProfileToControls(pace) {
  if (pace === "custom") return;
  const profile = paceProfiles[pace];
  $("#physical-level").value = profile.physicalLevel;
  $("#early-start").checked = profile.earlyStart;
  $("#night-activity").checked = profile.nightActivity;
  $("#transport-tolerance").value = profile.transportTolerance;
  $("#depth-preference").value = profile.depthPreference;
  $("#max-attractions-per-day").value = profile.maxAttractions;
  $("#earliest-departure").value = profile.earliestDeparture;
  $("#latest-return").value = profile.latestReturn;
  $("#lunch-minutes").value = profile.lunchMinutes;
  $("#dinner-minutes").value = profile.dinnerMinutes;
  $("#inter-event-buffer-minutes").value = profile.interEventBuffer;
  $("#arrival-buffer-minutes").value = profile.arrivalBuffer;
  $("#rail-wait-minutes").value = profile.railWait;
  $("#midday-rest-minutes").value = profile.middayRest;
  $("#max-daily-active-minutes").value = profile.maxDailyActive;
  $("#max-continuous-attraction-minutes").value = profile.maxContinuous;
  $("#max-transfers-per-day").value = profile.maxTransfers;
  $("#default-night-activity").checked = profile.defaultNight;
  $("#drop-low-priority").checked = profile.dropLowPriority;
}

function conditionPanel(detail) {
  const panel = element("div", "panel");
  panel.append(element("h3", "", detail.destination.region_label));
  const list = element("div", "condition-list");
  const values = [
    ["出发地", detail.request.origin],
    ["最早出发", detail.request.earliest_departure_at || detail.request.approximate_start_date],
    ["最晚返回", detail.request.latest_return_at || "UNKNOWN"],
    [
      "可用时长",
      detail.request.available_duration_hours
        ? `${Number(detail.request.available_duration_hours).toFixed(1)} 小时`
        : `${detail.request.days} 天`,
    ],
    ["预算", `¥${detail.request.total_budget}`],
    ["人数", `${detail.request.travelers} 人`],
    ["节奏", detail.request.pace],
    ["交通偏好", detail.request.transport_preferences.join(" / ")],
  ];
  values.forEach(([label, value]) => {
    const row = element("div", "condition-row");
    row.append(element("span", "", label), element("strong", "", value));
    list.append(row);
  });
  panel.append(list);
  const note = element(
    "p",
    "muted",
    "以上内容来自本次已提交请求。修改 Discover 表单后，本计划会立即标记失效。",
  );
  panel.append(note);
  return panel;
}

function renderRouteDiagram(detail) {
  if (!state.clientConfig?.amap_js.configured) {
    showMapState(
      "地图未配置",
      "需要独立的 AMAP_JS_API_KEY 与 AMAP_JS_SECURITY_CODE；后端 Web 服务 Key 不会发送到前端。",
      true,
    );
    return;
  }
  showMapState(
    "正在等待真实地点坐标",
    `已选择 ${detail.destination.region_label}。当地地点解析完成后显示真实 POI 与每日路线。`,
  );
}

function renderModules(detail) {
  const moduleGrid = $("#module-grid");
  const selected = state.recommendations.find(
    (candidate) => candidate.destination_id === detail.destination.id,
  );
  const modules = selected
    ? [
        {
          title: "跨城可行状态",
          value: selected.feasibility_status,
        },
        {
          title: "推荐门户",
          value: selected.recommended_gateway || "未取得真实门户",
        },
        {
          title: "往返交通时间",
          value: selected.roundtrip_transport_duration_seconds === null
            ? "真实交通时间未取得"
            : durationText(selected.roundtrip_transport_duration_seconds),
        },
        {
          title: "已知交通费用",
          value: selected.roundtrip_transport_cost_cny === null
            ? "真实交通费用未取得"
            : moneyText(selected.roundtrip_transport_cost_cny),
        },
      ]
    : [];
  moduleGrid.replaceChildren(
    ...modules.map((module) => {
      const card = element("div", "module-card");
      card.append(
        element("h4", "", module.title),
        element("p", "", module.value),
      );
      return card;
    }),
  );
}

function renderTimeline(detail) {
  const timeline = $("#timeline");
  timeline.replaceChildren();
}

function renderBudget(detail) {
  const panel = $("#budget-panel");
  panel.replaceChildren(element("h3", "", "预算拆分"));
  const rows = element("div", "budget-rows");
  const selected = state.recommendations.find(
    (candidate) => candidate.destination_id === detail.destination.id,
  );
  const values = [
    ["用户总预算", `¥${detail.request.total_budget}`],
    [
      "已知跨城交通",
      selected?.roundtrip_transport_cost_cny === null
        ? "UNKNOWN"
        : moneyText(selected?.roundtrip_transport_cost_cny),
    ],
    ["住宿", "UNKNOWN"],
    ["门票", "UNKNOWN"],
    ["当地交通", "UNKNOWN"],
  ];
  values.forEach(([label, value], index) => {
    const row = element("div", "budget-row");
    row.append(
      element("span", "", label),
      element("strong", index === 0 ? "" : "pending", value),
    );
    rows.append(row);
  });
  panel.append(rows);
}

function renderMissingSources(detail) {
  const list = $("#missing-sources");
  list.replaceChildren(
    ...detail.missing_real_sources.map(
      (source) => element("li", "", `未完成：${source}`),
    ),
  );
}

function moneyText(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value))
    ? `¥${Number(value).toFixed(1)}`
    : "UNKNOWN";
}

function clockText(value) {
  if (!value) return "UNKNOWN";
  const match = String(value).match(/T(\d{2}:\d{2})/);
  return match ? match[1] : String(value);
}

function attractionOpeningText(attraction) {
  const opening = attraction.opening_hours;
  if (opening.value) {
    return opening.last_entry
      ? `${opening.value}（停止入园 ${opening.last_entry}）`
      : opening.value;
  }
  if (Array.isArray(opening.observed_values)) {
    return `${opening.status}: ${opening.observed_values.join(" / ")}`;
  }
  return opening.status.toUpperCase();
}

function attractionTicketText(attraction) {
  const ticket = attraction.ticket;
  const amount = ticket.amount_cny ?? ticket.adult_base_cny;
  if (amount !== null && amount !== undefined) {
    return `${moneyText(amount)}（${ticket.status}）`;
  }
  if (Array.isArray(ticket.observed_values)) {
    return `${ticket.status}: ${ticket.observed_values.join(" / ")}`;
  }
  return ticket.status.toUpperCase();
}

function replanMainSummary(replan) {
  if (!replan) return "";
  const attractionChanges = replan.diff.attraction_changes
    .filter((value) => value.action !== "unchanged")
    .map((value) => `${value.label} ${value.action}`);
  const allEventChanges = [
    ...replan.diff.moved_events,
    ...replan.diff.removed_events,
    ...replan.diff.added_events,
  ];
  const countType = (type) => allEventChanges.filter(
    (value) => value.event_type === type,
  ).length;
  const railChanges = allEventChanges.filter(
    (value) => value.transport_mode === "high_speed_rail",
  ).length;
  const freeBlocks = replan.diff.added_events.filter(
    (value) => value.name === "自由活动 / 可用时间",
  );
  return [
    `景点：${attractionChanges.length ? attractionChanges.join("、") : "保持不变"}`,
    `跨城交通：${railChanges ? `${railChanges}处变化` : "保持不变"}`,
    `酒店：${countType("hotel") ? `${countType("hotel")}处变化` : "保持不变"}`,
    `主要餐食：${countType("meal") ? `${countType("meal")}处变化` : "保持不变"}`,
    ...(freeBlocks.length
      ? ["新增“自由活动 / 可用时间”"]
      : []),
  ].join("；");
}

function renderCompleteModules(result) {
  const moduleGrid = $("#module-grid");
  const lodging = result.accommodation_areas;
  const cards = [
    {
      title: "推荐住宿片区",
      body: `${result.recommended_lodging_area}。${result.lodging_recommendation_reason}`,
    },
    {
      title: "县城住宿价格",
      body: `${lodging[0].date_specific_lodging_price.status.toUpperCase()} · 2026-08-05至08-08未取得可复核日期价`,
    },
    {
      title: "篁岭附近住宿",
      body: `${lodging[1].date_specific_lodging_price.status.toUpperCase()} · 不因缺失价格默认推荐`,
    },
    {
      title: "最终状态",
      body: `${result.planning_status || result.status} · publishable=false`,
    },
    ...(result.replan
      ? [{
        title: "本次局部重排",
        body: `${result.replan.status} · ${replanMainSummary(result.replan)}；网络调用 0。`,
      }]
      : []),
    {
      title: "12306快照",
      body: result.gateway.snapshot?.display
        || "UNKNOWN · 未取得可用铁路快照",
    },
    {
      title: `节奏：${result.pace}`,
      body: `每日最多 ${result.pace_settings.max_attractions_per_day.value} 个景点；当地出发不早于 ${result.pace_settings.earliest_departure.value}；返回不晚于 ${result.pace_settings.latest_return.value}；节奏检查 ${result.pace_evaluation.status}。`,
    },
    {
      title: "本次节奏调整",
      body: result.pace_changes
        .map(
          (change) =>
            `${change.action} ${change.attraction || change.branch || ""}：${change.reason}`,
        )
        .join("；"),
    },
    ...result.attractions.map((attraction) => ({
      title: attraction.name,
      body: `${attraction.features.join("、")}。适合：${attraction.suitable_for.join("、")}；建议 ${durationText(Number(attraction.suggested_visit.minutes) * 60)}；开放 ${attractionOpeningText(attraction)}；门票 ${attractionTicketText(attraction)}。`,
      sources: attraction.sources,
    })),
  ];
  moduleGrid.replaceChildren(
    ...cards.map((value) => {
      const card = element("div", "module-card");
      card.append(element("h4", "", value.title), element("p", "", value.body));
      if (Array.isArray(value.sources)) {
        const sourceList = element("ul", "source-list");
        value.sources.forEach((source) => {
          const item = element("li");
          const link = element("a", "", source.title);
          link.href = source.url;
          link.target = "_blank";
          link.rel = "noreferrer";
          item.append(link);
          sourceList.append(item);
        });
        card.append(sourceList);
      }
      return card;
    }),
  );
}

function renderCompleteTimeline(result) {
  const renderedAttractionControls = new Set();
  const appliedEdits = result.replan?.applied_edits || {};
  const appliedMustVisit = new Set(appliedEdits.must_visit || []);
  const appliedLocked = new Set(appliedEdits.locked_event_ids || []);
  const appliedForcedDays = appliedEdits.forced_days || {};
  const cards = result.days.map((day) => {
    const card = element("article", "day-card");
    card.append(
      element("h3", "", `Day ${day.day} · ${day.date}`),
      element("p", "day-title", day.title),
    );
    [...day.events]
      .sort((left, right) => String(left.start_at).localeCompare(String(right.start_at)))
      .forEach((event) => {
      const row = element("div", "complete-timeline-row");
      row.dataset.eventType = event.type;
      const selectedByPlan = event.branch === undefined
        || event.branch === day.selected_branch;
      if (!selectedByPlan) row.classList.add("unselected-branch");
      const typeLabel = {
        transit: "交通",
        attraction: "景点",
        meal: "餐食",
        hotel: "酒店",
        buffer: "缓冲",
        rest: "休息",
      }[event.type] || event.type;
      row.append(
        element(
          "strong",
          "",
          `${clockText(event.start_at)}–${clockText(event.end_at)} · ${typeLabel}`,
        ),
        element("span", "", event.name),
      );
      if (event.type === "transit") {
        const distance = event.distance_meters === null
          || event.distance_meters === undefined
          ? "UNKNOWN"
          : `${(Number(event.distance_meters) / 1000).toFixed(1)}km`;
        const fare = event.fare || { amount_cny: null, status: "unknown" };
        const boarding = event.board_at || event.from || "UNKNOWN";
        const alighting = event.alight_at || event.to || "UNKNOWN";
        const service = event.service || event.transport_mode || "未确定";
        const backup = event.backup?.rule || (
          event.transport_mode === "ride_hailing"
            ? "现场取得车辆和报价后才能成立"
            : "公交不可用时才比较打车、包车和自驾"
        );
        row.append(
          element("span", "", `${boarding} 上车 · ${service} · ${alighting} 下车`),
          element(
            "small",
            "",
            `${durationText(event.duration_seconds)} · ${distance} · 票价 ${moneyText(fare.amount_cny)}（${fare.status}）`,
          ),
          element("small", "", `运营：${event.operating || "UNKNOWN"}`),
          element("small", "", `备选：${backup}`),
        );
      } else if (event.type === "meal") {
        row.append(
          element("small", "", `地点：${event.location || "UNKNOWN"}`),
          element(
            "small",
            "",
            `费用：${moneyText(event.cost?.amount_cny)}（${event.cost?.status || "unknown"}）`,
          ),
        );
      } else if (event.type === "attraction") {
        row.append(
          element(
            "small",
            "",
            `特色：${(event.features || []).join("、")}`,
          ),
          element(
            "small",
            "",
            `门票：${attractionTicketText({ticket: event.ticket})}`,
          ),
        );
        const editor = element("div", "event-replan-controls");
        editor.dataset.eventId = event.event_id;
        editor.dataset.attractionId = event.attraction_id;
        editor.dataset.currentDay = String(day.day);
        const start = event.start_at ? new Date(event.start_at) : null;
        const end = event.end_at ? new Date(event.end_at) : null;
        const duration = start && end
          ? Math.round((end.getTime() - start.getTime()) / 60000)
          : Number(event.planning_allocation_minutes || 120);
        editor.dataset.originalDuration = String(duration);
        if (!renderedAttractionControls.has(event.attraction_id)) {
          renderedAttractionControls.add(event.attraction_id);
          const mustLabel = element("label", "inline-edit-control");
          const must = element("input");
          must.type = "checkbox";
          must.className = "replan-must";
          must.checked = appliedMustVisit.has(event.attraction_id);
          mustLabel.append(must, element("span", "", "must_visit"));
          const removeLabel = element("label", "inline-edit-control");
          const remove = element("input");
          remove.type = "checkbox";
          remove.className = "replan-remove";
          removeLabel.append(remove, element("span", "", "删除地点"));
          const dayLabel = element("label", "inline-edit-control");
          dayLabel.append(element("span", "", "指定日期"));
          const daySelect = element("select", "replan-day");
          const keep = element("option", "", "保持当前日");
          keep.value = "";
          daySelect.append(keep);
          result.days.forEach((value) => {
            const option = element("option", "", `Day ${value.day}`);
            option.value = String(value.day);
            daySelect.append(option);
          });
          if (appliedForcedDays[event.attraction_id]) {
            daySelect.value = String(
              appliedForcedDays[event.attraction_id],
            );
          }
          dayLabel.append(daySelect);
          editor.append(mustLabel, removeLabel, dayLabel);
        }
        const durationLabel = element("label", "inline-edit-control");
        durationLabel.append(element("span", "", "游玩分钟"));
        const durationInput = element("input", "replan-duration");
        durationInput.type = "number";
        durationInput.min = "15";
        durationInput.max = "720";
        durationInput.step = "15";
        durationInput.value = String(duration);
        durationLabel.append(durationInput);
        const lockLabel = element("label", "inline-edit-control");
        const lock = element("input");
        lock.type = "checkbox";
        lock.className = "replan-lock";
        lock.checked = appliedLocked.has(event.event_id);
        lockLabel.append(lock, element("span", "", "锁定此事件"));
        editor.append(durationLabel, lockLabel);
        if (selectedByPlan) row.append(editor);
      }
      row.append(
        element("small", "", `安排原因：${event.why}`),
        element(
          "small",
          "",
          `依据：${event.value_origin} / ${event.timing_status}`,
        ),
        element(
          "small",
          "",
          `可调整：${event.adjustable?.length ? event.adjustable.join("、") : "无"}`,
        ),
      );
      if (event.branch) {
        row.append(
          element(
            "small",
            event.selected_by_pace ? "" : "pending",
            `条件方案：${event.branch} · ${
              event.selected_by_pace ? "当前节奏选中" : "未选中备选"
            }`,
          ),
        );
      }
      if (event.condition) {
        row.append(element("small", "pending", `成立条件：${event.condition}`));
      }
      if (event.conflicts?.length) {
        row.append(
          element("small", "error", `冲突：${event.conflicts.join("；")}`),
        );
      }
      card.append(row);
    });
    if (day.conditions?.length) {
      const conditions = element("ul", "day-conditions");
      day.conditions.forEach((condition) => {
        conditions.append(element("li", "", condition));
      });
      card.append(conditions);
    }
    if (day.pace_decisions?.length) {
      const decisions = element("div", "pace-decisions");
      decisions.append(element("strong", "", "节奏调整"));
      day.pace_decisions.forEach((decision) => {
        decisions.append(
          element(
            "p",
            "",
            `${decision.action} · ${decision.attraction || decision.branch || ""}：${decision.reason}`,
          ),
        );
      });
      card.append(decisions);
    }
    return card;
  });
  $("#timeline").replaceChildren(...cards);
}

function renderCompleteBudget(result) {
  const panel = $("#budget-panel");
  const budget = result.budget;
  const categories = budget.categories;
  const rows = [
    ["铁路", moneyText(categories.railway.amount_cny), categories.railway.support],
    ["接驳", moneyText(categories.station_transfer.amount_cny), categories.station_transfer.support],
    ["住宿", moneyText(categories.lodging.amount_cny), categories.lodging.support],
    [
      "门票",
      `${moneyText(categories.tickets.sourced_amount_cny)} + 未知项`,
      categories.tickets.support,
    ],
    ["当地交通", moneyText(categories.local_transport.amount_cny), categories.local_transport.support],
    [
      "餐饮",
      moneyText(categories.meals.amount_cny),
      categories.meals.support,
    ],
  ];
  panel.replaceChildren(element("h3", "", "完整预算拆分"));
  const container = element("div", "budget-rows");
  rows.forEach(([label, value, support]) => {
    const row = element("div", "budget-row");
    row.append(
      element("span", "", label),
      element("strong", support === "unknown" ? "pending" : "", `${value} · ${support}`),
    );
    container.append(row);
  });
  const summary = element(
    "p",
    "honesty-note",
    `来源金额 ${moneyText(budget.summary.sourced_amount_cny)}；估算金额 ${moneyText(budget.summary.estimated_amount_cny)}；未知前剩余预算 ${moneyText(budget.summary.remaining_before_unknowns_cny)}。`,
  );
  panel.append(container, summary);
}

function renderCompleteRouteDiagram(result) {
  showMapState(
    "行程已生成，地图坐标尚未就绪",
    `${result.recommended_lodging_area}及每日时间轴已使用真实数据生成；当前结果没有足够的 POI 坐标，地图不会用文字节点伪装路线。`,
  );
}

function optionalNumber(selector) {
  const text = $(selector)?.value.trim() || "";
  return text ? Number(text) : null;
}

function readPlannerDefaults() {
  const numeric = (id) => Number($(`#${id}`).value);
  const text = (id) => $(`#${id}`).value;
  return {
    breakfast_minutes: numeric("breakfast-minutes"),
    lunch_window_start: text("lunch-window-start"),
    lunch_window_end: text("lunch-window-end"),
    lunch_minutes: numeric("lunch-minutes"),
    dinner_window_start: text("dinner-window-start"),
    dinner_window_end: text("dinner-window-end"),
    dinner_minutes: numeric("dinner-minutes"),
    arrival_buffer_minutes: numeric("arrival-buffer-minutes"),
    rail_wait_minutes: numeric("rail-wait-minutes"),
    hotel_luggage_minutes: numeric("hotel-luggage-minutes"),
    hotel_checkin_minutes: numeric("hotel-checkin-minutes"),
    hotel_checkout_minutes: numeric("hotel-checkout-minutes"),
    inter_event_buffer_minutes: numeric("inter-event-buffer-minutes"),
    midday_rest_minutes: numeric("midday-rest-minutes"),
  };
}

function readPaceSettings() {
  const numeric = (id) => Number($(`#${id}`).value);
  return {
    pace: $("#pace-mode").value,
    physical_level: $("#physical-level").value,
    early_start: $("#early-start").checked,
    night_activity: $("#night-activity").checked,
    transport_tolerance: $("#transport-tolerance").value,
    depth_preference: $("#depth-preference").value,
    pace_overrides: {
      max_attractions_per_day: numeric("max-attractions-per-day"),
      earliest_departure: $("#earliest-departure").value,
      latest_return: $("#latest-return").value,
      max_daily_active_minutes: numeric("max-daily-active-minutes"),
      max_continuous_attraction_minutes: numeric(
        "max-continuous-attraction-minutes",
      ),
      max_transfers_per_day: numeric("max-transfers-per-day"),
      default_night_activity: $("#default-night-activity").checked,
      drop_low_priority: $("#drop-low-priority").checked,
    },
  };
}

function readReplanEdits() {
  const mustVisit = new Set();
  const removed = new Set();
  const forcedDays = {};
  const durations = {};
  const locked = [];
  document.querySelectorAll(".event-replan-controls").forEach((editor) => {
    const attractionId = editor.dataset.attractionId;
    const eventId = editor.dataset.eventId;
    if (editor.querySelector(".replan-must")?.checked) {
      mustVisit.add(attractionId);
    }
    if (editor.querySelector(".replan-remove")?.checked) {
      removed.add(attractionId);
    }
    const targetDay = editor.querySelector(".replan-day")?.value;
    if (targetDay) {
      forcedDays[attractionId] = Number(targetDay);
    }
    const duration = Number(editor.querySelector(".replan-duration")?.value);
    if (
      Number.isInteger(duration)
      && duration !== Number(editor.dataset.originalDuration)
    ) {
      durations[eventId] = duration;
    }
    if (editor.querySelector(".replan-lock")?.checked) {
      locked.push(eventId);
    }
  });
  return {
    must_visit: [...mustVisit],
    removed_attraction_ids: [...removed],
    forced_days: forcedDays,
    event_duration_minutes: durations,
    locked_event_ids: locked,
  };
}

function renderCompleteIssues(result) {
  const rows = [
    ...(result.schedule_conflicts || []).map(
      (value) => `[${value.severity}] ${value.message}`,
    ),
    ...(result.unknown || []).map((value) => `UNKNOWN: ${value}`),
  ];
  if (result.replan) {
    rows.unshift(
      ...result.replan.attempts.map(
        (value) =>
          `求解尝试 ${value.strategy}：${value.status}${
            value.reasons?.length ? `（${value.reasons.join("；")}）` : ""
          }`,
      ),
      ...result.replan.changes.map(
        (value) => `${value.action} ${value.attraction}：${value.reason}`,
      ),
      ...result.replan.diff.attraction_changes
        .filter((value) => value.action !== "unchanged")
        .map(
          (value) => `${value.action} ${value.label}：${value.reason}`,
        ),
      ...(result.replan.diff.locked_preserved_event_ids.length
        ? [`锁定保持：${result.replan.diff.locked_preserved_event_ids.join("、")}`]
        : []),
      ...result.replan.conflicts.map(
        (value) => `重排冲突：${value.message}`,
      ),
      ...result.replan.retained_unscheduled.map(
        (value) => `未排入 ${value.attraction_id}：${value.reason}`,
      ),
      ...result.replan.suggestions.map(
        (value) => `可选放松：${value}`,
      ),
    );
  }
  $("#missing-sources").replaceChildren(
    ...rows.map((value) => element("li", "", value)),
  );
  if (result.replan) {
    const minorChanges = [
      ...result.replan.diff.moved_events,
      ...result.replan.diff.removed_events,
      ...result.replan.diff.added_events,
    ].filter((value) => value.event_type === "buffer");
    if (minorChanges.length) {
      const item = element("li");
      const details = element("details", "minor-change-details");
      details.append(
        element(
          "summary",
          "",
          `展开微小buffer调整（${minorChanges.length}）`,
        ),
      );
      const list = element("ul");
      minorChanges.forEach((value) => {
        list.append(
          element(
            "li",
            "",
            `${value.name || value.event_id}：${value.reason}`,
          ),
        );
      });
      details.append(list);
      item.append(details);
      $("#missing-sources").append(item);
    }
  }
}

async function selectDestination(destinationId) {
  const status = $("#form-status");
  if (state.resultsStale) {
    setStatus(status, "表单已修改，旧候选已失效。请重新提交。", true);
    return;
  }
  setStatus(status, "正在建立详细规划工作区…");
  updateProgress(
    "#plan-progress",
    progressSnapshot(["understand"], "intercity"),
    "intercity",
  );
  try {
    const detail = await postJson("/api/select-destination", {
      destination_id: destinationId,
      request: state.discoveryRequest,
    });
    state.detail = detail;
    state.localPlanRequest = null;
    state.completePlan = null;
    $("#plan-title").textContent = `${detail.destination.region_label} · 详细规划`;
    $("#plan-subtitle").textContent =
      "正在加载已验证数据；失败项会保留具体原因。";
    $("#condition-panel").replaceChildren(conditionPanel(detail));
    renderRouteDiagram(detail);
    renderModules(detail);
    renderTimeline(detail);
    renderBudget(detail);
    renderMissingSources(detail);
    $("#local-result").classList.add("hidden");
    $("#local-plan-status").textContent = "";
    $("#recommendations-section").classList.add("hidden");
    $("#plan-section").classList.remove("hidden");
    $("#plan-section").classList.remove("is-stale");
    $("#plan-stale-results").classList.add("hidden");
    $("#discover-stage-pill").classList.remove("active");
    $("#plan-stage-pill").classList.add("active");
    setStatus(status, "");
  } catch (error) {
    setStatus(status, error.message, true);
  }
}

function localPlaceNames() {
  return $("#local-places").value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderLocalPlan(result) {
  const container = $("#local-result");
  const plan = result.local_plan;
  container.replaceChildren(element("h3", "", "当地粗行程"));
  plan.days.forEach((day) => {
    const dayBlock = element("div", "day-card");
    dayBlock.append(element("h3", "", `Day ${day.day_number} · ${day.date}`));
    if (!day.activities.length) {
      dayBlock.append(element("p", "", "本日暂无已排活动"));
    }
    day.activities.forEach((activity) => {
      const travel = activity.travel_from_previous;
      const text = travel
        ? `${activity.start_at}–${activity.end_at} · ${activity.name} · 前段 ${Math.ceil(travel.duration_seconds / 60)} 分钟`
        : `${activity.start_at}–${activity.end_at} · ${activity.name}`;
      dayBlock.append(element("p", "", text));
    });
    container.append(dayBlock);
  });
  const counts = element(
    "p",
    "muted",
    `matched ${plan.summary.matched} · unresolved ${plan.unresolved.length} · unmatched ${plan.unmatched.length} · unscheduled ${plan.unscheduled.length}`,
  );
  container.append(counts);
  container.classList.remove("hidden");
  const timelineCards = plan.days.map((day) => {
    const card = element("article", "day-card");
    card.append(element("h3", "", `Day ${day.day_number} · ${day.date}`));
    if (!day.activities.length) {
      card.append(element("p", "", "本日暂无已排活动"));
    }
    day.activities.forEach((activity) => {
      card.append(
        element(
          "p",
          "",
          `${activity.start_at}–${activity.end_at} · ${activity.name}`,
        ),
      );
    });
    return card;
  });
  $("#timeline").replaceChildren(...timelineCards);
  renderAmapPlan(plan);
  updateProgress(
    "#plan-progress",
    progressSnapshot(["understand", "intercity", "local_route", "plan"]),
  );
}

function renderCandidateSelections(result) {
  const container = $("#local-result");
  container.replaceChildren(
    element("h3", "", "需要选择具体地点身份"),
    element(
      "p",
      "muted",
      "以下地点存在多个精确候选。请选择后再生成；系统不会自动选择第一项。",
    ),
  );
  const form = element("form", "candidate-selection-form");
  result.selection_options.forEach((option) => {
    const fieldset = element("fieldset", "candidate-choice");
    fieldset.append(element("legend", "", option.seed));
    option.alternatives.forEach((candidate) => {
      const label = element("label", "candidate-option");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = `selection-${option.seed}`;
      input.value = candidate.candidate_id;
      const copy = element("span");
      copy.append(
        element("strong", "", candidate.name),
        element(
          "small",
          "",
          [candidate.category, candidate.district, candidate.address]
            .filter(Boolean)
            .join(" · "),
        ),
      );
      label.append(input, copy);
      fieldset.append(label);
    });
    form.append(fieldset);
  });
  const submit = element(
    "button",
    "button secondary full",
    "应用选择并生成当地粗行程",
  );
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const choices = {};
    for (const option of result.selection_options) {
      const chosen = form.querySelector(
        `input[name="selection-${CSS.escape(option.seed)}"]:checked`,
      );
      if (!chosen) {
        setStatus(
          $("#local-plan-status"),
          `请为“${option.seed}”选择一个候选。`,
          true,
        );
        return;
      }
      choices[option.seed] = chosen.value;
    }
    runLocalPlan(choices);
  });
  container.append(form);
  container.classList.remove("hidden");
}

async function runLocalPlan(selectionChoices = {}) {
  const status = $("#local-plan-status");
  const button = $("#local-plan-button");
  const isSelectionFollowup = Object.keys(selectionChoices).length > 0;
  const names = isSelectionFollowup
    ? state.localPlanRequest?.must_visit || []
    : localPlaceNames();
  if (!names.length) {
    setStatus(status, "请先填写至少一个当地地点。", true);
    return;
  }
  if (state.resultsStale) {
    setStatus(status, "Discover 条件已修改，请先重新提交。", true);
    return;
  }
  button.disabled = true;
  updateProgress(
    "#plan-progress",
    progressSnapshot(["understand", "intercity"], "local_route"),
    "local_route",
  );
  setStatus(status, "正在调用 simple_live；可能访问高德 Web 服务…");
  try {
    const payload = isSelectionFollowup
      ? {...state.localPlanRequest, selection_choices: selectionChoices}
      : {
          destination_id: state.detail.destination.id,
          discovery_request: state.detail.request,
          must_visit: names,
          transport_mode: $("#local-mode").value,
          visit_minutes: Number($("#visit-minutes").value),
          selection_choices: {},
        };
    state.localPlanRequest = payload;
    const result = await postJson("/api/local-plan", payload);
    if (result.requires_selection) {
      renderCandidateSelections(result);
      setStatus(status, "存在多个精确候选，等待用户明确选择。");
    } else {
      renderLocalPlan(result);
      setStatus(status, "当地地点解析与粗行程已返回。");
    }
  } catch (error) {
    setStatus(status, `当地规划未完成：${error.message}`, true);
  } finally {
    button.disabled = false;
  }
}

$("#discover-form").addEventListener("submit", submitDiscovery);
$("#discover-form").addEventListener("input", () => {
  updateDurationReadout();
  markResultsStale();
});
$("#back-button").addEventListener("click", () => {
  $("#plan-section").classList.add("hidden");
  $("#recommendations-section").classList.remove("hidden");
  $("#discover-stage-pill").classList.add("active");
  $("#plan-stage-pill").classList.remove("active");
});
$("#local-plan-button").addEventListener("click", runLocalPlan);

updateDurationReadout();
loadClientConfiguration();
