"use strict";

// ---------- Portal config (set per HTML entry page) ----------
const PORTAL = (document.documentElement.dataset.portal || "").toLowerCase();
const PORTAL_NAME = document.documentElement.dataset.name || "Restaurant OS";
const IS_ADMIN_PORTAL = PORTAL === "admin";
const IS_TENANT_PORTAL = PORTAL === "kfc" || PORTAL === "kababjees";

// ---------- API helpers ----------
const API_BASE = "";
const STORAGE = (key) => `${PORTAL}_${key}`;

function getToken() { return localStorage.getItem(STORAGE("access_token")); }
function setToken(t) { localStorage.setItem(STORAGE("access_token"), t); }
function clearAuth() {
  localStorage.removeItem(STORAGE("access_token"));
  localStorage.removeItem(STORAGE("role"));
  localStorage.removeItem(STORAGE("email"));
}
function getRole() { return localStorage.getItem(STORAGE("role")); }

if (!PORTAL) {
  document.body.innerHTML = "<p style='padding:40px;font-family:sans-serif'>Invalid portal. Go to <a href='/'>home</a>.</p>";
  throw new Error("No portal configured");
}

function parseApiError(body, fallback = "Request failed") {
  if (!body) return fallback;
  if (body.error?.message) return body.error.message;
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) {
    return body.detail.map((d) => d.msg || String(d)).join("; ");
  }
  if (typeof body.error === "string") return body.error;
  if (body.message) return body.message;
  return fallback;
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Portal-Id": PORTAL,
    ...(options.headers || {}),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const timeoutMs = options.timeoutMs ?? 20000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, {
      ...options,
      headers,
      credentials: "include",
      signal: controller.signal,
    });
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error("Request timed out — the server may be restarting. Try Refresh in a few seconds.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 401) {
    clearAuth();
    location.hash = "#/login";
    throw new Error("Session expired. Please log in again.");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { const e = await res.json(); msg = parseApiError(e, msg); } catch {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

async function login(email, password) {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Portal-Id": PORTAL },
    credentials: "include",
    body: JSON.stringify({ email, password, portal: PORTAL }),
  });
  if (!res.ok) {
    let msg = "Login failed";
    try { const e = await res.json(); msg = parseApiError(e, msg); } catch {}
    throw new Error(msg);
  }
  const data = await res.json();
  setToken(data.access_token);
  localStorage.setItem(STORAGE("role"), data.role);
  localStorage.setItem(STORAGE("email"), email);
  return data;
}

// ---------- UI utils ----------
function toast(message, type = "info") {
  const c = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  c.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function fmtMoney(n) { return "Rs " + Number(n || 0).toLocaleString(); }
function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function loadingBlock(lines = 3) {
  return Array.from({ length: lines }, () => '<div class="skeleton" style="height:48px;margin-bottom:8px"></div>').join("");
}

function clearPageOverlays() {
  document.querySelectorAll(".modal-backdrop").forEach((node) => node.remove());
}

// ---------- Layout ----------
const TENANT_NAV = [
  { hash: "#/orders", label: "Live Orders", ic: "🧾" },
  { hash: "#/menu", label: "Menu", ic: "📋" },
  { hash: "#/analytics", label: "Analytics", ic: "📊" },
];
const ADMIN_NAV = [{ hash: "#/admin", label: "Overview", ic: "🏢" }];

function renderLayout(activeHash, contentNode) {
  clearPageOverlays();
  const nav = IS_ADMIN_PORTAL ? ADMIN_NAV : TENANT_NAV;
  const email = localStorage.getItem(STORAGE("email")) || "";
  const role = getRole() || "";
  const app = document.getElementById("app");
  app.innerHTML = "";
  const layout = el(`
    <div class="layout">
      <aside class="sidebar">
        <div class="brand"><span class="dot"></span><span>${esc(PORTAL_NAME)}</span></div>
        <nav id="nav"></nav>
        <div class="spacer"></div>
        <div class="user-box">
          <div class="email">${esc(email)}</div>
          <div class="role">${esc(role)} · ${esc(PORTAL)} portal</div>
          <a href="/" class="btn btn-ghost btn-sm" style="margin-top:8px;width:100%;display:block;text-align:center">← All portals</a>
          <button class="btn btn-ghost btn-sm" id="logout" style="margin-top:8px;width:100%">Logout</button>
        </div>
      </aside>
      <main class="main" id="main"></main>
    </div>`);
  const navEl = layout.querySelector("#nav");
  nav.forEach((n) => {
    const a = el(`<a class="nav-item ${n.hash === activeHash ? "active" : ""}" href="${n.hash}"><span class="ic">${n.ic}</span><span>${n.label}</span></a>`);
    navEl.appendChild(a);
  });
  layout.querySelector("#logout").onclick = async () => {
    try { await api(`/auth/logout?portal=${PORTAL}`, { method: "POST" }); } catch {}
    clearAuth();
    location.hash = "#/login";
  };
  app.appendChild(layout);
  layout.querySelector("#main").appendChild(contentNode);
}

// ---------- Pages ----------
function pageLogin() {
  clearPageOverlays();
  const app = document.getElementById("app");
  app.innerHTML = "";
  const card = el(`
    <div class="login-wrap">
      <form class="login-card" id="loginForm">
        <div class="logo"><span class="dot"></span> ${esc(PORTAL_NAME)}</div>
        <h1>Sign in</h1>
        <p class="sub">This portal only accepts ${esc(PORTAL_NAME)} accounts</p>
        <div class="error-msg" id="err" style="display:none"></div>
        <div class="field">
          <label>Email</label>
          <input type="email" id="email" placeholder="you@restaurant.com" required autocomplete="username" />
        </div>
        <div class="field">
          <label>Password</label>
          <input type="password" id="password" placeholder="••••••••" required autocomplete="current-password" />
        </div>
        <button type="submit" class="btn">Sign in</button>
        <div class="hint">
          Use the email and password issued for this portal.<br/>
          <a href="/">← Back to portal picker</a>
        </div>
      </form>
    </div>`);
  app.appendChild(card);
  card.querySelector("#loginForm").onsubmit = async (e) => {
    e.preventDefault();
    const errEl = card.querySelector("#err");
    errEl.style.display = "none";
    const btn = card.querySelector("button[type=submit]");
    btn.textContent = "Signing in...";
    btn.disabled = true;
    try {
      await login(card.querySelector("#email").value, card.querySelector("#password").value);
      location.hash = IS_ADMIN_PORTAL ? "#/admin" : "#/orders";
    } catch (err) {
      errEl.textContent = err.message;
      errEl.style.display = "block";
      btn.textContent = "Sign in";
      btn.disabled = false;
    }
  };
}

const COLUMNS = ["placed", "accepted", "out_for_delivery", "delivered"];
const NEXT = { placed: "accepted", accepted: "out_for_delivery", preparing: "out_for_delivery", out_for_delivery: "delivered" };
const COL_LABELS = {
  placed: "New orders",
  accepted: "Accepted",
  out_for_delivery: "On the way",
  delivered: "Delivered",
};
const NEXT_LABELS = {
  placed: "Accept order",
  accepted: "Out for delivery",
  preparing: "Out for delivery",
  out_for_delivery: "Mark delivered",
};

function columnForStatus(status) {
  if (status === "preparing") return "accepted";
  return status;
}
let _ws = null;
let _wsTimer = null;
let _wsReconnectTimer = null;
let _wsPollTimer = null;
let _wsRetries = 0;

function scheduleWsReload(fn) {
  if (_wsTimer) clearTimeout(_wsTimer);
  _wsTimer = setTimeout(fn, 300);
}

function stopWsPoll() {
  if (_wsPollTimer) {
    clearInterval(_wsPollTimer);
    _wsPollTimer = null;
  }
}

function startWsPoll(onEvent) {
  if (_wsPollTimer) return;
  _wsPollTimer = setInterval(() => onEvent({ refresh: true }), 12000);
}

async function pageOrders() {
  const content = el(`
    <div>
      <div class="page-head">
        <div>
          <h2>Live Orders</h2>
          <p class="page-sub" id="orderSummary">Loading orders…</p>
        </div>
        <div class="page-head-actions">
          <button class="btn btn-sm btn-ghost" id="refreshBtn" type="button">↻ Refresh</button>
          <span class="live-badge off" id="liveBadge"><span class="pulse"></span> connecting…</span>
        </div>
      </div>
      <div class="kanban" id="kanban"></div>
    </div>`);
  renderLayout("#/orders", content);
  const kanban = content.querySelector("#kanban");
  const summary = content.querySelector("#orderSummary");
  kanban.innerHTML = loadingBlock(5);

  async function load(opts = {}) {
    const path = "/orders/board?nocache=1";
    let orders = [];
    try { orders = await api(path); } catch (e) {
      toast(e.message, "error");
      summary.textContent = "Could not load orders";
      kanban.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
      return;
    }
    const active = orders.filter((o) => o.status !== "delivered");
    summary.textContent = active.length
      ? `${active.length} active order${active.length === 1 ? "" : "s"} · updates appear automatically`
      : "No active orders — new WhatsApp orders will show here instantly";

    kanban.innerHTML = "";
    COLUMNS.forEach((col) => {
      const list = orders.filter((o) => columnForStatus(o.status) === col);
      const colEl = el(`
        <div class="kcol" data-status="${col}">
          <div class="kcol-head">
            <h3>${COL_LABELS[col] || col}</h3>
            <span class="count">${list.length}</span>
          </div>
          <div class="kcol-body"></div>
        </div>`);
      const body = colEl.querySelector(".kcol-body");
      if (!list.length) {
        body.appendChild(el(`<div class="kcol-empty">No orders here</div>`));
      }
      list.forEach((o) => {
        const items = o.items || [];
        const itemsHtml = items.length
          ? `<ul class="ocard-items">${items.map((i) => `<li>${i.quantity}× ${esc(i.name)}</li>`).join("")}</ul>`
          : `<div class="ocard-items empty">No items listed</div>`;
        const card = el(`
          <div class="ocard" data-order-id="${esc(o.id)}">
            <div class="ocard-top">
              <div class="id">#${o.id.slice(0, 8)}</div>
              <div class="total">${fmtMoney(o.total)}</div>
            </div>
            <div class="customer">${esc(o.customer_name || "Customer")}</div>
            <div class="addr">${esc(o.delivery_address || "No address")}</div>
            ${itemsHtml}
            <div class="meta">${o.item_count || items.length || 0} item${(o.item_count || items.length || 0) === 1 ? "" : "s"} · ${fmtTime(o.placed_at)}</div>
          </div>`);
        if (NEXT[o.status]) {
          const acts = el(`<div class="acts"></div>`);
          const adv = el(`<button class="btn btn-sm btn-advance" type="button">${NEXT_LABELS[o.status] || "Advance"}</button>`);
          adv.onclick = async () => {
            adv.disabled = true;
            adv.textContent = "Updating…";
            try {
              await api(`/orders/${o.id}/status`, { method: "PATCH", body: JSON.stringify({ status: NEXT[o.status] }) });
              await load({ refresh: true });
            } catch (e) {
              toast(e.message, "error");
              adv.disabled = false;
              adv.textContent = NEXT_LABELS[o.status] || "Advance";
            }
          };
          acts.appendChild(adv);
          if (o.status !== "delivered") {
            const cancel = el(`<button class="btn btn-sm btn-ghost btn-cancel" type="button" title="Cancel order">Cancel</button>`);
            cancel.onclick = async () => {
              if (!confirm("Cancel this order?")) return;
              try {
                await api(`/orders/${o.id}/status`, { method: "PATCH", body: JSON.stringify({ status: "cancelled" }) });
                await load({ refresh: true });
              } catch (e) { toast(e.message, "error"); }
            };
            acts.appendChild(cancel);
          }
          card.appendChild(acts);
        }
        body.appendChild(card);
      });
      kanban.appendChild(colEl);
    });
  }

  content.querySelector("#refreshBtn").onclick = () => load({ refresh: true });

  await load();
  connectWs(content.querySelector("#liveBadge"), () => load({ refresh: true }));
}

let _wsConnectTimer = null;

function connectWs(badge, onEvent) {
  const token = getToken();
  if (!token) return;
  if (_wsReconnectTimer) {
    clearTimeout(_wsReconnectTimer);
    _wsReconnectTimer = null;
  }
  if (_wsConnectTimer) {
    clearTimeout(_wsConnectTimer);
    _wsConnectTimer = null;
  }
  try { if (_ws) _ws.close(); } catch {}
  const wsBase = location.origin.replace(/^http/, "ws");
  _ws = new WebSocket(`${wsBase}/ws/orders`, [`access.${token}`]);
  _wsConnectTimer = setTimeout(() => {
    if (_ws && _ws.readyState === WebSocket.CONNECTING) {
      try { _ws.close(); } catch {}
      badge.className = "live-badge off";
      badge.innerHTML = '<span class="pulse"></span> Offline · polling';
      startWsPoll(onEvent);
    }
  }, 10000);
  _ws.onopen = () => {
    if (_wsConnectTimer) { clearTimeout(_wsConnectTimer); _wsConnectTimer = null; }
    _wsRetries = 0;
    stopWsPoll();
    badge.className = "live-badge";
    badge.innerHTML = '<span class="pulse"></span> Live';
    onEvent({ refresh: true });
  };
  _ws.onclose = () => {
    if (_wsConnectTimer) { clearTimeout(_wsConnectTimer); _wsConnectTimer = null; }
    badge.className = "live-badge off";
    badge.innerHTML = '<span class="pulse"></span> Reconnecting…';
    startWsPoll(onEvent);
    const delay = Math.min(30000, 2000 * Math.pow(2, _wsRetries++));
    _wsReconnectTimer = setTimeout(() => connectWs(badge, onEvent), delay);
  };
  _ws.onerror = () => {
    badge.className = "live-badge off";
    badge.innerHTML = '<span class="pulse"></span> Reconnecting…';
  };
  _ws.onmessage = (m) => {
    try {
      const ev = JSON.parse(m.data);
      if (ev.type === "order_created") {
        toast("New order received!", "success");
      } else if (ev.type === "order_status_changed") {
        toast("Order updated", "info");
      }
    } catch {}
    scheduleWsReload(() => onEvent({ refresh: true }));
  };
}

async function pageMenu() {
  const content = el(`
    <div>
      <div class="page-head"><h2>Menu</h2></div>
      <form class="toolbar" id="addForm">
        <div class="field"><label>Item name</label><input id="mName" placeholder="e.g. Chicken Biryani" required /></div>
        <div class="field"><label>Price (Rs)</label><input id="mPrice" type="number" step="0.01" min="0" placeholder="450" required style="width:120px" /></div>
        <div class="field"><label>Description</label><input id="mDesc" placeholder="optional" /></div>
        <button class="btn btn-sm" type="submit" style="height:38px">+ Add item</button>
      </form>
      <table>
        <thead><tr><th>Item</th><th>Description</th><th>Price</th><th>Available</th><th></th></tr></thead>
        <tbody id="rows"></tbody>
      </table>
    </div>`);
  renderLayout("#/menu", content);
  const rows = content.querySelector("#rows");
  rows.innerHTML = `<tr><td colspan="5">${loadingBlock(4)}</td></tr>`;

  async function load() {
    let items = [];
    try { items = await api("/menu/items"); } catch (e) { toast(e.message, "error"); return; }
    rows.innerHTML = "";
    if (!items.length) { rows.appendChild(el(`<tr><td colspan="5"><div class="empty">No menu items yet. Add your first item above.</div></td></tr>`)); return; }
    items.forEach((i) => {
      const tr = el(`
        <tr>
          <td><b>${esc(i.name)}</b></td>
          <td style="color:var(--muted)">${esc(i.description || "—")}</td>
          <td>${fmtMoney(i.price)}</td>
          <td></td>
          <td style="text-align:right"></td>
        </tr>`);
      const toggle = el(`<label class="toggle"><input type="checkbox" ${i.is_available ? "checked" : ""}/><span class="slider"></span></label>`);
      toggle.querySelector("input").onchange = async (e) => {
        try { await api(`/menu/items/${i.id}`, { method: "PATCH", body: JSON.stringify({ is_available: e.target.checked }) }); toast("Updated", "success"); }
        catch (err) { toast(err.message, "error"); e.target.checked = !e.target.checked; }
      };
      tr.children[3].appendChild(toggle);
      const del = el(`<button class="btn btn-sm btn-ghost">Delete</button>`);
      del.onclick = async () => {
        if (!confirm(`Delete "${i.name}"?`)) return;
        try { await api(`/menu/items/${i.id}`, { method: "DELETE" }); toast("Deleted", "success"); load(); }
        catch (e) { toast(e.message, "error"); }
      };
      tr.children[4].appendChild(del);
      rows.appendChild(tr);
    });
  }

  content.querySelector("#addForm").onsubmit = async (e) => {
    e.preventDefault();
    const body = {
      name: content.querySelector("#mName").value,
      price: parseFloat(content.querySelector("#mPrice").value),
      description: content.querySelector("#mDesc").value || null,
      is_available: true,
    };
    try {
      await api("/menu/items", { method: "POST", body: JSON.stringify(body) });
      e.target.reset();
      toast("Item added — agent menu updating", "success");
      load();
    } catch (err) { toast(err.message, "error"); }
  };

  await load();
}

let _charts = [];
function destroyCharts() { _charts.forEach((c) => { try { c.destroy(); } catch {} }); _charts = []; }

function analyticsRangeQuery(days) {
  if (!days) return "";
  const map = { 1: "today", 7: "7d", 30: "30d" };
  const range = map[Number(days)] || days;
  return `?range=${encodeURIComponent(range)}&_=${Date.now()}`;
}

function formatChartBucket(iso, days) {
  if (!iso) return "";
  const d = new Date(iso);
  if (days === "1") {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "2-digit", day: "2-digit" });
}

async function pageAnalytics() {
  const content = el(`
    <div>
      <div class="page-head">
        <h2>Analytics</h2>
        <select id="range" class="">
          <option value="">All time</option>
          <option value="1">Today</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
        </select>
      </div>
      <div class="kpi-grid" id="kpis"></div>
      <div class="chart-grid">
        <div class="card"><h3>Revenue over time</h3><div class="chart-box"><canvas id="revChart"></canvas></div></div>
        <div class="card"><h3>Top items</h3><div class="chart-box"><canvas id="topChart"></canvas></div></div>
      </div>
      <div class="chart-grid">
        <div class="card"><h3>Orders by status</h3><div class="chart-box"><canvas id="statusChart"></canvas></div></div>
        <div class="card"><h3>Peak hours</h3><div class="chart-box"><canvas id="hoursChart"></canvas></div></div>
      </div>
    </div>`);
  renderLayout("#/analytics", content);
  content.querySelector("#kpis").innerHTML = loadingBlock(4);

  let loadSeq = 0;
  async function load() {
    const seq = ++loadSeq;
    destroyCharts();
    const kpisEl = content.querySelector("#kpis");
    kpisEl.innerHTML = loadingBlock(4);
    const days = content.querySelector("#range").value;
    const qs = analyticsRangeQuery(days);
    let dash;
    try {
      dash = await api(`/analytics/dashboard${qs}`);
    } catch (e) { toast(e.message, "error"); return; }
    if (seq !== loadSeq) return;
    const summary = dash.summary || {};
    const ts = dash.revenue_timeseries || [];
    const top = dash.top_items || [];
    const byStatus = dash.orders_by_status || [];
    const hours = dash.peak_hours || [];

    kpisEl.innerHTML = "";
    [
      ["Revenue", fmtMoney(summary.revenue)],
      ["Orders", summary.orders_count || 0],
      ["Avg order value", fmtMoney(Math.round(summary.avg_order_value || 0))],
      ["Items sold", summary.items_sold || 0],
    ].forEach(([l, v]) => kpisEl.appendChild(el(`<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div></div>`)));

    const P = "#4f46e5";
    _charts.push(new Chart(content.querySelector("#revChart"), {
      type: "line",
      data: { labels: ts.map((t) => formatChartBucket(t.bucket, days)), datasets: [{ label: "Revenue", data: ts.map((t) => t.revenue), borderColor: P, backgroundColor: "rgba(79,70,229,0.1)", fill: true, tension: 0.3 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
    }));
    _charts.push(new Chart(content.querySelector("#topChart"), {
      type: "bar",
      data: { labels: top.map((t) => t.item), datasets: [{ label: "Qty", data: top.map((t) => t.quantity), backgroundColor: P }] },
      options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
    }));
    const statusColors = { placed: "#2563eb", accepted: "#4338ca", preparing: "#d97706", out_for_delivery: "#7c3aed", delivered: "#16a34a", cancelled: "#dc2626" };
    _charts.push(new Chart(content.querySelector("#statusChart"), {
      type: "doughnut",
      data: { labels: byStatus.map((s) => s.status), datasets: [{ data: byStatus.map((s) => s.count), backgroundColor: byStatus.map((s) => statusColors[s.status] || P) }] },
      options: { responsive: true, maintainAspectRatio: false },
    }));
    const hourMap = {}; hours.forEach((h) => (hourMap[h.hour] = h.count));
    _charts.push(new Chart(content.querySelector("#hoursChart"), {
      type: "bar",
      data: { labels: Array.from({ length: 24 }, (_, i) => i + "h"), datasets: [{ label: "Orders", data: Array.from({ length: 24 }, (_, i) => hourMap[i] || 0), backgroundColor: P }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
    }));
  }

  content.querySelector("#range").onchange = load;
  await load();
}

async function pageAdmin() {
  const content = el(`
    <div>
      <div class="page-head">
        <h2>Platform Admin</h2>
        <button class="btn btn-sm" id="provBtn" style="width:auto">+ Provision tenant</button>
      </div>
      <div class="kpi-grid" id="kpis"></div>
      <div class="card" style="margin-bottom:16px"><h3>Restaurants</h3>
        <table><thead><tr><th>Name</th><th>Slug</th><th>Owner</th><th>Status</th><th>Plan</th></tr></thead><tbody id="rows"></tbody></table>
      </div>
    </div>`);
  renderLayout("#/admin", content);
  content.querySelector("#kpis").innerHTML = loadingBlock(3);
  content.querySelector("#rows").innerHTML = `<tr><td colspan="5">${loadingBlock(3)}</td></tr>`;

  async function load() {
    let ov = {}, tenants = [];
    try { const dash = await api("/admin/dashboard"); ov = dash.overview || {}; tenants = dash.tenants || []; }
    catch (e) {
      try { [ov, tenants] = await Promise.all([api("/admin/overview"), api("/admin/tenants")]); }
      catch (err) { toast(err.message, "error"); return; }
    }
    const kpis = content.querySelector("#kpis");
    kpis.innerHTML = "";
    [
      ["Active tenants", ov.active_tenants || 0],
      ["Orders today", ov.orders_today || 0],
      ["Agent sessions", ov.agent_sessions || 0],
    ].forEach(([l, v]) => kpis.appendChild(el(`<div class="kpi"><div class="label">${l}</div><div class="value">${v}</div></div>`)));
    const rows = content.querySelector("#rows");
    rows.innerHTML = "";
    if (!tenants.length) { rows.appendChild(el(`<tr><td colspan="5"><div class="empty">No tenants yet.</div></td></tr>`)); return; }
    tenants.forEach((t) => rows.appendChild(el(`
      <tr><td><b>${esc(t.name)}</b></td><td>${esc(t.slug)}</td><td style="color:var(--muted)">${esc(t.owner_email)}</td>
      <td><span class="status-badge s-${t.status === "active" ? "delivered" : "preparing"}">${esc(t.status)}</span></td><td>${esc(t.plan)}</td></tr>`)));
  }

  content.querySelector("#provBtn").onclick = () => {
    const backdrop = el(`
      <div class="modal-backdrop">
        <form class="modal" id="provForm">
          <h3>Provision new restaurant</h3>
          <div class="field"><label>Restaurant name</label><input id="pName" required /></div>
          <div class="field"><label>Slug (subdomain)</label><input id="pSlug" pattern="[a-z0-9-]+" placeholder="kababjees" required /></div>
          <div class="field"><label>Owner email</label><input id="pEmail" type="email" required /></div>
          <div class="field"><label>Plan</label><select id="pPlan"><option value="free">Free</option><option value="pro">Pro</option></select></div>
          <div class="row">
            <button type="button" class="btn btn-ghost btn-sm" id="cancel">Cancel</button>
            <button type="submit" class="btn btn-sm" style="width:auto">Provision</button>
          </div>
        </form>
      </div>`);
    document.body.appendChild(backdrop);
    backdrop.querySelector("#cancel").onclick = () => backdrop.remove();
    backdrop.onclick = (e) => { if (e.target === backdrop) backdrop.remove(); };
    backdrop.querySelector("#provForm").onsubmit = async (e) => {
      e.preventDefault();
      try {
        await api("/admin/tenants", { method: "POST", body: JSON.stringify({
          name: backdrop.querySelector("#pName").value,
          slug: backdrop.querySelector("#pSlug").value,
          owner_email: backdrop.querySelector("#pEmail").value,
          plan: backdrop.querySelector("#pPlan").value,
        }) });
        toast("Provisioning started", "success");
        backdrop.remove();
        load();
      } catch (err) { toast(err.message, "error"); }
    };
  };

  await load();
}

// ---------- Router ----------
function defaultRoute() {
  return IS_ADMIN_PORTAL ? "#/admin" : "#/orders";
}

function router() {
  if (_ws) { try { _ws.close(); } catch {} _ws = null; }
  if (_wsReconnectTimer) { clearTimeout(_wsReconnectTimer); _wsReconnectTimer = null; }
  if (_wsConnectTimer) { clearTimeout(_wsConnectTimer); _wsConnectTimer = null; }
  if (_wsTimer) { clearTimeout(_wsTimer); _wsTimer = null; }
  stopWsPoll();
  destroyCharts();
  const hash = location.hash || "#/login";
  const authed = !!getToken();
  if (!authed && hash !== "#/login") {
    clearPageOverlays();
    location.hash = "#/login";
    return;
  }
  if (authed && hash === "#/login") { location.hash = defaultRoute(); return; }

  if (IS_ADMIN_PORTAL) {
    if (hash === "#/orders" || hash === "#/menu" || hash === "#/analytics") {
      location.hash = "#/admin"; return;
    }
    switch (hash) {
      case "#/login": return pageLogin();
      case "#/admin": return pageAdmin();
      default: location.hash = authed ? "#/admin" : "#/login";
    }
    return;
  }

  if (IS_TENANT_PORTAL) {
    if (hash === "#/admin") { location.hash = "#/orders"; return; }
    switch (hash) {
      case "#/login": return pageLogin();
      case "#/orders": return pageOrders();
      case "#/menu": return pageMenu();
      case "#/analytics": return pageAnalytics();
      default: location.hash = authed ? "#/orders" : "#/login";
    }
    return;
  }

  location.hash = "#/login";
}

window.addEventListener("hashchange", router);
window.addEventListener("DOMContentLoaded", router);
window.addEventListener("pageshow", (e) => {
  if (e.persisted) clearPageOverlays();
});
router();
