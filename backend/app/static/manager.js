const $ = (id) => document.getElementById(id);
const sar = (n) => `${Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 })} SAR`;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (n) => Number(n).toLocaleString("en-US", { maximumFractionDigits: 1 });
const TABS = [
  { id: "today", label: "Today", icon: "today" },
  { id: "sales", label: "Sales", icon: "sales" },
  { id: "orders", label: "Orders", icon: "orders" },
  { id: "stock", label: "Stock", icon: "stock" },
  { id: "more", label: "More", icon: "more" },
];
// sections reached from the More tab
const MORE = [
  { id: "deliveries", label: "Deliveries", icon: "delivery", sub: "Invoice photos, manual deliveries, POS upload" },
  { id: "forecast", label: "Forecast", icon: "sales", sub: "Next 7 days, tomorrow's prep, ingredients needed" },
  { id: "expenses", label: "Expenses", icon: "wallet", sub: "Costs and estimated profit" },
  { id: "routines", label: "Routines", icon: "check", sub: "Opening, mid-shift and closing checklists" },
  { id: "staff", label: "Staff", icon: "people", sub: "Shifts, attendance and hours" },
];
const SECTION = (id) => [...TABS, ...MORE].find((t) => t.id === id);
let expDays = 30;
let tab = location.hash.slice(1) || "today";
let status = {};
let salesDays = 14;

async function api(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const res = await fetch(path, { headers: isForm ? {} : { "Content-Type": "application/json" }, ...opts });
  if (res.status === 401) { location.href = "/login"; throw new Error("Signed out"); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  document.body.append(t);
  setTimeout(() => t.remove(), 3000);
}

async function renderTabs() {
  const today = await api("/api/today").catch(() => ({}));
  const active = MORE.some((m) => m.id === tab) ? "more" : tab;
  $("tabs").innerHTML = TABS.map((t) => `<button data-tab="${t.id}" ${t.id === active ? 'aria-current="page"' : ""}>${ICONS[t.icon]}${t.label}
    ${t.id === "orders" && today.drafts ? `<span class="dot">${today.drafts}</span>` : ""}${t.id === "stock" && today.low_stock ? `<span class="dot">${today.low_stock}</span>` : ""}</button>`).join("");
  $("tabs").querySelectorAll("button").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
}

function go(t) { tab = t; location.hash = t; render(); window.scrollTo(0, 0); }

async function render() {
  if (!SECTION(tab)) tab = "today";
  $("title").textContent = SECTION(tab).label;
  document.body.classList.toggle("has-hero", ["today", "forecast"].includes(tab));
  renderTabs();
  const view = $("view");
  try { view.innerHTML = await VIEWS[tab](); BIND[tab]?.(); }
  catch (e) { view.innerHTML = `<div class="panel section">${esc(e.message)}</div>`; }
}

function agentCard(run) {
  const when = run ? new Date(run.at + "Z").toLocaleString("en-GB", { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" }) : "";
  return `<div class="agent">
    <div class="head">${ICONS.spark}Stock-to-order agent</div>
    <div class="headline">${run ? esc(run.headline) : "No stock check yet today. Run one after closing, or any time."}</div>
    ${(run?.warnings || []).map((w) => `<div class="warn">${esc(w)}</div>`).join("")}
    ${run ? `<div class="meta">Last check ${when} · ${run.source === "ai" ? "written by Claude" : "rules mode"}</div>` : ""}
    <button id="run-agent">Run stock check now</button>
  </div>`;
}

const VIEWS = {
  async more() {
    return `<div class="section"><div class="panel">${MORE.map((m) => `<button class="more-row" data-go="${m.id}"><span class="ic">${ICONS[m.icon]}</span><span><b>${m.label}</b><br><span class="muted">${m.sub}</span></span>${ICONS.chevron}</button>`).join("")}</div></div>`;
  },

  async staff() {
    const [t, w] = await Promise.all([api("/api/staff/today"), api("/api/staff/week")]);
    window._st = w;
    const d = (iso, o) => new Date(iso + "T00:00").toLocaleDateString("en-GB", o);
    const label = { on_time: ["In", "received"], late: ["Late", "negative"], missing: ["Not in", "negative"], upcoming: ["Later", "draft"], done: ["Finished", "received"] };
    const n = (st) => t.shifts.filter((x) => x.status === st).length;
    const short = (s) => s ? s.replace(/:00/g, "") : "";
    const todayIdx = w.days.indexOf(t.date);
    return `<div class="hero" style="margin-top:12px">
        <div><div class="label">On shift now</div><div class="value num">${t.on_shift.length}</div></div>
        <div><div class="label">Shifts today</div><div class="value num">${t.shifts.length}</div></div>
        <div><div class="label">Late today</div><div class="value num" style="color:${n("late") ? "var(--warn)" : "inherit"}">${n("late")}</div></div>
        <div><div class="label">Not in</div><div class="value num" style="color:${n("missing") ? "var(--bad)" : "inherit"}">${n("missing")}</div></div>
      </div>
      <div class="section"><h2>Today · ${d(t.date, { weekday: "long", day: "numeric", month: "short" })}</h2><div class="panel">
        ${t.shifts.map((x) => `<div class="list-item"><span>${esc(x.staff)} · <span class="muted">${esc(x.role)}</span><br><span class="muted">${x.start}–${x.end}${x.clock_in ? ` · in ${x.clock_in}${x.late_min > 10 ? ` (${x.late_min} min late)` : ""}` : ""}${x.clock_out ? ` · out ${x.clock_out}` : ""}</span></span><span class="chip ${label[x.status][1]}">${label[x.status][0]}</span></div>`).join("") || '<div class="muted">No shifts today.</div>'}
        <div class="muted" style="font-size:13px;margin-top:10px">Staff clock in and out on the cashier iPad with their 4-digit PIN.</div>
      </div></div>
      <div class="section panel chart-card"><h3>Hours worked</h3><div class="sub">Last 7 days, from clock-in to clock-out</div><div id="c-hours"></div></div>
      <div class="section"><h2>This week's shifts</h2><div class="panel" style="overflow-x:auto">
        <table class="sched"><tr><th></th>${w.days.map((x, i) => `<th class="${i === todayIdx ? "now" : ""}">${d(x, { weekday: "short" })}<br><span class="muted">${new Date(x + "T00:00").getDate()}</span></th>`).join("")}</tr>
        ${w.staff.map((m) => `<tr><th>${esc(m.name)}</th>${m.shifts.map((s, i) => `<td class="${i === todayIdx ? "now" : ""}">${s ? `<span class="pill ${s.startsWith("10") ? "am" : "pm"}">${short(s)}</span>` : '<span class="muted">Off</span>'}</td>`).join("")}</tr>`).join("")}</table>
      </div></div>
      <div class="section"><h2>Set a shift</h2><div class="panel form">
        <label class="field">Who<select id="s-who">${w.staff.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join("")}</select></label>
        <label class="field">Day<select id="s-day">${w.days.map((x) => `<option value="${x}">${d(x, { weekday: "long", day: "numeric", month: "short" })}</option>`).join("")}</select></label>
        <label class="field">Shift<select id="s-time"><option value="10:00-17:00">Morning 10:00–17:00</option><option value="17:00-00:00">Evening 17:00–00:00</option></select></label>
        <button class="solid" id="s-save">Save shift</button>
      </div></div>
      <div class="section"><h2>Add a staff member</h2><div class="panel form">
        <label class="field">Name<input id="n-name" type="text" maxlength="120"></label>
        <label class="field">Role<input id="n-role" type="text" maxlength="60" placeholder="Cashier, Crepe maker…"></label>
        <label class="field">4-digit PIN for clocking in<input id="n-pin" type="text" inputmode="numeric" maxlength="4" pattern="\\d{4}"></label>
        <button class="solid" id="n-save">Add staff member</button>
      </div></div>`;
  },

  async routines() {
    const [r, h] = await Promise.all([api("/api/routines"), api("/api/routines/history?days=7")]);
    window._rt = h;
    return r.map((x) => `<div class="section"><h2>${x.label} · due ${x.due}</h2><div class="panel">
        <div class="rt-head"><div class="meter"><i style="width:${x.total ? (100 * x.done) / x.total : 0}%"></i></div><b class="num">${x.done}/${x.total}</b>${x.overdue ? '<span class="chip negative">Late</span>' : x.done === x.total ? '<span class="chip received">Done</span>' : ""}</div>
        ${x.tasks.map((t) => `<div class="task ${t.done ? "done" : ""}"><button class="tick" data-task="${t.id}" aria-pressed="${t.done}" aria-label="${esc(t.text)}">${ICONS.check}</button><span>${esc(t.text)}${t.done ? `<br><span class="muted">${esc(t.done_by || "")} · ${t.done_at}</span>` : ""}</span><button class="x" data-rmtask="${t.id}" aria-label="Remove task">×</button></div>`).join("")}
      </div></div>`).join("") + `
      <div class="section panel chart-card"><h3>Last 7 days</h3><div class="sub">% of each checklist done</div><div id="c-rt"></div></div>
      <div class="section"><h2>Add a task</h2><div class="panel form">
        <label class="field">Checklist<select id="t-r"><option value="opening">Opening</option><option value="midday">Mid-shift</option><option value="closing">Closing</option></select></label>
        <label class="field">Task<input id="t-text" type="text" maxlength="160"></label>
        <button class="solid" id="t-save">Add task</button>
      </div></div>`;
  },

  async forecast() {
    const f = await api("/api/forecast");
    window._fc = f;
    const wk = f.days.reduce((a, d) => a + d.sales, 0);
    const day = (iso, o = { weekday: "short", day: "numeric", month: "short" }) => new Date(iso + "T00:00").toLocaleDateString("en-GB", o);
    const short = f.ingredients.filter((i) => i.runs_out);
    return `<div class="hero">
        <div><div class="label">Next 7 days</div><div class="value num">${sar(wk)}</div></div>
        <div><div class="label">Tomorrow</div><div class="value num">${sar(f.days[1].sales)}</div></div>
        <div><div class="label">Tomorrow orders</div><div class="value num">${f.days[1].orders}</div></div>
        <div><div class="label">Will run short</div><div class="value num" style="color:${short.length ? "var(--bad)" : "var(--ok)"}">${short.length}</div></div>
      </div>
      <div class="section"><div class="agent">
        <div class="head">${ICONS.spark}Forecast</div>
        <div class="headline" style="font-size:16px">${short.length ? `${short.length} ${short.length === 1 ? "ingredient" : "ingredients"} will run out this week at the expected sales: ${short.slice(0, 3).map((i) => `${esc(i.name)} (${day(i.runs_out, { weekday: "short" })})`).join(", ")}.` : "Stock covers the expected sales for the next 7 days."}</div>
        <div class="meta">${esc(f.method)}</div>
      </div></div>
      <div class="section panel chart-card"><h3>Sales: last 14 days and next 7</h3><div class="sub">SAR · solid line is actual, dashed line is the forecast</div><div id="c-fc"></div>
        <details class="table"><summary>Show as table</summary><table><tr><th>Day</th><th>Forecast</th><th>Range</th></tr>${f.days.map((d) => `<tr><td>${day(d.date)}</td><td class="num">${sar(d.sales)}</td><td class="num">${sar(d.low)}–${sar(d.high)}</td></tr>`).join("")}</table></details></div>
      <div class="section panel chart-card"><h3>Tomorrow's prep</h3><div class="sub">Expected items sold, ${day(f.days[1].date, { weekday: "long" })}</div><div id="c-prep"></div></div>
      <div class="section"><h2>Ingredients for the next 7 days</h2><div class="panel">
        ${f.ingredients.map((i) => `<div class="list-item"><span>${esc(i.name)}<br><span class="muted">Need ${fmt(Math.ceil(i.need))} ${i.unit} · on hand ${fmt(i.on_hand)} ${i.unit}</span></span>${i.runs_out ? `<span class="chip negative">Runs out ${day(i.runs_out, { weekday: "short" })}</span>` : '<span class="chip received">Enough</span>'}</div>`).join("")}
      </div></div>`;
  },

  async expenses() {
    const e = await api(`/api/expenses?days=${expDays}`);
    window._exp = e;
    const margin = e.sales ? Math.round((100 * e.profit) / e.sales) : 0;
    const kindLabel = { one_off: "One-off", purchase: "Supplier delivery" };
    return `<div class="section" style="display:flex;justify-content:space-between;align-items:center">
        <h2 style="margin:0 0 0 4px;font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)">Last ${e.days} days</h2>
        <div class="seg" role="group" aria-label="Date range">${[7, 14, 30].map((d) => `<button data-edays="${d}" aria-pressed="${d === expDays}">${d} days</button>`).join("")}</div></div>
      <div class="hero" style="margin-top:12px">
        <div><div class="label">Sales</div><div class="value num">${sar(e.sales)}</div></div>
        <div><div class="label">Costs</div><div class="value num">${sar(e.costs)}</div></div>
        <div><div class="label">Est. profit</div><div class="value num" style="color:${e.profit >= 0 ? "var(--ok)" : "var(--bad)"}">${sar(e.profit)}</div></div>
        <div><div class="label">Margin</div><div class="value num">${margin}%</div></div>
      </div>
      <div class="section"><div class="agent">
        <div class="head">${ICONS.spark}Expenses check</div>
        ${e.notes.map((n) => `<div class="headline" style="font-size:16px">${esc(n)}</div>`).join("") || '<div class="headline">No sales in this period yet.</div>'}
        <div class="meta">Profit = sales − ingredient cost of what was sold − monthly costs for ${e.days} days − one-off costs.</div>
      </div></div>
      <div class="section panel chart-card"><h3>Where the money goes</h3><div class="sub">SAR, last ${e.days} days</div><div id="c-exp"></div>
        <details class="table"><summary>Show as table</summary><table><tr><th>Cost</th><th>SAR</th></tr>${e.by_category.map((c) => `<tr><td>${esc(c.category)}</td><td class="num">${sar(c.amount)}</td></tr>`).join("")}</table></details></div>
      <div class="section"><h2>Monthly costs</h2><div class="panel">
        ${e.fixed.map((x) => `<div class="list-item"><span>${esc(x.category)}<br><span class="muted">${esc(x.note || "")}</span></span><span style="display:flex;gap:10px;align-items:center"><b class="num">${sar(x.amount)}/mo</b><button class="secondary-btn" data-del="${x.id}">Remove</button></span></div>`).join("") || '<div class="muted">No monthly costs yet.</div>'}
      </div></div>
      <div class="section"><h2>Payments</h2><div class="panel">
        ${e.entries.map((x) => `<div class="list-item"><span>${esc(x.category)} · ${esc(x.note || "")}<br><span class="muted">${new Date(x.date + "T00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" })} · ${kindLabel[x.kind]}</span></span><span style="display:flex;gap:10px;align-items:center"><b class="num">${sar(x.amount)}</b>${x.kind === "purchase" ? "" : `<button class="secondary-btn" data-del="${x.id}">Remove</button>`}</span></div>`).join("") || '<div class="muted">No payments in this period.</div>'}
        <div class="muted" style="font-size:13px;margin-top:10px">Paid to suppliers in this period: <b>${sar(e.purchases_paid)}</b>. Deliveries are added here automatically at cost.</div>
      </div></div>
      <div class="section"><h2>Add an expense</h2><div class="panel form">
        <label class="field">Type<select id="x-kind"><option value="one_off">One-off payment</option><option value="fixed">Monthly cost</option></select></label>
        <label class="field">Category<select id="x-cat">${e.categories.map((c) => `<option>${c}</option>`).join("")}</select></label>
        <label class="field">Amount (SAR)<input id="x-amt" type="number" min="0" step="any" inputmode="decimal"></label>
        <label class="field">Note (optional)<input id="x-note" type="text" maxlength="200"></label>
        <button class="solid" id="x-save">Add expense</button>
      </div></div>`;
  },

  async today() {
    const [t, ins, runs, devs, ov] = await Promise.all([api("/api/today"), api("/api/insights/cashier"), api("/api/agents/runs"), api("/api/devices"), api("/api/overview")]);
    const brief = runs.find((r) => r.agent === "overview");
    const rate = ins.acceptance_rate == null ? "–" : `${Math.round(ins.acceptance_rate * 100)}%`;
    return `<div class="hero">
        <div><div class="label">Sales</div><div class="value num">${sar(t.sales)}</div></div>
        <div><div class="label">Orders</div><div class="value num">${t.orders}</div></div>
        <div><div class="label">Avg. ticket</div><div class="value num">${sar(t.avg_ticket)}</div></div>
        <div><div class="label">Helper sales</div><div class="value num">${sar(t.suggested_sales)}</div></div>
      </div>
      <div class="section"><div class="agent">
        <div class="head">${ICONS.spark}Manager overview</div>
        <div class="headline">${brief ? esc(brief.headline) : "Tap below for a briefing across sales, stock, orders and costs."}</div>
        ${(brief?.points || []).map((p) => `<div class="meta" style="font-size:14px;color:#fff;opacity:.9">• ${esc(p)}</div>`).join("")}
        ${brief ? `<div class="meta">Last briefing ${new Date(brief.at + "Z").toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })} · ${brief.source === "ai" ? "written by Claude" : "rules mode"}</div>` : ""}
        <button id="run-overview">Brief me now</button>
      </div></div>
      <div class="section"><h2>Needs you</h2><div class="panel">
        ${ov.priorities.map((p) => `<button class="more-row need ${p.level}" ${p.go ? `data-go="${p.go}"` : "disabled"}><span class="lvl"></span><span>${esc(p.text)}</span>${p.go ? ICONS.chevron : ""}</button>`).join("")}
      </div></div>
      <div class="section"><div class="hero" style="margin:0">
        <div><div class="label">Forecast tomorrow</div><div class="value num">${sar(ov.facts.forecast_tomorrow)}</div></div>
        <div><div class="label">Profit, 7 days</div><div class="value num" style="color:${ov.facts.profit_7d >= 0 ? "var(--ok)" : "var(--bad)"}">${sar(ov.facts.profit_7d)}</div></div>
      </div></div>
      <div class="section">${agentCard(runs.find((r) => r.agent === "stock"))}</div>
      <div class="section"><h2>Cashier helper</h2><div class="panel">
        <div class="hero" style="margin:0;box-shadow:none;padding:0;grid-template-columns:repeat(3,minmax(0,1fr))">
          <div><div class="label">Shown</div><div class="value num">${ins.shown}</div></div>
          <div><div class="label">Accepted</div><div class="value num">${ins.accepted}</div></div>
          <div><div class="label">Rate</div><div class="value num">${rate}</div></div>
        </div>
        <div style="margin-top:14px">${ins.top_accepted.length ? ins.top_accepted.map((x) => `<div class="list-item"><span>${esc(x.name)}</span><b class="num">${x.count}×</b></div>`).join("") : '<div class="muted">No suggestions accepted yet.</div>'}</div>
        <div class="muted" style="font-size:13px;margin-top:10px">Add-on revenue from accepted suggestions, all time: <b>${sar(ins.added_revenue)}</b></div>
      </div></div>
      <div class="section"><h2>Cashier devices</h2><div class="panel">
        <div class="muted" style="font-size:14px;margin-bottom:8px">The cashier account only works on devices paired here.</div>
        ${devs.map((d) => `<div class="list-item"><span>${esc(d.name)}<br><span class="muted">${d.paired ? "Paired" : "Waiting for code"}</span></span><button class="secondary-btn" data-revoke="${d.id}">Remove</button></div>`).join("") || '<div class="muted">No cashier device yet.</div>'}
        <div id="pair-out"></div>
        <div class="btns" style="display:flex;gap:8px;margin-top:12px"><button class="pair-btn" id="pair-new">Pair a cashier iPad</button><button class="secondary-btn" id="logout">Sign out</button></div>
      </div></div>`;
  },

  async sales() {
    const s = await api(`/api/sales/summary?days=${salesDays}`);
    window._sales = s;
    const total = s.daily.reduce((a, d) => a + d.sales, 0), orders = s.daily.reduce((a, d) => a + d.orders, 0);
    const best = s.daily.reduce((a, d) => (d.sales > a.sales ? d : a), s.daily[0]);
    const helper = s.daily.reduce((a, d) => a + d.helper_sales, 0);
    const day = (iso) => new Date(iso + "T00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
    return `<div class="section" style="display:flex;justify-content:space-between;align-items:center">
        <h2 style="margin:0 0 0 4px;font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)">Last ${salesDays} days</h2>
        <div class="seg" role="group" aria-label="Date range">${[7, 14, 30].map((d) => `<button data-days="${d}" aria-pressed="${d === salesDays}">${d} days</button>`).join("")}</div></div>
      <div class="hero" style="margin-top:12px">
        <div><div class="label">Sales</div><div class="value num">${sar(total)}</div></div>
        <div><div class="label">Orders</div><div class="value num">${orders.toLocaleString("en-US")}</div></div>
        <div><div class="label">Avg. per day</div><div class="value num">${sar(total / s.daily.length)}</div></div>
        <div><div class="label">Best day</div><div class="value num" style="font-size:20px">${day(best.date)}<br><small>${sar(best.sales)}</small></div></div>
      </div>
      <div class="section panel chart-card"><h3>Sales by day</h3><div class="sub">SAR, all channels</div><div id="c-daily"></div>
        <details class="table"><summary>Show as table</summary><table><tr><th>Day</th><th>Orders</th><th>Sales</th></tr>${s.daily.map((d) => `<tr><td>${day(d.date)}</td><td class="num">${d.orders}</td><td class="num">${sar(d.sales)}</td></tr>`).join("")}</table></details></div>
      <div class="panel chart-card"><h3>Average order value</h3><div class="sub">SAR per order, by day</div><div id="c-aov"></div></div>
      <div class="panel chart-card"><h3>Sales by hour today</h3><div class="sub">SAR, cashier orders</div><div id="c-hour"></div></div>
      <div class="panel chart-card"><h3>Top items</h3><div class="sub">By sales, last ${salesDays} days</div><div id="c-top"></div></div>
      <div class="panel chart-card"><h3>Sales by category</h3><div class="sub">Share of sales, last ${salesDays} days</div><div id="c-cat"></div>
        <details class="table"><summary>Show as table</summary><table><tr><th>Category</th><th>Sales</th></tr>${s.categories.map((c) => `<tr><td>${c.category}</td><td class="num">${sar(c.sales)}</td></tr>`).join("")}</table></details></div>
      <div class="panel chart-card"><h3>Cashier helper add-on sales</h3><div class="sub">SAR from accepted suggestions · ${sar(helper)} in total</div><div id="c-helper"></div></div>`;
  },

  async orders() {
    const pos = await api("/api/purchase-orders");
    if (!pos.length) return `<div class="section">${agentCard(null)}</div><div class="section panel empty">No supplier orders yet.</div>`;
    const card = (po) => {
      const draft = po.status === "draft";
      const cost = po.lines.reduce((s, l) => s + l.est_cost, 0);
      return `<div class="panel po" data-id="${po.id}">
        <div class="top"><span class="sup">${esc(po.supplier)}</span><span class="muted num">#${po.id}</span><span class="chip ${po.status}">${po.status}</span></div>
        ${po.note ? `<div class="note">${ICONS.spark.replace("<svg", '<svg width="14" style="vertical-align:-2px;margin-right:4px"')}${esc(po.note)}</div>` : ""}
        <table>${po.lines.map((l) => `<tr><td>${esc(l.ingredient)}</td><td class="q">${draft
          ? `<input class="qty num" type="number" min="0" step="any" value="${l.qty}" data-line="${l.id}" aria-label="Quantity of ${esc(l.ingredient)}"> ${l.unit}`
          : `<b class="num">${fmt(l.qty)}</b> ${l.unit}`}</td></tr>`).join("")}
          <tr><td class="muted">Estimated cost</td><td class="q"><b class="num">${sar(cost)}</b></td></tr></table>
        ${draft ? `<div class="btns"><button class="approve">Approve and send</button><button class="reject">Reject</button></div>` : ""}
        ${draft && po.channel === "whatsapp" ? '<div class="muted" style="font-size:13px;margin-top:8px">This supplier takes orders on WhatsApp.</div>' : ""}
        ${po.status === "sent" ? `<div class="btns">${po.whatsapp_link ? `<a class="wa" href="${esc(po.whatsapp_link)}" target="_blank" rel="noopener">${ICONS.whatsapp}Send on WhatsApp</a>` : ""}<button class="approve receive">Mark as delivered</button></div>` : ""}
      </div>`;
    };
    const drafts = pos.filter((p) => p.status === "draft"), rest = pos.filter((p) => p.status !== "draft");
    return `${drafts.length ? `<div class="section"><h2>Waiting for your approval</h2>${drafts.map(card).join("")}</div>` : `<div class="section">${agentCard(null)}</div>`}
      ${rest.length ? `<div class="section"><h2>History</h2>${rest.map(card).join("")}</div>` : ""}`;
  },

  async stock() {
    const [rows, runs] = await Promise.all([api("/api/stock"), api("/api/agents/runs")]);
    const order = { negative: 0, low: 1, ok: 2 };
    rows.sort((a, b) => order[a.status] - order[b.status] || a.name.localeCompare(b.name));
    const row = (r) => {
      const pct = Math.max(0, Math.min(100, (r.on_hand / r.par_level) * 100));
      const minPct = (r.min_level / r.par_level) * 100;
      return `<div class="stock-row"><span class="n">${esc(r.name)}</span><span class="chip ${r.status}">${r.status === "ok" ? "OK" : r.status}</span>
        <div class="meter ${r.status}"><i style="width:${pct}%"></i><b style="left:${minPct}%"></b></div>
        <span class="d num">${fmt(r.on_hand)} ${r.unit} on hand · min ${fmt(r.min_level)} · ${r.days_left == null ? "no recent use" : `${r.days_left} days left`} · ${esc(r.supplier)}</span></div>`;
    };
    return `<div class="section">${agentCard(runs.find((r) => r.agent === "stock"))}</div>
      <div class="section"><h2>Ingredients</h2><div class="panel">${rows.map(row).join("")}</div></div>
      <div class="section"><h2>Monthly count</h2><div class="panel form">
        <label class="field">Ingredient<select id="c-ing">${rows.map((r) => `<option value="${r.id}">${esc(r.name)} (${r.unit})</option>`).join("")}</select></label>
        <label class="field">Counted quantity<input id="c-qty" type="number" min="0" step="any" inputmode="decimal"></label>
        <button class="solid" id="c-save">Save count</button>
      </div></div>`;
  },

  async deliveries() {
    const [rows, mails] = await Promise.all([api("/api/stock"), api("/api/outbox")]);
    const opts = rows.map((r) => `<option value="${r.id}">${esc(r.name)} (${r.unit})</option>`).join("");
    return `<div class="section"><h2>Invoice photo</h2><div class="panel">
        <div class="upload">${ICONS.delivery.replace("<svg", '<svg width="34"')}
          <div>${status.ai_enabled ? "Take a photo of the supplier invoice. Claude reads the lines and you confirm them." : "Reading invoice photos needs the AI key. Use manual entry below for now."}</div>
          <label ${status.ai_enabled ? "" : 'style="opacity:.5;pointer-events:none"'}>Take or upload photo<input id="inv" type="file" accept="image/*" capture="environment" hidden></label>
        </div><div id="inv-out"></div></div></div>
      <div class="section"><h2>Manual delivery</h2><div class="panel form">
        <label class="field">Ingredient<select id="d-ing">${opts}</select></label>
        <label class="field">Quantity received<input id="d-qty" type="number" min="0" step="any" inputmode="decimal"></label>
        <label class="field">Invoice number (optional)<input id="d-ref" type="text"></label>
        <button class="solid" id="d-save">Add to stock</button>
      </div></div>
      <div class="section"><h2>POS daily report</h2><div class="panel form">
        <div class="muted" style="font-size:14px">Upload the day's sales as CSV with columns <b>item,qty</b> if the POS is not connected.</div>
        <label class="field">CSV file<input id="pos" type="file" accept=".csv,text/csv"></label>
      </div></div>
      <div class="section"><h2>Messages to suppliers</h2><div class="panel">${mails.length ? mails.slice(0, 8).map((m) => `<div class="list-item"><span>${esc(m.subject)}<br><span class="muted">${esc(m.to)}</span></span><span class="chip ${m.status === "sent" ? "received" : m.status === "failed" ? "negative" : "draft"}">${m.status === "link" ? "WhatsApp" : m.status}</span></div>`).join("") : '<div class="muted">No emails yet.</div>'}</div></div>`;
  },
};

function bindAgent() {
  const b = $("run-agent");
  if (!b) return;
  b.onclick = async () => {
    b.disabled = true; b.textContent = "Checking stock…";
    try { const r = await api("/api/agents/stock/run", { method: "POST" }); toast(r.headline); go(r.order_ids.length ? "orders" : tab); }
    catch (e) { toast(e.message, true); b.disabled = false; b.textContent = "Run stock check now"; }
  };
}

const BIND = {
  more() {
    document.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
  },
  staff() {
    const w = window._st;
    Charts.bars($("c-hours"), w.staff.map((m) => ({ value: m.hours_7d, label: m.name, tip: `${esc(m.name)}<br><b>${m.hours_7d} h</b> · late ${m.late_7d}×` })), { unit: " h" });
    $("s-save").onclick = async () => {
      const [start, end] = $("s-time").value.split("-");
      await api("/api/shifts", { method: "POST", body: JSON.stringify({ staff_id: +$("s-who").value, date: $("s-day").value, start, end }) });
      toast("Shift saved"); render();
    };
    $("n-save").onclick = async () => {
      const name = $("n-name").value.trim(), role = $("n-role").value.trim(), pin = $("n-pin").value.trim();
      if (!name || !role || !/^\d{4}$/.test(pin)) return toast("Enter a name, a role and a 4-digit PIN", true);
      try { await api("/api/staff", { method: "POST", body: JSON.stringify({ name, role, pin }) }); toast(`${name} added`); render(); } catch (e) { toast(e.message, true); }
    };
  },
  routines() {
    const h = window._rt, d = (iso) => new Date(iso + "T00:00");
    const rows = [{ key: "opening", label: "Opening" }, { key: "midday", label: "Mid-shift" }, { key: "closing", label: "Closing" }];
    Charts.heatmap($("c-rt"), rows, h.map((x) => ({ ...x, label: d(x.date).toLocaleDateString("en-GB", { weekday: "narrow" }) + d(x.date).getDate() })), (r, c) => c[r.key],
      { tipFor: (r, c, v) => `${r.label} · ${d(c.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}<br><b>${Math.round(v * 100)}%</b> done` });
    document.querySelectorAll("[data-task]").forEach((b) => (b.onclick = async () => { await api(`/api/routines/tasks/${b.dataset.task}/toggle`, { method: "POST", body: "{}" }); render(); }));
    document.querySelectorAll("[data-rmtask]").forEach((b) => (b.onclick = async () => { await api(`/api/routines/tasks/${b.dataset.rmtask}`, { method: "DELETE" }); toast("Task removed"); render(); }));
    $("t-save").onclick = async () => {
      const text = $("t-text").value.trim();
      if (!text) return toast("Write the task", true);
      await api("/api/routines/tasks", { method: "POST", body: JSON.stringify({ routine: $("t-r").value, text }) });
      toast("Task added"); render();
    };
  },
  forecast() {
    const f = window._fc;
    const d = (iso) => new Date(iso + "T00:00");
    const tip = (iso, v, kind) => `${d(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}<br><b>${sar(v)}</b> ${kind}`;
    const series = [...f.actual.map((a) => ({ value: a.sales, label: d(a.date).getDate(), tip: tip(a.date, a.sales, "actual") })),
      ...f.days.map((x) => ({ value: x.sales, label: d(x.date).getDate(), tip: `${tip(x.date, x.sales, "forecast")}<br>range ${sar(x.low)}–${sar(x.high)}` }))];
    Charts.line($("c-fc"), series, { labelEvery: 3, dashFrom: f.actual.length });
    Charts.bars($("c-prep"), f.tomorrow_items.map((i) => ({ value: i.qty, label: i.name, tip: `${esc(i.name)}<br><b>${i.qty}</b> expected` })));
  },
  expenses() {
    const e = window._exp;
    Charts.bars($("c-exp"), e.by_category.map((c) => ({ value: c.amount, label: c.category, tip: `${esc(c.category)}<br><b>${sar(c.amount)}</b>${e.sales ? ` · ${Math.round((100 * c.amount) / e.sales)}% of sales` : ""}` })));
    document.querySelectorAll("[data-edays]").forEach((b) => (b.onclick = () => { expDays = +b.dataset.edays; render(); }));
    document.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => { await api(`/api/expenses/${b.dataset.del}`, { method: "DELETE" }); toast("Expense removed"); render(); }));
    $("x-save").onclick = async () => {
      const amount = parseFloat($("x-amt").value);
      if (!(amount > 0)) return toast("Enter the amount", true);
      await api("/api/expenses", { method: "POST", body: JSON.stringify({ kind: $("x-kind").value, category: $("x-cat").value, amount, note: $("x-note").value || null }) });
      toast("Expense added"); render();
    };
  },
  sales() {
    const s = window._sales;
    const day = (iso) => new Date(iso + "T00:00");
    const every = s.daily.length > 14 ? 5 : s.daily.length > 7 ? 2 : 1;
    Charts.line($("c-daily"), s.daily.map((d) => ({ value: d.sales, label: day(d.date).getDate(), tip: `${day(d.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}<br><b>${sar(d.sales)}</b> · ${d.orders} orders` })), { labelEvery: every });
    Charts.line($("c-aov"), s.daily.map((d) => { const v = d.orders ? d.sales / d.orders : 0; return { value: v, label: day(d.date).getDate(), tip: `${day(d.date).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}<br><b>${sar(v)}</b> per order` }; }), { height: 150, labelEvery: every, area: false });
    const hours = Array.from({ length: 16 }, (_, i) => i + 8).map((h) => ({ h, v: 0, n: 0 }));
    s.today_orders.forEach((o) => { const h = new Date(o.at).getHours(); const b = hours.find((x) => x.h === h); if (b) { b.v += o.total; b.n += 1; } });
    Charts.columns($("c-hour"), hours.map((b) => ({ value: b.v, label: b.h % 2 === 0 ? `${b.h}` : "", tip: `${b.h}:00–${b.h + 1}:00<br><b>${sar(b.v)}</b> · ${b.n} orders` })), { height: 160 });
    Charts.bars($("c-top"), s.top_items.map((t) => ({ value: t.sales, label: t.name, tip: `${t.name}<br><b>${sar(t.sales)}</b> · ${t.qty} sold` })));
    const cats = s.categories.length > 5 ? [...s.categories.slice(0, 4), { category: "Other", sales: s.categories.slice(4).reduce((a, c) => a + c.sales, 0) }] : s.categories;
    Charts.donut($("c-cat"), cats.map((c) => ({ value: c.sales, label: c.category, tip: `${c.category}<br><b>${sar(c.sales)}</b>` })), { center: "SAR" });
    Charts.columns($("c-helper"), s.daily.map((d) => ({ value: d.helper_sales, label: day(d.date).getDate(), tip: `${day(d.date).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}<br><b>${sar(d.helper_sales)}</b> from suggestions` })), { height: 140, labelEvery: every, color: getComputedStyle(document.documentElement).getPropertyValue("--chart-2").trim() || undefined });
    document.querySelectorAll("[data-days]").forEach((b) => (b.onclick = () => { salesDays = +b.dataset.days; render(); }));
  },
  today() {
    bindAgent();
    document.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
    $("run-overview").onclick = async (ev) => {
      ev.target.disabled = true; ev.target.textContent = "Reading every section…";
      try { await api("/api/agents/overview/run", { method: "POST" }); render(); } catch (e) { toast(e.message, true); ev.target.disabled = false; }
    };
    $("logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.href = "/login"; };
    $("pair-new").onclick = async () => {
      const r = await api("/api/devices", { method: "POST", body: JSON.stringify({ name: "Cashier iPad" }) });
      $("pair-out").innerHTML = `<div style="margin-top:12px"><div class="code num">${r.code}</div><div class="muted" style="font-size:13px;margin-top:8px;text-align:center">On the iPad, open Restaura, tap "Pair as cashier iPad" and enter this code. It expires in ${r.minutes} minutes.</div></div>`;
    };
    document.querySelectorAll("[data-revoke]").forEach((b) => (b.onclick = async () => { await api(`/api/devices/${b.dataset.revoke}/revoke`, { method: "POST" }); toast("Device removed"); render(); }));
  },
  stock() {
    bindAgent();
    $("c-save").onclick = async () => {
      const qty = parseFloat($("c-qty").value);
      if (isNaN(qty)) return toast("Enter the counted quantity", true);
      const r = await api("/api/stock/count", { method: "POST", body: JSON.stringify([{ ingredient_id: +$("c-ing").value, counted: qty }]) });
      const [name, diff] = Object.entries(r.adjustments)[0];
      toast(`${name} corrected by ${diff > 0 ? "+" : ""}${fmt(diff)}`); render();
    };
  },
  orders() {
    bindAgent();
    document.querySelectorAll(".po").forEach((el) => {
      const id = el.dataset.id;
      el.querySelector(".approve:not(.receive)")?.addEventListener("click", async (ev) => {
        ev.target.disabled = true;
        const edits = [...el.querySelectorAll("input.qty")].map((i) => ({ line_id: +i.dataset.line, qty: parseFloat(i.value) || 0 }));
        try { const r = await api(`/api/purchase-orders/${id}/approve`, { method: "POST", body: JSON.stringify(edits) });
          if (r.whatsapp_link) { toast("Approved. Tap Send on WhatsApp to message the supplier."); render(); return; }
          toast(r.email.status === "sent" ? `Sent to ${r.email.to}` : r.email.status === "logged" ? "Approved. Email logged (no mail server set)" : `Approved, but email failed: ${r.email.error}`, r.email.status === "failed"); render(); }
        catch (e) { toast(e.message, true); ev.target.disabled = false; }
      });
      el.querySelector(".reject")?.addEventListener("click", async () => { await api(`/api/purchase-orders/${id}/reject`, { method: "POST" }); toast("Order rejected"); render(); });
      el.querySelector(".receive")?.addEventListener("click", async () => {
        const po = (await api("/api/purchase-orders")).find((p) => p.id == id);
        await api(`/api/purchase-orders/${id}/receive`, { method: "POST", body: JSON.stringify({ lines: po.lines.map((l) => ({ ingredient_id: l.ingredient_id, qty: l.qty })) }) });
        toast("Delivery added to stock"); render();
      });
    });
  },
  deliveries() {
    $("d-save").onclick = async () => {
      const qty = parseFloat($("d-qty").value);
      if (!(qty > 0)) return toast("Enter the quantity received", true);
      await api("/api/deliveries", { method: "POST", body: JSON.stringify({ lines: [{ ingredient_id: +$("d-ing").value, qty }], invoice_ref: $("d-ref").value || null }) });
      toast("Added to stock"); render();
    };
    $("pos").onchange = async (e) => {
      const fd = new FormData(); fd.append("file", e.target.files[0]);
      try { const r = await api("/api/sales/import", { method: "POST", body: fd }); toast(`Imported ${r.lines} lines · ${sar(r.total)}`); }
      catch (err) { toast(err.message, true); }
    };
    $("inv").onchange = async (e) => {
      const out = $("inv-out");
      out.innerHTML = '<p class="muted">Reading the invoice…</p>';
      const fd = new FormData(); fd.append("file", e.target.files[0]);
      try {
        const r = await api("/api/invoices/read", { method: "POST", body: fd });
        const ok = r.lines.filter((l) => l.ingredient_id && l.qty_in_unit);
        out.innerHTML = `<div class="po" style="margin-top:12px"><div class="top"><span class="sup">${esc(r.supplier_name || "Supplier")}</span><span class="muted">${esc(r.invoice_number || "")}</span></div>
          <table>${r.lines.map((l) => `<tr><td>${esc(l.description)}${l.ingredient ? `<br><span class="muted">→ ${esc(l.ingredient)}</span>` : '<br><span class="muted">not matched</span>'}</td><td class="q">${l.qty_in_unit ?? "?"}</td></tr>`).join("")}</table>
          ${r.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("")}
          ${ok.length ? `<div class="btns"><button class="approve" id="inv-ok">Add ${ok.length} matched line(s) to stock</button></div>` : ""}</div>`;
        $("inv-ok")?.addEventListener("click", async () => {
          await api("/api/deliveries", { method: "POST", body: JSON.stringify({ lines: ok.map((l) => ({ ingredient_id: l.ingredient_id, qty: l.qty_in_unit })), invoice_ref: r.invoice_number }) });
          toast("Delivery added to stock"); render();
        });
      } catch (err) { out.innerHTML = ""; toast(err.message, true); }
    };
  },
};

(async () => {
  status = await api("/api/status");
  $("store").textContent = `${status.store} · ${new Date().toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}`;
  $("ai-badge").textContent = status.ai_enabled ? "AI on" : "Rules mode";
  $("ai-badge").classList.toggle("on", status.ai_enabled);
  window.onhashchange = () => { const t = location.hash.slice(1); if (t && t !== tab && VIEWS[t]) { tab = t; render(); } };
  render();
})();
