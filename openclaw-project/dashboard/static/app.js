// Owner dashboard client: SSE live viewer (fail-open), theme toggle.
// All agent/page content is inserted with textContent (inert); this script
// never uses innerHTML with server or agent data.
(function () {
  "use strict";
  // active nav highlight
  document.querySelectorAll("nav a").forEach(function (a) {
    if (a.getAttribute("href") === location.pathname) a.classList.add("on");
  });
  // small-screen menu
  const menuBtn = document.getElementById("menu-btn");
  if (menuBtn) menuBtn.addEventListener("click", function () { document.body.classList.toggle("menu"); });
  document.addEventListener("click", function (e) {
    if (document.body.classList.contains("menu") && !e.target.closest("#side") && !e.target.closest("#menu-btn")) document.body.classList.remove("menu");
  });
  // table search: <input data-filter-table="id"> hides rows that do not contain the text (textContent only)
  document.querySelectorAll("input[data-filter-table]").forEach(function (box) {
    const holder = document.getElementById(box.getAttribute("data-filter-table"));
    if (!holder) return;
    box.addEventListener("input", function () {
      const q = box.value.trim().toLowerCase();
      holder.querySelectorAll("tr").forEach(function (tr, i) {
        if (i === 0) return;
        tr.style.display = !q || tr.textContent.toLowerCase().indexOf(q) >= 0 ? "" : "none";
      });
    });
  });
  // the home page refreshes its numbers every 30 seconds unless you are typing or a form is focused
  if (location.pathname === "/") setInterval(function () {
    if (!document.hidden && !document.activeElement.closest("form")) location.reload();
  }, 30000);
  // theme
  const themeBtn = document.getElementById("theme-toggle");
  function setTheme(t) {
    document.body.classList.toggle("light", t === "light");
    try { localStorage.setItem("dash-theme", t); } catch (e) {}
    if (themeBtn) themeBtn.textContent = t === "light" ? "Dark" : "Light";
  }
  let saved = null;
  try { saved = localStorage.getItem("dash-theme"); } catch (e) {}
  setTheme(saved === "light" ? "light" : "dark");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    setTheme(document.body.classList.contains("light") ? "dark" : "light");
  });

  const tl = document.getElementById("timeline");
  if (!tl) return; // not on the live page

  const state = {
    paused: false, pending: [], seq: 0, shown: 0,
    agent: "", tool: "", es: null, retries: 0,
  };
  const pauseBtn = document.getElementById("pause");
  const statusEl = document.getElementById("live-status");
  const agentSel = document.getElementById("filter-agent");
  const toolSel = document.getElementById("filter-tool");
  if (pauseBtn) pauseBtn.addEventListener("click", function () {
    state.paused = !state.paused;
    pauseBtn.textContent = state.paused ? "Resume" : "Pause";
    if (!state.paused) flushPending();
  });
  function want(row) {
    return (!state.agent || row.agent === state.agent) &&
           (!state.tool || String(row.tool || "").indexOf(state.tool) >= 0);
  }
  function render(row) {
    const div = document.createElement("div");
    div.className = "evt " + (row.cls || "");
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = [row.ts, row.agent, row.tool].filter(Boolean).join(" · ") + "  ";
    const body = document.createElement("span");
    body.textContent = row.text || "";
    div.appendChild(meta); div.appendChild(body);
    if (row.detail) {
      const d = document.createElement("details");
      const s = document.createElement("summary"); s.textContent = "excerpt";
      const p = document.createElement("pre"); p.textContent = row.detail;
      d.appendChild(s); d.appendChild(p); div.appendChild(d);
    }
    tl.appendChild(div);
    state.shown += 1;
    if (statusEl) statusEl.textContent = state.shown + " events";
    if (tl.scrollHeight - tl.scrollTop - tl.clientHeight < 160) tl.scrollTop = tl.scrollHeight;
  }
  function flushPending() {
    while (state.pending.length) render(state.pending.shift());
  }
  function handle(evt) {
    let row; try { row = JSON.parse(evt.data); } catch (e) { return; }
    if (row.cursor) { state.seq = row.cursor; return; }
    if (row.agent && !agentSel.querySelector('option[value="' + row.agent + '"]')) {
      const o = document.createElement("option"); o.value = row.agent; o.textContent = row.agent;
      agentSel.appendChild(o);
    }
    if (!want(row)) return;
    if (state.paused) { state.pending.push(row); if (state.pending.length > 500) state.pending.shift(); }
    else render(row);
  }
  function connect() {
    if (state.es) state.es.close();
    const url = "/live/stream?cursor=" + state.seq +
      "&agent=" + encodeURIComponent(state.agent) +
      "&tool=" + encodeURIComponent(state.tool);
    state.es = new EventSource(url);
    state.es.onmessage = handle;
    state.es.onopen = function () { state.retries = 0; if (statusEl) statusEl.textContent = "connected"; };
    state.es.onerror = function () {
      state.es.close(); state.retries += 1;
      if (statusEl) statusEl.textContent = "disconnected (retry " + state.retries + ")";
      if (state.retries <= 10) setTimeout(connect, Math.min(15000, 1000 * state.retries));
    };
  }
  if (agentSel) agentSel.addEventListener("change", function () { state.agent = agentSel.value; connect(); });
  if (toolSel) toolSel.addEventListener("change", function () { state.tool = toolSel.value; connect(); });
  connect();
})();
