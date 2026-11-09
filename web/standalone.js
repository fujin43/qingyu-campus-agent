/* 单文件浏览器版：无服务器、无 Python；天气走 Open-Meteo，DOCX 在浏览器内生成。 */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const messagesEl = $("#messages");
  const inputEl = $("#input");
  const sendBtn = $("#sendBtn");
  const composerEl = $("#composer");
  const traceEl = $("#trace");
  const artifactsEl = $("#artifacts");
  const citationsEl = $("#citations");
  const snapshotEl = $("#snapshot");
  const latencyEl = $("#latency");
  const serverDot = $("#serverDot");
  const serverStatus = $("#serverStatus");
  const mobileInspectorBtn = $("#mobileInspectorBtn");
  const closeInspector = $("#closeInspector");
  const drawerBackdrop = $("#drawerBackdrop");

  const KB = Array.isArray(window.QY_KB) ? window.QY_KB : [];
  const TEMPLATES = {
    activity_signup: {
      name: "校园活动报名表",
      required: ["姓名", "学号", "学院", "专业", "班级", "活动名称", "活动日期", "联系电话"],
      aliases: ["活动报名表", "报名表", "活动表", "社团报名", "活动报名"],
    },
    leave_request: {
      name: "学生请假申请表",
      required: ["姓名", "学号", "学院", "请假事由", "开始时间", "结束时间"],
      aliases: ["请假申请表", "请假表", "请假条", "请假单", "请假"],
    },
  };
  const FIELD_ALIASES = {
    姓名: "姓名", 名字: "姓名", 学生姓名: "姓名",
    学号: "学号", 学院: "学院", 院系: "学院", 专业: "专业", 班级: "班级",
    联系电话: "联系电话", 联系方式: "联系电话", 手机: "联系电话", 手机号: "联系电话", 电话: "联系电话",
    活动名称: "活动名称", 活动: "活动名称", 活动名: "活动名称", 活动日期: "活动日期", 举办日期: "活动日期",
    备注: "备注", 请假事由: "请假事由", 事由: "请假事由", 原因: "请假事由",
    开始时间: "开始时间", 结束时间: "结束时间", 请假天数: "请假天数", 天数: "请假天数",
    紧急联系人: "紧急联系人", 联系人: "紧急联系人", 辅导员: "辅导员", 辅导员姓名: "辅导员",
  };
  const CITIES = [
    "郑州", "北京", "上海", "广州", "深圳", "南京", "武汉", "成都", "西安", "天津", "重庆",
    "苏州", "厦门", "长沙", "青岛", "大连", "宁波", "温州", "合肥", "福州", "济南", "昆明",
    "贵阳", "南宁", "海口", "三亚", "哈尔滨", "长春", "沈阳", "石家庄", "太原", "兰州",
  ];

  const WEATHER_CODES = {
    0: "晴", 1: "大部晴朗", 2: "多云", 3: "阴", 45: "有雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "较强毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪", 80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "强阵雪", 95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
  };

  const TOOL_LABELS = {
    "browser.plan": "浏览器规划",
    "time.now": "系统时间",
    "weather.get": "天气查询",
    "campus.search": "知识库检索",
    "doc.validate": "字段校验",
    "doc.fill": "文档生成",
    "doc.plan_card": "出行卡生成",
    "memory.set_profile": "偏好保存",
  };

  const state = {
    profile: loadJSON("qy_profile", { default_city: "郑州" }),
    pending: loadJSON("qy_pending", null),
    trace: [],
    artifacts: [],
    busy: false,
    queue: [],
  };

  function loadJSON(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function saveJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* ignore */ }
  }

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function xml(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&apos;");
  }

  function timeLabel() {
    const d = new Date();
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function todayLabel(offset = 0) {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    return `${d.getMonth() + 1}月${d.getDate()}日`;
  }

  function formatReply(text) {
    const lines = esc(text).split("\n");
    let html = "";
    for (const raw of lines) {
      let line = raw.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      if (!line.trim()) { html += "<br/>"; continue; }
      if (line.startsWith("•")) html += `<span class="point">${line}</span>`;
      else if (line.startsWith("数据时间：")) html += `<span class="meta-line">${line}</span>`;
      else if (/^(已按|已经|已为你|可以|好的|这个请求|抱歉|天气服务|校园知识库暂时|这次出行|我暂时|我在)/.test(line)) {
        html += `<span class="lead">${line}</span><br/>`;
      } else html += line + "<br/>";
    }
    return html.replace(/(<br\/>)+$/, "");
  }

  function addUser(text) {
    const row = document.createElement("div");
    row.className = "msg-row user";
    row.innerHTML = `<div class="msg-col"><div class="bubble">${esc(text)}</div><div class="msg-time">你 · ${timeLabel()}</div></div>`;
    messagesEl.appendChild(row);
    scrollBottom();
  }

  function addTyping() {
    const row = document.createElement("div");
    row.className = "msg-row assistant";
    row.innerHTML = `<div class="msg-avatar">晴</div><div class="msg-col"><div class="bubble"><div class="typing"><i></i><i></i><i></i></div></div></div>`;
    messagesEl.appendChild(row);
    scrollBottom();
    return row;
  }

  function artifactCard(artifact) {
    return `<div class="inline-artifact"><div class="file-icon">DOCX</div><div><strong>${esc(artifact.name)}</strong><span>${Math.max(1, Math.round((artifact.size || 0) / 1024))} KB · 点击下载</span></div><a href="${artifact.url}" download="${esc(artifact.filename)}">下载</a></div>`;
  }

  function addAssistant(data) {
    const row = document.createElement("div");
    row.className = "msg-row assistant";
    const chips = (data.suggestions || []).length
      ? `<div class="suggestions">${data.suggestions.map((s) => `<button class="suggestion">${esc(s)}</button>`).join("")}</div>` : "";
    row.innerHTML = `<div class="msg-avatar">晴</div><div class="msg-col"><div class="bubble">${formatReply(data.reply)}${(data.artifacts || []).map(artifactCard).join("")}</div><div class="msg-time">晴雨校园助手 · ${timeLabel()} · 浏览器版</div>${chips}</div>`;
    messagesEl.appendChild(row);
    row.querySelectorAll(".suggestion").forEach((btn) => btn.addEventListener("click", () => send(btn.textContent)));
    scrollBottom();
  }

  function renderTrace(trace, latency) {
    latencyEl.textContent = latency ? `${latency} ms` : "待命";
    if (!trace || !trace.length) {
      traceEl.className = "trace empty";
      traceEl.innerHTML = `<div class="empty-state"><div class="empty-icon">⌁</div><p>本轮没有调用工具</p><span>可以直接回答，或继续追问</span></div>`;
      return;
    }
    traceEl.className = "trace";
    traceEl.innerHTML = trace.map((item) => `<div class="trace-item ${item.status === "ok" ? "" : "error"}"><div class="trace-index">${String(item.step).padStart(2, "0")}</div><div><div class="trace-name"><b>${esc(TOOL_LABELS[item.tool] || item.tool)}</b><em>${esc(item.tool)}</em><span class="trace-status"></span></div><p class="trace-summary">${esc(item.summary)}</p><div class="trace-foot"><span>${item.duration_ms || 0} ms</span><span>${item.status === "ok" ? "成功" : "失败"}</span></div></div></div>`).join("");
  }

  function renderArtifacts(list) {
    if (!list || !list.length) {
      artifactsEl.className = "artifacts empty";
      artifactsEl.innerHTML = `<div class="empty-state small"><p>还没有生成文件</p><span>填写表单或生成出行卡后可下载</span></div>`;
      return;
    }
    artifactsEl.className = "artifacts";
    artifactsEl.innerHTML = list.map((item) => `<div class="artifact-item"><div class="file-icon">DOCX</div><div><strong>${esc(item.name)}</strong><span>${Math.max(1, Math.round((item.size || 0) / 1024))} KB</span></div><a href="${item.url}" download="${esc(item.filename)}">下载</a></div>`).join("");
  }

  function renderCitations(items) {
    if (!items || !items.length) {
      citationsEl.innerHTML = `<div class="source-row"><span class="source-dot weather"></span><span>Open-Meteo 天气</span><em>实时</em></div><div class="source-row"><span class="source-dot kb"></span><span>校园知识库</span><em>12 条</em></div>`;
      return;
    }
    citationsEl.innerHTML = items.map((item) => `<div class="source-row"><span class="source-dot ${item.type === "campus_kb" ? "kb" : "weather"}"></span><span>${esc(item.title)}</span><em>${esc(item.time || item.updated || "")}</em></div>`).join("");
  }

  function renderSnapshot(data) {
    if (data.weather) {
      const w = data.weather;
      const a = data.advice || {};
      snapshotEl.className = "snapshot";
      snapshotEl.innerHTML = `<div class="snapshot-grid"><div class="snap-card"><em>${w.current ? "当前气温" : "预报气温"}</em><strong>${w.current ? `${w.current.temperature}℃` : `${w.daily.temp_min}–${w.daily.temp_max}℃`}</strong><span>${esc(w.daily.weather)}</span></div><div class="snap-card"><em>降水概率</em><strong>${a.rain_probability != null ? a.rain_probability + "%" : "—"}</strong><span>${esc(a.umbrella || "")}</span></div><div class="snap-card wide"><em>推荐窗口</em><strong style="font-size:11px">${esc((w.window && w.window.label) || "—")}</strong><span>${esc((w.window && w.window.advice) || "按实时天气安排")}</span></div></div>`;
    } else if (data.artifact) {
      snapshotEl.className = "snapshot";
      snapshotEl.innerHTML = `<div class="snap-card doc wide"><em>本轮产物</em><strong>${esc(data.artifact.name)}</strong><span>${Math.max(1, Math.round((data.artifact.size || 0) / 1024))} KB · DOCX</span></div><div class="snap-card doc"><em>运行方式</em><strong>浏览器本地</strong><span>不上传服务器</span></div><div class="snap-card doc"><em>模板校验</em><strong>必填字段</strong><span>缺失会先追问</span></div>`;
    } else {
      snapshotEl.className = "snapshot empty";
      snapshotEl.innerHTML = `<div class="empty-state small"><p>浏览器本地运行</p><span>天气实时查询，文档在本地生成</span></div>`;
    }
  }

  function scrollBottom() {
    requestAnimationFrame(() => { messagesEl.scrollTop = messagesEl.scrollHeight; });
  }

  function welcome() {
    messagesEl.innerHTML = `<div class="welcome"><section class="hero"><div class="hero-eyebrow"><span></span> QINGYU CAMPUS · SINGLE FILE</div><h3>今天出门，<br/>先看天气，<em>再决定。</em></h3><p>单文件浏览器版：实时天气、校园知识库、DOCX 生成都在本机完成。不需要 Python、不需要服务器，双击 HTML 就能用。</p><div class="hero-stats"><div class="hero-stat"><strong>10</strong><span>工具/步骤</span></div><div class="hero-stat"><strong>4</strong><span>内置工作流</span></div><div class="hero-stat"><strong>12</strong><span>校园知识</span></div></div></section><div class="welcome-grid"><button class="example" data-prompt="郑州现在天气怎么样？需要带伞吗？"><b><i>☀</i> 查实时天气</b><p>“郑州现在天气怎么样？需要带伞吗？”</p></button><button class="example" data-prompt="明天早上8点从宿舍去图书馆，帮我看看天气、图书馆开不开，并生成一张出行计划卡。"><b><i>↗</i> 生成出行计划卡</b><p>天气 + 图书馆 + 随身清单</p></button><button class="example" data-prompt="帮我填写活动报名表：姓名=林晓，学号=20231234，学院=计算机学院，专业=软件工程，班级=软工2301，活动=秋季校园马拉松，活动日期=2026-11-15，联系方式=13800001234"><b><i>▤</i> 填写活动报名表</b><p>自然语言给字段，生成 DOCX</p></button><button class="example" data-prompt="图书馆几点关门？校车最晚一班几点？"><b><i>◎</i> 问校园知识库</b><p>回答带来源与更新时间</p></button></div></div>`;
    document.querySelectorAll("[data-prompt]").forEach((btn) => btn.addEventListener("click", () => send(btn.getAttribute("data-prompt"))));
  }

  function traceAdd(tool, status, summary, duration = 0) {
    state.trace.push({ step: state.trace.length + 1, tool, status, summary, duration_ms: Math.round(duration) });
  }

  function findTemplate(text) {
    for (const [id, meta] of Object.entries(TEMPLATES)) {
      if (meta.aliases.some((a) => text.includes(a))) return id;
    }
    return null;
  }

  function normalizeFields(raw) {
    const out = {};
    for (const [key, value] of Object.entries(raw || {})) {
      const canonical = FIELD_ALIASES[key] || key;
      if (value != null && String(value).trim()) out[canonical] = String(value).trim();
    }
    return out;
  }

  function extractFields(text) {
    const aliases = Object.keys(FIELD_ALIASES).sort((a, b) => b.length - a.length);
    const re = new RegExp(`(${aliases.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\s*[=:：]\\s*([^，,；;\\n]+)`, "g");
    const raw = {};
    let m;
    while ((m = re.exec(text))) raw[m[1]] = m[2].trim().replace(/[。；;]$/, "");
    return normalizeFields(raw);
  }

  function extractCity(text) {
    for (const city of CITIES) if (text.includes(city)) return city;
    if (/学校|校园|宿舍/.test(text)) return state.profile.default_city || "郑州";
    return state.profile.default_city || "郑州";
  }

  function extractWhen(text) {
    if (text.includes("后天")) return "dayafter";
    if (text.includes("明天") || text.includes("明早")) return "tomorrow";
    return "today";
  }

  function extractHour(text) {
    const m = text.match(/(?<!\d)(\d{1,2})\s*(?:点|[:：])\s*(\d{1,2})?/);
    if (!m) return null;
    let hour = Number(m[1]);
    if (hour > 23) return null;
    if (/下午|晚上/.test(text) && hour < 12) hour += 12;
    return hour;
  }

  function destination(text) {
    for (const place of ["图书馆", "教学楼", "食堂", "体育馆", "操场", "地铁站", "宿舍", "快递点", "行政楼"]) {
      if (text.includes(place)) return place;
    }
    const m = text.match(/去([\u4e00-\u9fa5A-Za-z0-9]{2,8})/);
    return m ? m[1].replace(/[，。].*$/, "") : "校园";
  }

  function plan(text) {
    state.trace = [];
    const lower = text.trim();
    if (!lower) return { intent: "clarify", reply: "我在。你可以让我查天气、找校园信息，或填写报名表/请假表。" };
    if (/系统提示词|忽略(之前|以上|前面).*指令|打印.*提示词|developer mode|jailbreak/i.test(text)) {
      return { intent: "security", reply: "这个请求我不能配合：内部提示词和工具配置不对外提供。我可以继续帮你查天气、找校园信息或填写文档。" };
    }
    if (/写(一篇|个)?.*(论文|作文|小说)|翻译(一下|成)|写代码|炒股|医疗诊断|法律咨询/.test(text)) {
      return { intent: "out_of_scope", reply: "这个请求超出我的服务范围。我只处理校园出行与校园事务：查天气、查校园知识库、填写报名/请假文档、生成出行卡。" };
    }
    if (/你好|你是谁|能做什么|帮助|功能|怎么用/.test(text)) {
      return { intent: "help", reply: "我是晴雨校园助手（单文件浏览器版）。可以：\n• 查实时天气与穿衣/带伞建议\n• 查图书馆、校车、食堂等校园信息\n• 填写活动报名表/请假表（本地生成 DOCX）\n• 把天气 + 校园信息 + 清单组合成出行卡\n\n直接说“郑州现在天气”或“明天去图书馆并生成出行卡”。" };
    }
    if (/记住|我怕冷|我怕热|我叫|默认城市/.test(text)) {
      if (/怕冷/.test(text)) return { intent: "memory", key: "temperature_sensitivity", value: "cold" };
      if (/怕热/.test(text)) return { intent: "memory", key: "temperature_sensitivity", value: "warm" };
      const name = text.match(/我叫([\u4e00-\u9fa5A-Za-z0-9]{1,12})/);
      if (name) return { intent: "memory", key: "nickname", value: name[1] };
      return { intent: "memory", key: "default_city", value: extractCity(text) };
    }
    if (state.pending && state.pending.template_id) {
      const fields = Object.assign({}, state.pending.fields, extractFields(text));
      return { intent: "doc", template_id: state.pending.template_id, fields, resumed: true };
    }
    const templateId = findTemplate(text);
    if (templateId || /(填写|填一下|填表|生成).{0,8}(表|文档)/.test(text)) {
      if (!templateId) return { intent: "clarify_template", reply: "我可以填写《校园活动报名表》或《学生请假申请表》。你想填哪一份？" };
      return { intent: "doc", template_id: templateId, fields: extractFields(text) };
    }
    if (/(出门|出行|去图书馆|去上课|去食堂|去操场|安排|计划|行程|出行卡)/.test(text) && /(天气|图书馆|出门|出行|计划|卡片|生成)/.test(text)) {
      return { intent: "trip", city: extractCity(text), when: extractWhen(text), hour: extractHour(text), destination: destination(text), make_card: /卡片|计划卡|出行卡|文档|生成/.test(text) };
    }
    if (/(天气|气温|多少度|下雨|降雨|带伞|穿什么|冷不冷|热不热|风大)/.test(text)) {
      return { intent: "weather", city: extractCity(text), when: extractWhen(text), hour: extractHour(text) };
    }
    if (/(图书馆|校车|摆渡车|班车|食堂|校园卡|饭卡|快递|驿站|报修|维修|场地|教室|报告厅|校园网|wifi|打印|体育馆|操场|自习室|请假流程)/i.test(text)) {
      return { intent: "campus", query: text };
    }
    return { intent: "clarify", reply: "我主要做四件事：①查实时天气与带伞/穿衣建议；②查图书馆、校车等校园信息；③填写报名表/请假表；④把天气和校园信息组合成出行卡。你想先做哪一件？" };
  }

  async function geocode(city) {
    const url = `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=5&language=zh&format=json`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("地名服务不可用");
    const data = await res.json();
    const list = data.results || [];
    if (!list.length) throw new Error(`没有找到“${city}”`);
    return list.find((x) => x.country_code === "CN") || list[0];
  }

  async function weatherGet(city, when = "today", preferredHour = null) {
    const started = performance.now();
    const place = await geoCodeCached(city);
    const params = new URLSearchParams({
      latitude: place.latitude, longitude: place.longitude,
      current: "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
      hourly: "temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,wind_speed_10m",
      daily: "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset",
      timezone: "Asia/Shanghai", forecast_days: "4", forecast_hours: "72", wind_speed_unit: "kmh",
    });
    const res = await fetch(`https://api.open-meteo.com/v1/forecast?${params.toString()}`);
    if (!res.ok) throw new Error("天气服务不可用");
    const data = await res.json();
    const offset = when === "today" ? 0 : when === "tomorrow" ? 1 : 2;
    const daily = data.daily || {};
    const code = daily.weather_code[offset];
    const target = new Date();
    target.setDate(target.getDate() + offset);
    const targetStr = target.toISOString().slice(0, 10);
    const hourly = (data.hourly.time || []).map((t, i) => ({
      time: t, hour: Number(t.slice(11, 13)),
      temp: data.hourly.temperature_2m[i], apparent: data.hourly.apparent_temperature[i],
      rain: data.hourly.precipitation_probability[i], precip: data.hourly.precipitation[i],
      wind: data.hourly.wind_speed_10m[i],
    })).filter((x) => x.time.startsWith(targetStr));
    let rows = hourly;
    if (offset === 0) {
      const nowHour = new Date().getHours();
      rows = hourly.filter((x) => x.hour >= Math.max(0, nowHour - 1));
    }
    let window = bestWindow(rows, preferredHour, offset === 0 ? "今天" : when === "tomorrow" ? "明天" : "后天");
    const cur = offset === 0 ? data.current : null;
    const weather = {
      city: place.name, current: cur ? { temperature: cur.temperature_2m, apparent: cur.apparent_temperature, precipitation: cur.precipitation, weather: WEATHER_CODES[cur.weather_code] || "未知", wind: cur.wind_speed_10m } : null,
      daily: { temp_min: daily.temperature_2m_min[offset], temp_max: daily.temperature_2m_max[offset], rain: daily.precipitation_probability_max[offset], weather: WEATHER_CODES[code] || "未知", uv: daily.uv_index_max[offset], date: daily.time[offset] },
      window, when, label: offset === 0 ? "今天" : when === "tomorrow" ? "明天" : "后天", fetched_at: new Date().toLocaleString("zh-CN", { hour12: false }),
    };
    weather.advice = makeAdvice(weather);
    weather.ms = performance.now() - started;
    return weather;
  }

  const GEO_CACHE = {};
  async function geoCodeCached(city) {
    if (GEO_CACHE[city]) return GEO_CACHE[city];
    const place = await geocode(city);
    GEO_CACHE[city] = place;
    return place;
  }

  function bestWindow(rows, preferredHour, label) {
    if (!rows.length) return null;
    const candidates = [];
    for (let i = 0; i < rows.length - 1; i++) {
      const a = rows[i], b = rows[i + 1];
      if (a.hour < 6 || a.hour > 21 || b.hour !== a.hour + 1) continue;
      const rain = ((a.rain || 0) + (b.rain || 0)) / 2;
      const temp = ((a.apparent || a.temp || 20) + (b.apparent || b.temp || 20)) / 2;
      let score = rain + Math.abs(temp - 22) * 2;
      if (preferredHour != null) score += Math.abs(a.hour - preferredHour) * 6;
      candidates.push({ start: a.hour, rain, temp, score });
    }
    if (!candidates.length) return null;
    const best = candidates.sort((x, y) => x.score - y.score)[0];
    return {
      start: `${String(best.start).padStart(2, "0")}:00`,
      end: `${String(best.start + 2).padStart(2, "0")}:00`,
      label: `${label}${String(best.start).padStart(2, "0")}:00–${String(best.start + 2).padStart(2, "0")}:00`,
      rain_probability: Math.round(best.rain), temperature: Math.round(best.temp * 10) / 10,
      advice: best.rain < 30 ? "适合出门" : "可以出门，注意天气变化",
    };
  }

  function makeAdvice(w) {
    const t = w.current ? w.current.apparent : ((w.daily.temp_min + w.daily.temp_max) / 2);
    let clothing = "长袖或短袖 + 轻薄外套";
    if (t <= 4) clothing = "厚羽绒服 + 保暖内搭";
    else if (t <= 10) clothing = "羽绒服/厚大衣 + 毛衣";
    else if (t <= 16) clothing = "大衣/夹克 + 长袖";
    else if (t <= 21) clothing = "薄外套 + 长袖/卫衣";
    else if (t <= 27) clothing = "长袖或短袖 + 轻薄外套";
    else if (t <= 32) clothing = "短袖 + 透气长裤/裙装";
    else clothing = "短袖短裤 + 防晒";
    const rain = w.daily.rain || 0;
    const umbrella = (w.current && w.current.precipitation > 0) || rain >= 55 ? "一定要带伞" : rain >= 25 ? "建议带折叠伞备用" : "可以不带伞";
    return { apparent: Math.round(t * 10) / 10, clothing, umbrella, rain_probability: rain, uv: w.daily.uv, summary: `${clothing}；${umbrella}` };
  }

  function campusSearch(query) {
    const grams = (s) => { const t = String(s || "").replace(/\s+/g, "").toLowerCase(); const set = new Set(); for (let i = 0; i < t.length - 1; i++) set.add(t.slice(i, i + 2)); return set; };
    const qg = grams(query);
    const scored = KB.map((e) => {
      const kw = (e.keywords || []).filter((k) => query.includes(k)).length;
      const title = [...grams(e.title)].filter((g) => qg.has(g)).length;
      const body = [...grams(e.answer)].filter((g) => qg.has(g)).length;
      return { ...e, score: kw * 4 + title * 2.2 + body * 0.7 };
    }).filter((x) => x.score > 0).sort((a, b) => b.score - a.score);
    return scored.slice(0, 2);
  }

  function validateDoc(templateId, fields) {
    const meta = TEMPLATES[templateId];
    const missing = meta.required.filter((k) => !fields[k]);
    let days = "";
    if (templateId === "leave_request" && fields["开始时间"] && fields["结束时间"]) {
      const start = new Date(fields["开始时间"].replace(" ", "T"));
      const end = new Date(fields["结束时间"].replace(" ", "T"));
      if (!Number.isNaN(start.getTime()) && !Number.isNaN(end.getTime()) && end > start) {
        const hours = (end - start) / 3600000;
        const d = Math.max(0.5, Math.round((hours / 8) * 2) / 2);
        days = Number.isInteger(d) ? String(d) : d.toFixed(1);
      }
    }
    return { meta, missing, days };
  }

  function docxBlob(title, rows, note) {
    const cell = (text, bold = false, fill = "FFFFFF") => `<w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="${fill}"/></w:tcPr><w:p><w:r><w:rPr>${bold ? "<w:b/>" : ""}<w:rFonts w:eastAsia="宋体"/><w:sz w:val="21"/></w:rPr><w:t xml:space="preserve">${xml(text)}</w:t></w:r></w:p></w:tc>`;
    const tableRows = rows.map(([k, v]) => `<w:tr>${cell(k, true, "E8F2F7")}${cell(v)}</w:tr>`).join("");
    const body = `<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="44"/><w:rFonts w:eastAsia="微软雅黑"/></w:rPr><w:t>${xml(title)}</w:t></w:r></w:p>` +
      `<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:sz w:val="18"/><w:color w:val="7B96AA"/></w:rPr><w:t>郑州大学 · 晴雨校园助手生成</w:t></w:r></w:p>` +
      `<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders><w:top w:val="single" w:sz="6" w:color="CFE1E7"/><w:left w:val="single" w:sz="6" w:color="CFE1E7"/><w:bottom w:val="single" w:sz="6" w:color="CFE1E7"/><w:right w:val="single" w:sz="6" w:color="CFE1E7"/><w:insideH w:val="single" w:sz="6" w:color="CFE1E7"/><w:insideV w:val="single" w:sz="6" w:color="CFE1E7"/></w:tblBorders></w:tblPr>${tableRows}</w:tbl>` +
      `<w:p><w:r><w:rPr><w:sz w:val="17"/><w:color w:val="7B96AA"/></w:rPr><w:t>${xml(note || "")}</w:t></w:r></w:p>` +
      `<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1440" w:bottom="1134" w:left="1440"/></w:sectPr>`;
    const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${body}</w:body></w:document>`;
    const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>`;
    const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>`;
    const zip = new JSZip();
    zip.file("[Content_Types].xml", contentTypes);
    zip.file("_rels/.rels", rels);
    zip.file("word/document.xml", documentXml);
    return zip.generateAsync({ type: "blob", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", compression: "DEFLATE" });
  }

  async function makeDoc(templateId, fields) {
    const check = validateDoc(templateId, fields);
    if (check.missing.length) return { ok: false, missing: check.missing, fields };
    const all = Object.assign({}, fields);
    if (templateId === "leave_request") all["请假天数"] = check.days || all["请假天数"] || "0.5";
    const rows = Object.keys(all).filter((k) => all[k]).map((k) => [k, all[k]]);
    const blob = await docxBlob(check.meta.name, rows, "本表由晴雨校园助手（单文件浏览器版）生成，请核对后提交。");
    const filename = `${check.meta.name}_${fields["姓名"] || "学生"}_${Date.now()}.docx`;
    return { ok: true, blob, filename, fields: all, meta: check.meta };
  }

  async function makePlanCard(city, label, weatherLine, advice, windowLine, campusLine, checklist, destinationName) {
    const rows = [["目的地", destinationName], ["天气概况", weatherLine], ["出行窗口", windowLine || "以实时天气为准"], ["穿衣与携带", advice], ["校园信息", campusLine || "未检索到额外校园信息"], ["随身清单", (checklist || []).join("、")]];
    const blob = await docxBlob("校园出行计划卡", rows, "天气来自 Open-Meteo；校园信息为示例知识库。");
    return { blob, filename: `校园出行计划卡_${destinationName}_${Date.now()}.docx`, name: "校园出行计划卡" };
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    return url;
  }

  function weatherText(w, advice) {
    const head = w.current
      ? `${w.city}${w.label}（${w.daily.date}）：此刻 ${w.current.temperature}℃，体感 ${w.current.apparent}℃，${w.current.weather}；今日 ${w.daily.temp_min}–${w.daily.temp_max}℃，当天最大降水概率 ${w.daily.rain}%。`
      : `${w.city}${w.label}（${w.daily.date}）：${w.daily.weather}，${w.daily.temp_min}–${w.daily.temp_max}℃，当天最大降水概率 ${w.daily.rain}%。`;
    const lines = [head, `• 穿衣：${advice.clothing}`, `• 带伞：${advice.umbrella}`];
    if (advice.uv != null) lines.push(`• 防晒：紫外线指数 ${advice.uv}，${advice.uv >= 7 ? "注意防晒" : "可做基础防晒"}`);
    if (w.window) lines.push(`• 更合适的窗口：${w.window.label}（降水概率约 ${w.window.rain_probability}%，体感 ${w.window.temperature}℃）`);
    lines.push("", `数据时间：${w.fetched_at}（Open-Meteo；浏览器实时请求）`);
    return lines.join("\n");
  }

  async function handle(text) {
    const planResult = plan(text);
    const reply = { suggestions: [], artifacts: [], citations: [] };
    try {
      if (planResult.intent === "security" || planResult.intent === "out_of_scope" || planResult.intent === "help") {
        reply.reply = planResult.reply;
      } else if (planResult.intent === "clarify" || planResult.intent === "clarify_template") {
        reply.reply = planResult.reply;
      } else if (planResult.intent === "memory") {
        state.profile[planResult.key] = planResult.value;
        saveJSON("qy_profile", state.profile);
        traceAdd("memory.set_profile", "ok", `记住 ${planResult.key}=${planResult.value}`, 1);
        reply.reply = `好的，已记住：${planResult.key} = ${planResult.value}。下次我会优先使用这个偏好。`;
      } else if (planResult.intent === "weather") {
        traceAdd("browser.plan", "ok", "本地规则规划 → weather_brief", 1);
        traceAdd("time.now", "ok", new Date().toLocaleString("zh-CN"), 1);
        const w = await weatherGet(planResult.city, planResult.when, planResult.hour);
        traceAdd("weather.get", "ok", `${w.city}${w.label}：${w.daily.weather} ${w.daily.temp_min}–${w.daily.temp_max}℃`, w.ms);
        const advice = w.advice;
        reply.reply = weatherText(w, advice);
        reply.suggestions = ["明天呢？", "需要带伞吗？", "图书馆开吗？", "生成出行卡"];
        reply.citations.push({ type: "weather", title: "Open-Meteo 实时天气", time: w.fetched_at });
        reply.weather = w; reply.advice = advice;
      } else if (planResult.intent === "campus") {
        traceAdd("browser.plan", "ok", "本地规则规划 → campus_qa", 1);
        const hits = campusSearch(planResult.query);
        traceAdd("campus.search", "ok", hits.length ? `命中 ${hits.length} 条校园知识` : "未命中", 1);
        if (!hits.length) reply.reply = "校园知识库里暂时没有找到相关条目。你可以换一种说法，或查看学校官网/公众号的最新通知。";
        else {
          reply.reply = "根据校园知识库：\n" + hits.map((x) => `• ${x.title}：${x.answer}\n  来源：${x.source}（更新于 ${x.updated}）`).join("\n");
          reply.suggestions = ["帮我填请假表", "生成出行卡", "郑州天气"];
          hits.forEach((x) => reply.citations.push({ type: "campus_kb", title: x.source, updated: x.updated }));
        }
      } else if (planResult.intent === "doc") {
        traceAdd("browser.plan", "ok", `本地规则规划 → doc_fill（${planResult.template_id}）`, 1);
        const check = validateDoc(planResult.template_id, planResult.fields);
        traceAdd("doc.validate", "ok", check.missing.length ? `还缺 ${check.missing.length} 项` : "字段完整", 1);
        if (check.missing.length) {
          state.pending = { template_id: planResult.template_id, fields: planResult.fields };
          saveJSON("qy_pending", state.pending);
          reply.reply = `可以，我来填《${check.meta.name}》。还需要你补充：\n${check.missing.join("、")}\n\n请按“字段=值”的格式发我，例如：${check.missing.slice(0, 3).map((k) => `${k}=…`).join("，")}\n已收到的字段我会先暂存，不会生成空表。`;
          reply.suggestions = ["取消填写", "查看模板字段"];
        } else {
          const doc = await makeDoc(planResult.template_id, planResult.fields);
          const url = downloadBlob(doc.blob, doc.filename);
          traceAdd("doc.fill", "ok", `已生成《${doc.meta.name}》`, 80);
          const artifact = { type: "docx", name: doc.meta.name, filename: doc.filename, size: doc.blob.size, url };
          reply.artifacts.push(artifact);
          state.pending = null; saveJSON("qy_pending", null);
          reply.reply = `已按《${doc.meta.name}》生成文档，字段校验通过。\n` +
            Object.entries(doc.fields).filter(([k, v]) => v && v !== "—" && !["申请日期", "备注"].includes(k)).map(([k, v]) => `• ${k}：${k === "联系电话" ? String(v).replace(/(1[3-9]\d)\d{4}(\d{4})/, "$1****$2") : v}`).join("\n") +
            `\n\n文件：${doc.filename}\n浏览器已开始下载，请在下载目录查看。`;
          reply.suggestions = ["再填一份请假表", "郑州天气", "图书馆开放时间"];
          reply.artifact = artifact;
        }
      } else if (planResult.intent === "trip") {
        traceAdd("browser.plan", "ok", "本地规则规划 → trip_plan", 1);
        traceAdd("time.now", "ok", new Date().toLocaleString("zh-CN"), 1);
        const w = await weatherGet(planResult.city, planResult.when, planResult.hour);
        traceAdd("weather.get", "ok", `${w.city}${w.label}：${w.daily.weather} ${w.daily.temp_min}–${w.daily.temp_max}℃`, w.ms);
        const hits = campusSearch(`${planResult.destination} 开放时间`);
        traceAdd("campus.search", "ok", hits.length ? `命中 ${hits.length} 条校园知识` : "未命中", 1);
        const campusLine = hits.length ? `${hits[0].title}：${hits[0].answer}` : "";
        const lines = ["已经按“天气 → 校园信息 → 出行卡”的顺序跑完：", `• 天气：${w.city}${w.label} ${w.daily.temp_min}–${w.daily.temp_max}℃，${w.daily.weather}，当天最大降水概率 ${w.daily.rain}%。`];
        if (w.window) lines.push(`• 推荐窗口：${w.window.label}（降水概率约 ${w.window.rain_probability}%，体感 ${w.window.temperature}℃）。`);
        lines.push(`• 穿带：${w.advice.clothing}；${w.advice.umbrella}。`);
        if (campusLine) lines.push(`• 校园：${campusLine}`);
        if (planResult.make_card) {
          const card = await makePlanCard(w.city, w.label, `${w.daily.weather} ${w.daily.temp_min}–${w.daily.temp_max}℃`, w.advice.summary, w.window ? w.window.label : "", campusLine, ["折叠伞", "外套", "校园卡", "水杯"], planResult.destination);
          const url = downloadBlob(card.blob, card.filename);
          traceAdd("doc.plan_card", "ok", "已生成校园出行计划卡", 60);
          const artifact = { type: "docx", name: "校园出行计划卡", filename: card.filename, size: card.blob.size, url };
          reply.artifacts.push(artifact);
          lines.push(`• 出行卡：已生成《${card.name}》，浏览器已开始下载。`);
          reply.artifact = artifact;
        }
        lines.push("", `建议：${w.window ? w.window.advice : "出发前再看一眼实时降水"}；出发前再看一眼实时降水。`);
        reply.reply = lines.join("\n");
        reply.suggestions = ["帮我填活动报名表", "图书馆开放时间", "郑州天气"];
        reply.weather = w; reply.advice = w.advice;
        reply.citations.push({ type: "weather", title: "Open-Meteo 实时天气", time: w.fetched_at });
        hits.forEach((x) => reply.citations.push({ type: "campus_kb", title: x.source, updated: x.updated }));
      } else {
        reply.reply = "我暂时没有对应的处理流程，请换一种说法。";
      }
    } catch (e) {
      traceAdd("weather.get", "error", String(e.message || e), 0);
      reply.reply = "这次没有完成：可能是天气接口网络较慢或浏览器拦截了请求。请稍后重试；如果一直失败，请检查网络。";
    }
    return reply;
  }

  async function send(text) {
    const msg = String(text || "").trim();
    if (!msg) return;
    if (state.busy) { state.queue.push(msg); return; }
    if (messagesEl.querySelector(".welcome")) messagesEl.innerHTML = "";
    state.busy = true; sendBtn.disabled = true;
    addUser(msg);
    const typing = addTyping();
    state.trace = []; state.artifacts = [];
    const started = performance.now();
    try {
      const data = await handle(msg);
      typing.remove();
      addAssistant(data);
      const latency = performance.now() - started;
      state.artifacts = data.artifacts || [];
      renderTrace(state.trace, latency);
      renderArtifacts(state.artifacts);
      renderCitations(data.citations || []);
      renderSnapshot(data);
      latencyEl.textContent = `${Math.round(latency)} ms`;
    } catch (e) {
      typing.remove();
      addAssistant({ reply: "浏览器本地执行失败：" + (e.message || e), artifacts: [], suggestions: [] });
    } finally {
      state.busy = false; sendBtn.disabled = false; inputEl.focus();
      if (state.queue.length) { const next = state.queue.shift(); setTimeout(() => send(next), 20); }
    }
  }

  function setStatus() {
    serverDot.classList.remove("offline");
    serverStatus.textContent = "浏览器本地运行 · 无需安装";
  }

  function setInspectorOpen(open) {
    const panel = $(".inspector");
    if (!panel) return;
    panel.classList.toggle("open", open);
    if (drawerBackdrop) drawerBackdrop.classList.toggle("open", open);
  }

  function reset() {
    state.pending = null; state.trace = []; state.artifacts = []; state.queue = [];
    saveJSON("qy_pending", null);
    welcome();
    renderTrace([], 0); renderArtifacts([]); renderCitations([]); renderSnapshot({});
    setStatus(); setInspectorOpen(false);
  }

  function bind() {
    composerEl.addEventListener("submit", (e) => {
      e.preventDefault();
      const t = inputEl.value; inputEl.value = ""; inputEl.style.height = "auto"; send(t);
    });
    inputEl.addEventListener("input", () => { inputEl.style.height = "auto"; inputEl.style.height = Math.min(90, inputEl.scrollHeight) + "px"; });
    inputEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); composerEl.requestSubmit(); }
    });
    $("#resetBtn").addEventListener("click", reset);
    if (mobileInspectorBtn) mobileInspectorBtn.addEventListener("click", () => setInspectorOpen(true));
    if (closeInspector) closeInspector.addEventListener("click", () => setInspectorOpen(false));
    if (drawerBackdrop) drawerBackdrop.addEventListener("click", () => setInspectorOpen(false));
  }

  // 供自动化测试使用（不影响 UI）
  window.__qyTest = { handle, weatherGet, makeDoc, docxBlob, plan, state };

  bind();
  welcome();
  renderTrace([], 0);
  renderArtifacts([]);
  renderCitations([]);
  renderSnapshot({});
  setStatus();
  inputEl.focus();
})();
