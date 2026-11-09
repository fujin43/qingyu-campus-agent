/* 晴雨校园助手 · 前端交互 */
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

  const state = {
    sessionId: localStorage.getItem("qy_session") || ("web-" + Math.random().toString(36).slice(2, 10)),
    busy: false,
    queue: [],
    demoTurns: 0,
  };
  localStorage.setItem("qy_session", state.sessionId);

  const TOOL_LABELS = {
    "llm.plan": "LLM 规划",
    "time.now": "系统时间",
    "weather.get": "天气查询",
    "weather.air_quality": "空气质量",
    "campus.search": "知识库检索",
    "doc.list_templates": "模板列表",
    "doc.validate": "字段校验",
    "doc.fill": "文档写入",
    "doc.plan_card": "出行卡生成",
    "memory.set_profile": "记忆写入",
    "memory.get_profile": "记忆读取",
  };

  const CATEGORY_COLORS = {
    weather: "weather",
    knowledge: "kb",
    document: "doc",
    memory: "memory",
    system: "system",
  };

  function uid() {
    return "s-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 7);
  }

  function esc(text) {
    return String(text == null ? "" : text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatReply(text) {
    const lines = esc(text).split("\n");
    let html = "";
    for (const raw of lines) {
      let line = raw;
      line = line.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      if (!line.trim()) {
        html += "<br/>";
        continue;
      }
      if (line.startsWith("•")) {
        html += `<span class="point">${line}</span>`;
      } else if (line.startsWith("数据时间：")) {
        html += `<span class="meta-line">${line}</span>`;
      } else if (/^(已按|已经|已为|可以|好的|这个请求|抱歉|天气服务|校园知识库暂时|这次出行|我暂时|我在)/.test(line)) {
        html += `<span class="lead">${line}</span><br/>`;
      } else {
        html += line + "<br/>";
      }
    }
    return html.replace(/(<br\/>)+$/, "");
  }

  function scrollBottom() {
    requestAnimationFrame(() => {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    });
  }

  function timeLabel() {
    const d = new Date();
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function welcomeHtml() {
    return `
      <div class="welcome">
        <section class="hero">
          <div class="hero-eyebrow"><span></span> QINGYU CAMPUS COPILOT</div>
          <h3>今天出门，<br/>先看天气，<em>再决定。</em></h3>
          <p>我是晴雨校园助手。把实时天气、校园知识库和 DOCX 文档工具串成一条工作流：
             查天气、给穿衣建议、找图书馆/校车信息、填写报名表和请假表，还能生成一张可下载的出行计划卡。</p>
          <div class="hero-stats">
            <div class="hero-stat"><strong>9</strong><span>可调用工具</span></div>
            <div class="hero-stat"><strong>4</strong><span>内置工作流</span></div>
            <div class="hero-stat"><strong>12</strong><span>校园知识条目</span></div>
          </div>
        </section>
        <div class="welcome-grid">
          <button class="example" data-prompt="郑州现在天气怎么样？需要带伞吗？">
            <b><i>☀</i> 查实时天气</b>
            <p>“郑州现在天气怎么样？需要带伞吗？”</p>
          </button>
          <button class="example" data-prompt="明天早上8点从宿舍去图书馆，帮我看看天气、图书馆开不开，并生成一张出行计划卡。">
            <b><i>↗</i> 生成出行计划卡</b>
            <p>天气 + 图书馆 + 随身清单，一次跑完</p>
          </button>
          <button class="example" data-prompt="帮我填写活动报名表：姓名=林晓，学号=20231234，学院=计算机学院，专业=软件工程，班级=软工2301，活动=秋季校园马拉松，活动日期=2026-11-15，联系方式=13800001234">
            <b><i>▤</i> 填写活动报名表</b>
            <p>自然语言给字段，自动生成 DOCX</p>
          </button>
          <button class="example" data-prompt="图书馆几点关门？校车最晚一班几点？">
            <b><i>◎</i> 问校园知识库</b>
            <p>回答带来源与更新时间</p>
          </button>
        </div>
      </div>`;
  }

  function renderWelcome() {
    messagesEl.innerHTML = welcomeHtml();
    bindPromptButtons(messagesEl);
  }

  function bindPromptButtons(root) {
    root.querySelectorAll("[data-prompt]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const prompt = btn.getAttribute("data-prompt");
        if (prompt) send(prompt);
      });
    });
  }

  function addUser(text) {
    const row = document.createElement("div");
    row.className = "msg-row user";
    row.innerHTML = `
      <div class="msg-col">
        <div class="bubble">${esc(text)}</div>
        <div class="msg-time">你 · ${timeLabel()}</div>
      </div>`;
    messagesEl.appendChild(row);
    scrollBottom();
  }

  function addTyping() {
    const row = document.createElement("div");
    row.className = "msg-row assistant";
    row.id = "typingRow";
    row.innerHTML = `
      <div class="msg-avatar">晴</div>
      <div class="msg-col">
        <div class="bubble"><div class="typing"><i></i><i></i><i></i></div></div>
      </div>`;
    messagesEl.appendChild(row);
    scrollBottom();
    return row;
  }

  function artifactCard(artifact) {
    const name = esc(artifact.name || artifact.filename || "文档");
    const size = artifact.size ? `${Math.max(1, Math.round(artifact.size / 1024))} KB` : "DOCX";
    const url = esc(artifact.url || ("/files/" + artifact.filename));
    return `
      <div class="inline-artifact">
        <div class="file-icon">DOCX</div>
        <div>
          <strong>${name}</strong>
          <span>${size} · 点击下载 / 打开核对</span>
        </div>
        <a href="${url}" target="_blank" rel="noopener">下载</a>
      </div>`;
  }

  function addAssistant(data, withSuggestions = true) {
    const row = document.createElement("div");
    row.className = "msg-row assistant";
    const artifacts = (data.artifacts || []).map(artifactCard).join("");
    const suggestions = withSuggestions && (data.suggestions || []).length
      ? `<div class="suggestions">${data.suggestions.map((s) => `<button class="suggestion">${esc(s)}</button>`).join("")}</div>`
      : "";
    row.innerHTML = `
      <div class="msg-avatar">晴</div>
      <div class="msg-col">
        <div class="bubble">${formatReply(data.reply || "")}${artifacts}</div>
        <div class="msg-time">晴雨校园助手 · ${timeLabel()} · ${data.planner === "llm" ? "LLM 规划" : data.planner === "rule_fallback" ? "规则兜底" : "规则规划"} · ${data.latency_ms || 0} ms</div>
        ${suggestions}
      </div>`;
    messagesEl.appendChild(row);
    row.querySelectorAll(".suggestion").forEach((btn) => {
      btn.addEventListener("click", () => send(btn.textContent));
    });
    scrollBottom();
    return row;
  }

  function renderTrace(trace, latency) {
    const list = trace || [];
    latencyEl.textContent = latency ? `${latency} ms` : "待命";
    if (!list.length) {
      traceEl.className = "trace empty";
      traceEl.innerHTML = `<div class="empty-state"><div class="empty-icon">⌁</div><p>本轮没有调用工具</p><span>我可以直接回答，或继续帮你查</span></div>`;
      return;
    }
    traceEl.className = "trace";
    traceEl.innerHTML = list.map((item) => {
      const name = TOOL_LABELS[item.tool] || item.tool;
      const status = item.status === "ok" ? "" : "error";
      return `
        <div class="trace-item ${status}">
          <div class="trace-index">${String(item.step).padStart(2, "0")}</div>
          <div>
            <div class="trace-name">
              <b>${esc(name)}</b>
              <em>${esc(item.tool)}</em>
              <span class="trace-status"></span>
            </div>
            <p class="trace-summary">${esc(item.summary || "")}</p>
            <div class="trace-foot">
              <span>${item.duration_ms || 0} ms</span>
              <span>${item.status === "ok" ? "成功" : "失败"}</span>
              ${item.error_code ? `<span>${esc(item.error_code)}</span>` : ""}
            </div>
          </div>
        </div>`;
    }).join("");
  }

  function renderArtifacts(artifacts) {
    if (!artifacts || !artifacts.length) {
      artifactsEl.className = "artifacts empty";
      artifactsEl.innerHTML = `<div class="empty-state small"><p>还没有生成文件</p><span>填写表单或生成出行卡后可下载</span></div>`;
      return;
    }
    artifactsEl.className = "artifacts";
    artifactsEl.innerHTML = artifacts.map((item) => `
      <div class="artifact-item">
        <div class="file-icon">DOCX</div>
        <div>
          <strong>${esc(item.name || item.filename)}</strong>
          <span>${item.size ? Math.max(1, Math.round(item.size / 1024)) + " KB" : "DOCX"}</span>
        </div>
        <a href="${esc(item.url || "/files/" + item.filename)}" target="_blank" rel="noopener">打开</a>
      </div>`).join("");
  }

  function renderCitations(citations) {
    if (!citations || !citations.length) {
      citationsEl.innerHTML = `
        <div class="source-row"><span class="source-dot weather"></span><span>Open-Meteo 天气</span><em>实时</em></div>
        <div class="source-row"><span class="source-dot kb"></span><span>校园知识库</span><em>示例 12 条</em></div>
        <div class="source-row"><span class="source-dot memory"></span><span>SQLite 会话记忆</span><em>本地</em></div>`;
      return;
    }
    citationsEl.innerHTML = citations.map((item) => {
      const dot = item.type === "campus_kb" ? "kb" : item.type === "weather" || item.type === "air" ? "weather" : "memory";
      const label = item.type === "campus_kb"
        ? `${item.title || "校园知识库"}${item.entry ? " · " + item.entry : ""}`
        : (item.title || "数据源");
      const extra = item.time || item.updated || "";
      return `<div class="source-row"><span class="source-dot ${dot}"></span><span>${esc(label)}</span><em>${esc(extra)}</em></div>`;
    }).join("");
  }

  function renderSnapshot(data) {
    const meta = data.meta || {};
    const weather = meta.weather;
    const artifact = meta.artifact;
    if (weather) {
      const daily = weather.daily || {};
      const advice = meta.advice || {};
      const window = weather.best_window || {};
      const hasCurrent = !!weather.current;
      const tempText = hasCurrent
        ? `${weather.current.temperature}℃`
        : `${daily.temp_min != null ? daily.temp_min : "—"}–${daily.temp_max != null ? daily.temp_max : "—"}℃`;
      const rainProb = advice.rain_probability != null ? advice.rain_probability : daily.rain_probability;
      snapshotEl.className = "snapshot";
      snapshotEl.innerHTML = `
        <div class="snapshot-grid">
          <div class="snap-card"><em>${hasCurrent ? "当前气温" : "预报气温"}</em><strong>${tempText}</strong><span>${esc(daily.weather || "")}</span></div>
          <div class="snap-card"><em>降水概率</em><strong>${rainProb != null ? rainProb + "%" : "—"}</strong><span>${esc(advice.umbrella || "")}</span></div>
          <div class="snap-card wide"><em>推荐窗口</em><strong style="font-size:11px">${esc(window.label || "—")}</strong><span>${esc(window.advice || "按实时天气安排")}</span></div>
          ${artifact ? `<div class="snap-card doc wide"><em>产物</em><strong>${esc(artifact.name)}</strong><span>${Math.max(1, Math.round((artifact.size || 0) / 1024))} KB · DOCX</span></div>` : ""}
        </div>`;
      return;
    }
    if (artifact) {
      snapshotEl.className = "snapshot";
      snapshotEl.innerHTML = `
        <div class="snap-card doc wide"><em>本轮产物</em><strong>${esc(artifact.name)}</strong>
        <span>${Math.max(1, Math.round((artifact.size || 0) / 1024))} KB · 已写入并校验</span></div>
        <div class="snap-card doc"><em>工具链</em><strong>validate → fill</strong><span>字段完整才允许写入</span></div>
        <div class="snap-card doc"><em>隐私</em><strong>手机号脱敏</strong><span>展示层掩码</span></div>`;
      return;
    }
    if (meta.results && meta.results.length) {
      snapshotEl.className = "snapshot";
      snapshotEl.innerHTML = `<div class="snap-card doc wide"><em>知识库命中</em><strong>${esc(meta.results[0].title)}</strong><span>来源：${esc(meta.results[0].source)} · ${esc(meta.results[0].updated)}</span></div>`;
      return;
    }
    snapshotEl.className = "snapshot empty";
    snapshotEl.innerHTML = `<div class="empty-state small"><p>本轮没有结构化数据</p><span>${data.trace && data.trace.length ? "已返回文字结果" : "未调用工具"}</span></div>`;
  }

  async function send(text) {
    const message = String(text || "").trim();
    if (!message) return;
    // 上一轮还没结束时，不丢消息：进入队列，等当前请求收尾后再发
    if (state.busy) {
      state.queue.push(message);
      return;
    }
    if (messagesEl.querySelector(".welcome")) messagesEl.innerHTML = "";
    state.busy = true;
    sendBtn.disabled = true;
    addUser(message);
    const typing = addTyping();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 75000);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId, message }),
        signal: controller.signal,
      });
      const data = await response.json();
      typing.remove();
      if (!response.ok) {
        addAssistant({ reply: "请求失败：" + (data.error || response.status), artifacts: [], suggestions: [] });
      } else {
        addAssistant(data);
        renderTrace(data.trace, data.latency_ms);
        renderArtifacts(data.artifacts);
        renderCitations(data.citations);
        renderSnapshot(data);
        if (data.profile) updateProfile(data.profile);
      }
    } catch (error) {
      typing.remove();
      if (error.name === "AbortError") {
        addAssistant({
          reply: "这次请求超过 75 秒仍未完成，已取消。可能是天气接口或 LLM 接口较慢，请稍后重试；如果多次出现，请重新启动本地服务。",
          artifacts: [],
          suggestions: ["重试一次", "郑州天气"],
        });
        setServerStatus(false, "请求超时，请检查本地服务");
      } else {
        addAssistant({
          reply: "无法连接本地服务：请双击项目根目录的“启动晴雨校园助手.bat”，然后刷新页面。\n" + error.message,
          artifacts: [],
          suggestions: [],
        });
        setServerStatus(false, "服务未连接，请双击启动脚本");
      }
    } finally {
      clearTimeout(timer);
      state.busy = false;
      sendBtn.disabled = false;
      inputEl.focus();
      if (state.queue.length) {
        const next = state.queue.shift();
        setTimeout(() => send(next), 30);
      }
    }
  }

  function updateProfile(profile) {
    if (!profile) return;
    const name = profile.nickname || "同学";
    $("#profileName").textContent = name;
    $("#profileCity").textContent = "默认城市：" + (profile.default_city || "郑州");
  }

  function setInspectorOpen(open) {
    const panel = $(".inspector");
    if (!panel) return;
    panel.classList.toggle("open", open);
    if (drawerBackdrop) drawerBackdrop.classList.toggle("open", open);
  }

  function setServerStatus(online, text) {
    if (!serverDot || !serverStatus) return;
    serverDot.classList.toggle("offline", !online);
    serverStatus.textContent = text;
  }

  async function checkHealth() {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (!response.ok) throw new Error("health " + response.status);
      const data = await response.json();
      setServerStatus(true, data.llm_enabled ? "本地运行中 · LLM 已连接" : "本地运行中 · 规则模式");
    } catch (error) {
      setServerStatus(false, "服务未连接，请双击启动脚本");
    }
  }

  function renderDemo(demo) {
    if (!demo) return;
    messagesEl.innerHTML = "";
    state.sessionId = demo.session_id || state.sessionId;
    if (demo.profile) updateProfile(demo.profile);
    const turns = demo.turns || [];
    turns.forEach((turn) => {
      addUser(turn.user);
      addAssistant(turn.assistant, true);
    });
    const last = turns.length ? turns[turns.length - 1].assistant : null;
    if (last) {
      renderTrace(last.trace, last.latency_ms);
      const allArtifacts = turns.flatMap((t) => t.assistant.artifacts || []);
      renderArtifacts(allArtifacts);
      const allCitations = turns.flatMap((t) => t.assistant.citations || []);
      renderCitations(allCitations);
      renderSnapshot(last);
    }
    state.demoTurns = turns.length;
    document.body.dataset.ready = "1";
  }

  async function reset() {
    if (state.busy) return;
    try {
      await fetch("/api/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: state.sessionId }),
      });
    } catch (e) { /* ignore */ }
    state.sessionId = uid();
    state.queue = [];
    localStorage.setItem("qy_session", state.sessionId);
    renderWelcome();
    renderTrace([], 0);
    renderArtifacts([]);
    renderCitations([]);
    renderSnapshot({ trace: [], meta: {} });
    setInspectorOpen(false);
  }

  function autoResize() {
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(90, inputEl.scrollHeight) + "px";
  }

  composerEl.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = inputEl.value;
    inputEl.value = "";
    autoResize();
    send(text);
  });
  inputEl.addEventListener("input", autoResize);
  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      composerEl.requestSubmit();
    }
  });
  $("#resetBtn").addEventListener("click", reset);
  if (mobileInspectorBtn) mobileInspectorBtn.addEventListener("click", () => setInspectorOpen(true));
  if (closeInspector) closeInspector.addEventListener("click", () => setInspectorOpen(false));
  if (drawerBackdrop) drawerBackdrop.addEventListener("click", () => setInspectorOpen(false));

  bindPromptButtons(document);
  checkHealth();
  setInterval(checkHealth, 15000);
  if (window.__DEMO__) {
    renderDemo(window.__DEMO__);
  } else {
    renderWelcome();
    renderTrace([], 0);
    renderArtifacts([]);
    renderCitations([]);
    fetch("/api/profile?session_id=" + encodeURIComponent(state.sessionId))
      .then((r) => r.json())
      .then((data) => updateProfile(data.profile))
      .catch(() => {});
    inputEl.focus();
  }
})();
