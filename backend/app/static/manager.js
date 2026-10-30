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
  { id: "evaluation", label: "Agent evaluation", icon: "gauge", sub: "How the AI agents score on data they have never seen" },
  { id: "devices", label: "Cashier iPads", icon: "device", sub: "Pair or remove the iPads the cashier signs in on" },
];
// pages reached from a link, not from the tab bar; they show a back arrow
const SUB = [{ id: "steps", label: "Stock agent", icon: "stock", back: "today" }];
const SECTION = (id) => [...TABS, ...MORE, ...SUB].find((t) => t.id === id);
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
  const active = MORE.some((m) => m.id === tab) ? "more" : SUB.find((x) => x.id === tab)?.back || tab;
  $("tabs").innerHTML = TABS.map((t) => `<button data-tab="${t.id}" ${t.id === active ? 'aria-current="page"' : ""}><span class="ti">${ICONS[t.icon]}</span>${t.label}
    ${t.id === "orders" && today.changed_drafts ? `<span class="dot warn" aria-label="An order needs a look">!</span>` : t.id === "orders" && today.drafts ? `<span class="dot">${today.drafts}</span>` : ""}${t.id === "stock" && today.low_stock ? `<span class="dot">${today.low_stock}</span>` : ""}</button>`).join("");
  $("tabs").querySelectorAll("button").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
}

function go(t) { tab = t; location.hash = t; render(); window.scrollTo(0, 0); }

async function render() {
  if (!SECTION(tab)) tab = "today";
  $("title").textContent = SECTION(tab).label;
  const sub = SUB.find((x) => x.id === tab) || (MORE.some((m) => m.id === tab) ? { back: "more" } : null);
  $("back").hidden = !sub;
  $("back").onclick = () => go(sub.back);
  $("back").setAttribute("aria-label", sub?.back === "more" ? "Back to More" : "Back to Today");
  document.body.classList.toggle("has-hero", ["today", "forecast", "evaluation"].includes(tab));
  renderTabs();
  const view = $("view");
  try { view.innerHTML = await VIEWS[tab](); BIND[tab]?.(); view.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go))); }
  catch (e) { view.innerHTML = `<div class="panel section">${esc(e.message)}</div>`; }
}

const byWhom = (run) => (run.source === "ai" ? "by Claude" : "by the built-in rules");
const timeOf = (iso) => new Date(iso + "Z").toLocaleString("en-GB", { hour: "2-digit", minute: "2-digit" });

// A draft order the stock agent changed: shown orange on Today so the manager looks at this one first.
function orderTab(po) {
  const lines = po.lines.filter((l) => l.change);
  const cost = po.lines.reduce((s, l) => s + l.est_cost, 0);
  return `<div class="order-tab" role="alert">
    <div class="ot-head"><span class="ot-ic">${ICONS.bang}</span><b>Check before approving</b></div>
    <div class="ot-main"><b class="sup">${esc(po.supplier)}</b><span class="mut">Delivers in ${po.lead_days} ${po.lead_days === 1 ? "day" : "days"} · ${sar(cost)}</span></div>
    ${lines.map((l) => `<div class="ot-line"><span class="fl">${esc(l.ingredient)}</span><span class="chg"><s>${fmt(l.change.from)} ${l.unit}</s><i>→</i><b>${fmt(l.change.to)} ${l.unit}</b></span></div>
      <p class="ot-why">${esc(l.change.reason)}</p>`).join("")}
    <button class="brass full" data-go="orders">Review this order</button>
  </div>`;
}

function agentCard(run, drafts = []) {
  const steps = run?.steps?.length || 0;
  return `<div class="agent">
    <div class="agent-h"><span class="badge">${ICONS.stockAgent}</span><div><b>Stock agent</b><small>${run ? `Finished ${timeOf(run.at)} · ${steps} steps · ${byWhom(run)}` : "Not run yet"}</small></div></div>
    <p class="big">${run ? esc(run.headline) : "No stock check yet today. Run one after closing, or any time."}</p>
    ${drafts.filter((p) => p.changed).map(orderTab).join("")}
    ${(run?.warnings || []).map((w) => `<div class="warn">${esc(w)}</div>`).join("")}
    ${steps ? `<button class="link" data-go="steps">See what the agent did</button>` : ""}
    <button class="secondary-btn" id="run-agent">Run stock check now</button>
  </div>`;
}

const pct = (v) => `${Number(v).toFixed(1)}%`;
const when = (iso) => new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
let evalStore = "own";
let evalPoll = null;

function evBars(rows, { max = 100 } = {}) {
  return `<div class="ev-bars">${rows.map((r) => `<div class="ev-bar ${r.kind}"><div class="top"><span>${esc(r.label)}</span><span class="val num">${pct(r.value)}</span></div>
    <div class="track"><div class="fill" style="width:${Math.max(2, (100 * r.value) / max)}%"></div></div></div>`).join("")}</div>`;
}

function evCashier(c) {
  const d = c[evalStore] || c.own;
  const lift = d.lift > 0 ? `<span class="chip ok">+${Math.round(d.lift)} pts</span>` : `<span class="chip low">Ties</span>`;
  const note = evalStore === "own"
    ? `${d.cases} held-out cases from a store whose customers pair items in their own way. The helper learns this from the orders.`
    : `${d.cases} cases. The demo data pairs items almost at random, so best sellers are already close to the best possible answer.`;
  return { lift, body: `${evBars(d.rows)}<p class="ev-note">${note}</p>` };
}

// stock tab: filters and a compact list; a row opens to show the details and the count box
let stockFilter = "need", stockQuery = "", stockOpen = null;
const STOCK_FILTERS = {
  need: { label: "Needs action", test: (r) => r.status === "negative" || (r.status === "low" && !r.on_order) },
  coming: { label: "On order", test: (r) => r.on_order },
  ok: { label: "OK", test: (r) => r.status === "ok" && !r.on_order },
  all: { label: "All", test: () => true },
};
const STOCK_WORD = { negative: "Below zero", low: "Low", ok: "OK" };

function stockList() {
  const q = stockQuery.trim().toLowerCase();
  const rank = (r) => (r.status === "negative" ? 0 : r.status === "low" ? (r.on_order ? 2 : 1) : 3);
  const rows = window._stk.filter(STOCK_FILTERS[stockFilter].test).filter((r) => !q || r.name.toLowerCase().includes(q))
    .sort((a, b) => rank(a) - rank(b) || (a.days_left ?? 999) - (b.days_left ?? 999) || a.name.localeCompare(b.name));
  if (!rows.length) return `<div class="empty">${q ? "No ingredient matches your search." : "Nothing here. Every ingredient is fine."}</div>`;
  return rows.map((r) => {
    const pct = Math.max(0, Math.min(100, (r.on_hand / r.par_level) * 100));
    const left = r.days_left == null ? "No recent use" : `${fmt(r.days_left)} ${r.days_left === 1 ? "day" : "days"} left`;
    const tight = r.days_left != null && r.days_left <= r.lead_days + 1;
    const open = stockOpen === r.id;
    return `<div class="stk ${r.status}${r.on_order ? " coming" : ""}${open ? " open" : ""}">
      <button class="stk-row" data-stk="${r.id}" aria-expanded="${open}">
        <span class="sd"></span>
        <span class="stk-n"><b>${esc(r.name)}</b><small>${fmt(r.on_hand)} ${r.unit}${r.on_order ? " · order on the way" : ""}</small></span>
        <span class="stk-m"><i style="width:${pct}%"></i></span>
        <span class="stk-l${tight ? " tight" : ""}">${left}</span>
        ${ICONS.chevron}
      </button>
      ${open ? `<div class="stk-more">
        ${r.status !== "ok" && r.reason ? `<p class="stk-why"><b>${STOCK_WORD[r.status]}:</b> ${esc(r.reason)}</p>` : ""}
        <dl class="facts four"><div><dt>On hand</dt><dd>${fmt(r.on_hand)} ${r.unit}</dd></div><div><dt>Minimum</dt><dd>${fmt(r.min_level)}</dd></div><div><dt>Full level</dt><dd>${fmt(r.par_level)}</dd></div><div><dt>Use a day</dt><dd>${fmt(r.avg_daily_use)}</dd></div></dl>
        <div class="muted stk-sup">${esc(r.supplier)} · delivers in ${r.lead_days} ${r.lead_days === 1 ? "day" : "days"}</div>
        <div class="stk-count"><label for="cnt-${r.id}">Counted today</label><input id="cnt-${r.id}" class="qty num" type="number" min="0" step="any" inputmode="decimal" placeholder="${fmt(r.on_hand)}"><span class="u">${r.unit}</span><button class="brass" data-count="${r.id}">Save count</button></div>
      </div>` : ""}
    </div>`;
  }).join("");
}

const VIEWS = {
  async devices() {
    const devs = await api("/api/devices");
    return `<div class="section first"><div class="panel">
        <div class="muted" style="font-size:14px;margin-bottom:8px">The cashier account only works on iPads paired here.</div>
        ${devs.map((d) => `<div class="list-item"><span>${esc(d.name)}<br><span class="muted">${d.paired ? "Paired" : "Waiting for code"}</span></span><button class="secondary-btn" data-revoke="${d.id}">Remove</button></div>`).join("") || '<div class="muted">No cashier iPad yet.</div>'}
        <div id="pair-out"></div>
        <div class="btns" style="display:flex;gap:8px;margin-top:12px"><button class="pair-btn" id="pair-new">Pair a cashier iPad</button></div>
      </div></div>`;
  },

  async more() {
    return `<div class="section"><div class="panel">${MORE.map((m) => `<button class="more-row" data-go="${m.id}"><span class="ic">${ICONS[m.icon]}</span><span><b>${m.label}</b><br><span class="muted">${m.sub}</span></span>${ICONS.chevron}</button>`).join("")}</div></div>
      <div class="section"><div class="panel"><button class="more-row signout" id="logout"><span class="ic">${ICONS.logout}</span><span><b>Sign out</b><br><span class="muted">Signed in as the manager</span></span></button></div></div>`;
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

  async evaluation() {
    const { running, error, results: e } = await api("/api/evaluation");
    window._ev = e;
    if (!e) return `<div class="hero"><div><div class="label">Agent evaluation</div><div class="value">Not run yet</div></div></div>
      <div class="section panel">Run <code>python -m evals --with-tests</code> in <code>backend/</code>, or tap below.</div>
      <div class="section"><div class="agent"><button id="ev-run" ${running ? "disabled" : ""}>${running ? "Running the checks…" : "Run the checks"}</button></div></div>`;
    const s = e.summary, c = evCashier(e.cashier), f = e.forecast, st = e.stock, inv = e.invoice;
    const tick = `<span class="ev-tick">${ICONS.check}</span>`;
    const head = (icon, title, sub, chip) => `<div class="ev-head"><span class="ic">${ICONS[icon]}</span><div><h3>${title}</h3><div class="sub">${sub}</div></div>${chip}</div>`;
    return `<div class="hero">
        <div><div class="label">Checks passed</div><div class="value num" style="color:${s.checks_passed === s.checks_total ? "var(--ok)" : "var(--bad)"}">${s.checks_passed ?? "–"}<small> / ${s.checks_total ?? "–"}</small></div></div>
        <div><div class="label">Agents tested</div><div class="value num">${s.agents}</div></div>
        <div><div class="label">Unseen test cases</div><div class="value num">${s.cases.toLocaleString("en-US")}</div></div>
        <div><div class="label">Fixed by testing</div><div class="value num">${s.fixes}</div></div>
      </div>
      <div class="section"><div class="agent">
        <div class="head">${ICONS.spark}Verdict</div>
        <div class="headline">${esc(e.verdict.headline)}</div>
        <ol class="ev-points">${e.verdict.points.map((p) => `<li><span><b>${esc(p.agent)}</b> ${esc(p.text)}</span></li>`).join("")}</ol>
        ${error ? `<div class="warn">${esc(error)}</div>` : ""}
        <div class="meta">Checks run ${when(e.run.at)}${e.run.ai_at ? ` · Claude results ${when(e.run.ai_at)}` : ""}</div>
        <button id="ev-run" ${running ? "disabled" : ""}>${running ? "Running the checks…" : "Run the checks again"}</button>
      </div></div>

      <div class="section"><h2>By agent</h2><div class="ev-stack">
        <div class="panel ev-card">
          ${head("bag", "Cashier helper", "Last 7 days of orders, held out", `<span id="ev-lift">${c.lift}</span>`)}
          <p class="ev-ask">How often was one of the two suggestions something the customer really added?</p>
          <div class="seg ev-seg" role="group" aria-label="Which store"><button data-store="own" aria-pressed="${evalStore === "own"}">Store with its own habits</button><button data-store="demo" aria-pressed="${evalStore === "demo"}">Demo sample data</button></div>
          <div id="ev-cashier">${c.body}</div>
        </div>

        <div class="panel ev-card">
          ${head("sales", "Sales forecast", `${esc(f.data)} · last 6 weeks`, `<span class="chip ok">${f.after < f.before ? "Improved" : "Checked"}</span>`)}
          <p class="ev-ask">Forecasting each of the next 7 days, how far off was it on average? Lower is better.</p>
          <div class="ev-ba"><div class="s before"><span class="l">Before testing</span><span class="v num">${pct(f.before)}</span></div>
            <span class="arrow">${ICONS.chevron}</span>
            <div class="s after"><span class="l">Now</span><span class="v num">${pct(f.after)}</span></div></div>
          ${evBars(f.rows, { max: Math.max(...f.rows.map((r) => r.value)) })}
          <details class="ev-more"><summary>How this was tested</summary><p>Each day, the forecast is made from the days before it only, then compared with what really sold, over ${f.days} days of sales. ${f.data.startsWith("Real") ? "Only percentages are shown, so the store's revenue stays private." : ""}</p></details>
        </div>

        <div class="panel ev-card">
          ${head("stock", "Stock-to-order agent", `Worked example + ${st.stores} random stores`, `<span class="chip ok">${st.right === st.expected && st.recall === 100 && st.precision === 100 ? "All correct" : "Check"}</span>`)}
          <p class="ev-ask">Does it order the right amount of the right things, and nothing else?</p>
          <div class="ev-rings">
            <div class="ring"><div class="dial" style="--p:${(100 * st.right) / st.expected}"><span class="num">${st.right}/${st.expected}</span></div><div class="cap">Order lines exactly right</div></div>
            <div class="ring"><div class="dial" style="--p:${st.recall}"><span class="num">${Math.round(st.recall)}%</span></div><div class="cap">Needed orders made</div></div>
            <div class="ring"><div class="dial" style="--p:${st.precision}"><span class="num">${Math.round(st.precision)}%</span></div><div class="cap">Orders really needed</div></div>
          </div>
          ${st.claude_numbers_ok === null ? "" : `<div class="ev-callout">${ICONS.spark}<span>Claude writes the notes, but the amounts always come from the code${st.claude_numbers_ok ? ", and every number in Claude's notes is one on the order" : ". Some numbers in Claude's notes were not on the order"}.</span></div>`}
        </div>

        ${inv ? `<div class="panel ev-card">
          ${head("orders", "Invoice reader", `${inv.lines} lines, ${inv.conditions.length} photo conditions`, `<span class="chip ok">${Math.round(Math.min(...inv.conditions.map((x) => x.value)))}%</span>`)}
          <p class="ev-ask">Lines read right: quantity, price and which ingredient it is.</p>
          <div class="ev-conds">${inv.conditions.map((x) => `<div class="cond ${x.key}"><div class="doc"><i></i><i></i><i></i><i></i></div><b class="num">${Math.round(x.value)}%</b><span>${esc(x.name)}</span></div>`).join("")}</div>
          ${inv.smudge_total ? `<div class="ev-callout">${ICONS.clock}<span>When a number is covered, it ${inv.smudge_said === inv.smudge_total ? "says it can't read it instead of guessing" : "says so or works it out, never guessing a wrong number"} (${inv.smudge_ok} of ${inv.smudge_total}).</span></div>` : ""}
        </div>` : ""}
      </div></div>

      ${e.robustness.length ? `<div class="section"><h2>When things go wrong</h2><div class="panel"><ul class="ev-checks">
        ${e.robustness.map((g) => `<li>${g.passed === g.total ? tick : `<span class="ev-tick bad">!</span>`}<span>${esc(g.text)}</span><span class="count num">${g.passed}/${g.total}</span></li>`).join("")}
      </ul></div></div>` : ""}

      <div class="section"><h2>What testing fixed</h2><div class="panel">
        ${e.fixes.map((x) => `<div class="ev-fix"><span class="what">${esc(x.what)}</span><span class="delta num"><s>${esc(x.before)}</s><em>${esc(x.after)}</em></span><small>${esc(x.measure)}</small></div>`).join("")}
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
    const [t, ins, runs, ov, pos] = await Promise.all([api("/api/today"), api("/api/insights/cashier"), api("/api/agents/runs"), api("/api/overview"), api("/api/purchase-orders")]);
    const drafts = pos.filter((p) => p.status === "draft");
    const brief = runs.find((r) => r.agent === "overview");
    const rate = ins.acceptance_rate == null ? "–" : `${Math.round(ins.acceptance_rate * 100)}%`;
    const needs = ov.priorities.filter((p) => !(p.go === "orders" && drafts.length));
    return `<div class="section first">${agentCard(runs.find((r) => r.agent === "stock"), drafts)}</div>
      ${drafts.length ? `<div class="section"><div class="panel"><div class="po-sum"><div><b>${drafts.length} supplier ${drafts.length === 1 ? "order" : "orders"} waiting</b><span class="muted">${sar(drafts.reduce((a, p) => a + p.lines.reduce((s2, l) => s2 + l.est_cost, 0), 0))} in total</span></div><button class="brass" data-go="orders">Review</button></div></div></div>` : ""}
      <div class="section"><h2>Needs you</h2><div class="panel">
        ${needs.map((p) => `<button class="more-row need ${p.level}" ${p.go ? `data-go="${p.go}"` : "disabled"}><span class="lvl"></span><span>${esc(p.text)}</span>${p.go ? ICONS.chevron : ""}</button>`).join("")}
      </div></div>
      <div class="section"><div class="agent">
        <div class="agent-h"><span class="badge">${ICONS.overviewAgent}</span><div><b>Manager overview</b><small>${brief ? `Briefed ${timeOf(brief.at)} · ${byWhom(brief)}` : "Not run yet"}</small></div></div>
        <p class="big">${brief ? esc(brief.headline) : "Tap below for a briefing across sales, stock, orders and costs."}</p>
        ${(brief?.points || []).map((p) => `<p class="pt">${esc(p)}</p>`).join("")}
        <button class="secondary-btn" id="run-overview">Brief me now</button>
      </div></div>
      <div class="section"><div class="hero flat">
        <div><div class="label">Sales</div><div class="value num">${sar(t.sales)}</div></div>
        <div><div class="label">Orders</div><div class="value num">${t.orders}</div></div>
        <div><div class="label">Avg. ticket</div><div class="value num">${sar(t.avg_ticket)}</div></div>
        <div><div class="label">Helper sales</div><div class="value num">${sar(t.suggested_sales)}</div></div>
      </div></div>
      <div class="section"><div class="hero flat center">
        <div><div class="label">Forecast tomorrow</div><div class="value num">${sar(ov.facts.forecast_tomorrow)}</div></div>
        <div><div class="label">Profit, 7 days</div><div class="value num" style="color:${ov.facts.profit_7d >= 0 ? "var(--ok)" : "var(--bad)"}">${sar(ov.facts.profit_7d)}</div></div>
      </div></div>
      <div class="section"><h2>Cashier helper</h2><div class="panel hc">
        <div class="hc-top">
          <div class="hc-ring" style="--p:${ins.acceptance_rate == null ? 0 : Math.round(ins.acceptance_rate * 100)}"><span class="num">${rate}</span></div>
          <div class="hc-say"><b>${ins.shown ? `${rate} of suggestions were added` : "No suggestions shown yet"}</b>
            <span>${ins.accepted.toLocaleString("en-US")} added out of ${ins.shown.toLocaleString("en-US")} shown on the cashier iPad</span></div>
        </div>
        <div class="hc-rev"><span>Extra sales from the helper</span><b class="num">${sar(ins.added_revenue)}</b></div>
        ${ins.top_accepted.length ? `<div class="hc-items"><span class="lbl">Added most often</span><div class="hc-chips">${ins.top_accepted.map((x) => `<span class="hc-chip">${esc(x.name)}<b class="num">${x.count}×</b></span>`).join("")}</div></div>` : ""}
      </div></div>
`;
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
      <div class="panel chart-card"><h3>Sales by hour</h3><div class="sub">Average SAR per day, last ${salesDays} days</div><div id="c-hour"></div></div>
      <div class="panel chart-card"><h3>Top items</h3><div class="sub">By sales, last ${salesDays} days</div><div id="c-top"></div></div>
      <div class="panel chart-card"><h3>Sales by category</h3><div class="sub">Share of sales, last ${salesDays} days</div><div id="c-cat"></div>
        <details class="table"><summary>Show as table</summary><table><tr><th>Category</th><th>Sales</th></tr>${s.categories.map((c) => `<tr><td>${c.category}</td><td class="num">${sar(c.sales)}</td></tr>`).join("")}</table></details></div>
      <div class="panel chart-card"><h3>Cashier helper add-on sales</h3><div class="sub">SAR from accepted suggestions · ${sar(helper)} in total</div><div id="c-helper"></div></div>`;
  },

  async orders() {
    const [pos, runs] = await Promise.all([api("/api/purchase-orders"), api("/api/agents/runs")]);
    const run = runs.find((r) => r.agent === "stock");
    if (!pos.length) return `<div class="section">${agentCard(run)}</div><div class="section panel empty">No supplier orders yet.</div>`;
    const dayOf = (iso, o = { weekday: "short", day: "numeric", month: "short" }) => new Date(iso.length === 10 ? iso + "T00:00" : iso + "Z").toLocaleDateString("en-GB", o);
    const todayIso = new Date().toISOString().slice(0, 10);
    const lineHtml = (l, draft) => {
      const input = `<input class="qty num" type="number" min="0" step="any" value="${l.qty}" data-line="${l.id}" aria-label="Quantity of ${esc(l.ingredient)}"><span class="u">${l.unit}</span>`;
      if (draft && l.change) return `<div class="item-card changed">
        <div class="item-top"><span class="iname">${esc(l.ingredient)}</span><span class="tag alert-tag">${l.change.to >= l.change.from ? "Raised" : "Lowered"} by agent</span></div>
        <div class="amounts"><div class="was"><span>Rules said</span><s>${fmt(l.change.from)} ${l.unit}</s></div><span class="arr">→</span><div class="now"><span>Order</span><div class="inp">${input}</div></div></div>
        <p class="because">${esc(l.change.reason)}</p>
        <button class="link undo" data-undo="${l.change.from}" data-line="${l.id}">Change it back to ${fmt(l.change.from)} ${l.unit}</button></div>`;
      return `<div class="ln"><span class="n">${esc(l.ingredient)}</span><span class="q">${draft ? input : `<b class="num">${fmt(l.qty)}</b> ${l.unit}`}</span>
        ${draft && l.reason ? `<p class="why">${esc(l.reason)}</p>` : ""}</div>`;
    };
    // the agent's note often repeats each line's reason (rules mode always does); show it only when it adds something
    const extraNote = (po) => {
      let rest = po.note || "";
      po.lines.forEach((l) => { rest = rest.split(`${l.ingredient}: ${l.reason}`).join("").split(l.reason).join(""); });
      return rest.replace(/[\s.;,:-]+/g, " ").trim().length > 15 ? po.note : "";
    };
    // where the order is in its journey: drafted, sent, on the way, delivered
    const track = (po) => {
      const late = po.status === "sent" && po.expected < todayIso;
      const steps = [["Drafted", dayOf(po.created_at)], ["Approved and sent", po.sent_at ? dayOf(po.sent_at) : ""],
        [late ? "Late" : "On the way", po.expected ? `Due ${dayOf(po.expected)}` : ""], ["Delivered", po.delivery?.at ? dayOf(po.delivery.at) : ""]];
      const at = { draft: 0, sent: 2, received: 3 }[po.status];
      return `<ol class="track">${steps.map(([t, d], i) => `<li class="${i < at || po.status === "received" ? "done" : i === at ? (late ? "now late" : "now") : ""}"><i></i><b>${t}</b><small>${d}</small></li>`).join("")}</ol>`;
    };
    const chipFor = (po) => po.status === "draft" ? '<span class="chip draft">Needs approval</span>'
      : po.status === "sent" ? (po.expected < todayIso ? '<span class="chip negative">Late</span>' : '<span class="chip sent">On the way</span>')
      : po.status === "received" ? '<span class="chip received">Delivered</span>' : '<span class="chip rejected">Rejected</span>';
    const card = (po) => {
      const draft = po.status === "draft";
      const cost = po.lines.reduce((s, l) => s + l.est_cost, 0);
      const note = draft ? extraNote(po) : "";
      const got = Object.fromEntries((po.delivery?.lines || []).map((d) => [d.ingredient_id, d.qty]));
      return `<div class="panel po${po.changed && draft ? " flagged" : ""}" data-id="${po.id}">
        <div class="po-head"><div><b>${esc(po.supplier)}</b><small>Order #${po.id} · drafted by the stock agent</small></div>${chipFor(po)}</div>
        ${po.status === "rejected" ? "" : track(po)}
        ${note ? `<div class="agent-note">${ICONS.spark}<p>${esc(note)}</p></div>` : ""}
        <dl class="facts"><div><dt>${po.status === "draft" ? "Delivery" : po.status === "received" ? "Delivered" : "Due"}</dt><dd>${draft ? `${po.lead_days} ${po.lead_days === 1 ? "day" : "days"}` : po.status === "received" ? (po.delivery?.at ? dayOf(po.delivery.at, { day: "numeric", month: "short" }) : "Yes") : po.expected ? dayOf(po.expected, { weekday: "short", day: "numeric" }) : "–"}</dd></div><div><dt>Items</dt><dd>${po.lines.length}</dd></div><div><dt>Est. cost</dt><dd>${sar(cost)}</dd></div></dl>
        ${po.status === "received" ? po.lines.map((l) => { const r = got[l.ingredient_id] ?? 0, short = r < l.qty;
            return `<div class="ln"><span class="n">${esc(l.ingredient)}</span><span class="q"><b class="num">${fmt(r)}</b> of ${fmt(l.qty)} ${l.unit}${short ? ' <span class="chip low">Short</span>' : ""}</span></div>`; }).join("")
          : po.lines.map((l) => lineHtml(l, draft)).join("")}
        ${draft ? `<div class="row"><button class="brass approve">Approve and send</button><button class="reject">Reject</button></div>
          <p class="after">${po.channel === "whatsapp" ? "After you approve, a Send on WhatsApp button appears with the order typed in for the supplier." : "After you approve, the order is emailed to the supplier."} It then waits here under <b>On the way</b> until you confirm the delivery.</p>` : ""}
        ${po.status === "sent" ? `<div class="sent-how">${po.channel === "whatsapp" ? "Order written for WhatsApp" : "Order emailed to the supplier"}${po.sent_at ? ` · ${dayOf(po.sent_at)}` : ""}</div>
          <div class="btns">${po.whatsapp_link ? `<a class="wa" href="${esc(po.whatsapp_link)}" target="_blank" rel="noopener">${ICONS.whatsapp}Send on WhatsApp</a>` : ""}<button class="brass open-receive">Confirm delivery</button></div>
          <div class="receive-form" hidden>
            <p class="muted">Enter what really arrived. Change a number if the supplier sent less or more.</p>
            ${po.lines.map((l) => `<label class="rf-line"><span>${esc(l.ingredient)}</span><span class="q"><input class="qty num" type="number" min="0" step="any" value="${l.qty}" data-ing="${l.ingredient_id}" aria-label="Received ${esc(l.ingredient)}"><span class="u">${l.unit}</span></span></label>`).join("")}
            <label class="field">Invoice number (optional)<input class="inv-ref" type="text" maxlength="40"></label>
            <div class="row"><button class="brass receive">Add to stock</button><button class="reject cancel-receive">Cancel</button></div>
            <button class="link" data-go="deliveries">Read the invoice photo instead</button>
          </div>` : ""}
      </div>`;
    };
    const by = (st) => pos.filter((p) => p.status === st);
    const drafts = by("draft").sort((a, b) => b.changed - a.changed), sent = by("sent"), received = by("received"), rejected = by("rejected");
    const group = (title, list, sub = "") => list.length ? `<div class="section"><h2>${title}${sub}</h2>${list.map(card).join("")}</div>` : "";
    return `${drafts.length ? `<div class="section first"><h2>Waiting for your approval</h2>${drafts.map(card).join("")}</div>` : `<div class="section first">${agentCard(run)}</div>`}
      ${group("On the way", sent)}
      ${group("Delivered", received.slice(0, 5))}
      ${received.length > 5 || rejected.length ? `<div class="section"><details class="older"><summary>${received.length > 5 ? `${received.length - 5} older deliveries` : ""}${received.length > 5 && rejected.length ? " and " : ""}${rejected.length ? `${rejected.length} rejected` : ""}</summary>${[...received.slice(5), ...rejected].map(card).join("")}</details></div>` : ""}`;
  },

  async steps() {
    const [runs, pos] = await Promise.all([api("/api/agents/runs"), api("/api/purchase-orders")]);
    const run = runs.find((r) => r.agent === "stock");
    if (!run?.steps?.length) return `<div class="section first panel empty">No stock check has run yet.</div>`;
    const drafts = pos.filter((p) => p.status === "draft");
    const target = drafts.find((p) => p.changed) || drafts[0];
    const stepHtml = (s) => {
      const changed = /^(Changed|Raised|Lowered)/.test(s.label), bad = !s.ok;
      return `<li class="step${changed ? " chg" : ""}${bad ? " bad" : ""}"><span class="dot${changed || bad ? " warn" : ""}">${changed || bad ? ICONS.bang : ICONS.check}</span>
        <div><b>${esc(s.label)}</b>${s.detail ? (changed ? `<div class="note">${esc(s.detail)}</div>` : `<span>${esc(s.detail)}</span>`) : ""}</div></li>`;
    };
    return `<div class="section first"><div class="panel"><div class="muted" style="font-size:13px;margin-bottom:12px">${run.steps.length} steps · ${timeOf(run.at)} · ${run.source === "ai" ? "decided by Claude" : "run by the rules"}</div>
        <ol class="steps">${run.steps.map(stepHtml).join("")}</ol></div></div>
      <div class="next">${target ? `<button class="brass full" data-go="orders">Review the order · ${esc(target.supplier)}</button><small>Opens the Orders page</small>` : `<button class="brass full" data-go="today">Back to Today</button>`}</div>`;
  },

  async stock() {
    const [rows, runs] = await Promise.all([api("/api/stock"), api("/api/agents/runs")]);
    window._stk = rows;
    const run = runs.find((r) => r.agent === "stock");
    const n = (f) => rows.filter(STOCK_FILTERS[f].test).length;
    if (stockFilter === "need" && !n("need")) stockFilter = "all";
    return `<div class="section first"><div class="panel strip"><span class="badge sm">${ICONS.stockAgent}</span>
        <div><b>Stock agent</b><small>${run ? `Last check ${timeOf(run.at)} · ${byWhom(run)}` : "No check yet today"}</small></div>
        <button class="secondary-btn" id="run-agent">Run check</button></div></div>
      <div class="section stk-tools">
        <div class="stk-filters" role="group" aria-label="Show">${Object.entries(STOCK_FILTERS).map(([k, f]) => `<button data-sf="${k}" aria-pressed="${k === stockFilter}" class="${k}">${f.label}<b class="num">${n(k)}</b></button>`).join("")}</div>
        <label class="stk-search">${ICONS.search}<input id="stk-q" type="search" placeholder="Search ingredients" value="${esc(stockQuery)}" autocomplete="off"></label>
      </div>
      <div class="section"><div class="panel stk-list" id="stk-list"></div></div>`;
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
  evaluation() {
    clearTimeout(evalPoll);
    document.querySelectorAll("[data-store]").forEach((b) => (b.onclick = () => {
      evalStore = b.dataset.store;
      const c = evCashier(window._ev.cashier);
      $("ev-cashier").innerHTML = c.body; $("ev-lift").innerHTML = c.lift;
      document.querySelectorAll("[data-store]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.store === evalStore));
    }));
    const btn = $("ev-run");
    const poll = () => { evalPoll = setTimeout(async () => {
      if (tab !== "evaluation") return;
      const r = await api("/api/evaluation").catch(() => ({ running: false }));
      if (r.running) return poll();
      toast(r.error ? r.error : "Checks finished"); render();
    }, 3000); };
    if (btn?.disabled) poll();
    if (btn) btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "Running the checks… about a minute";
      try { await api("/api/evaluation/run", { method: "POST" }); poll(); }
      catch (err) { toast(err.message, true); btn.disabled = false; btn.textContent = "Run the checks again"; }
    };
  },
  more() {
    document.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => go(b.dataset.go)));
    $("logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.href = "/login"; };
  },
  devices() {
    $("pair-new").onclick = async () => {
      const r = await api("/api/devices", { method: "POST", body: JSON.stringify({ name: "Cashier iPad" }) });
      $("pair-out").innerHTML = `<div style="margin-top:12px"><div class="code num">${r.code}</div><div class="muted" style="font-size:13px;margin-top:8px;text-align:center">On the iPad, open Restaura, tap "Pair as cashier iPad" and enter this code. It expires in ${r.minutes} minutes.</div></div>`;
    };
    document.querySelectorAll("[data-revoke]").forEach((b) => (b.onclick = async () => { await api(`/api/devices/${b.dataset.revoke}/revoke`, { method: "POST" }); toast("Device removed"); render(); }));
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
    const hours = Array.from({ length: 14 }, (_, i) => i + 10).map((h) => ({ h, v: 0, n: 0 }));
    s.period_orders.forEach((o) => { const h = o.hour; const b = hours.find((x) => x.h === h); if (b) { b.v += o.total; b.n += 1; } });
    const nd = s.daily.length;
    Charts.columns($("c-hour"), hours.map((b) => ({ value: b.v / nd, label: b.h % 2 === 0 ? `${b.h}` : "", tip: `${b.h}:00–${b.h + 1}:00<br><b>${sar(b.v / nd)}</b> a day · ${fmt(b.n / nd)} orders` })), { height: 160 });
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
  },
  stock() {
    bindAgent();
    const draw = () => {
      $("stk-list").innerHTML = stockList();
      $("stk-list").querySelectorAll("[data-stk]").forEach((b) => (b.onclick = () => { stockOpen = stockOpen === +b.dataset.stk ? null : +b.dataset.stk; draw(); }));
      $("stk-list").querySelectorAll("[data-count]").forEach((b) => (b.onclick = async () => {
        const id = +b.dataset.count, qty = parseFloat($(`cnt-${id}`).value);
        if (isNaN(qty)) return toast("Enter the counted quantity", true);
        const r = await api("/api/stock/count", { method: "POST", body: JSON.stringify([{ ingredient_id: id, counted: qty }]) });
        const [name, diff] = Object.entries(r.adjustments)[0];
        toast(`${name} corrected by ${diff > 0 ? "+" : ""}${fmt(diff)}`); render();
      }));
    };
    document.querySelectorAll("[data-sf]").forEach((b) => (b.onclick = () => {
      stockFilter = b.dataset.sf;
      document.querySelectorAll("[data-sf]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.sf === stockFilter));
      draw();
    }));
    $("stk-q").oninput = (e) => { stockQuery = e.target.value; if (stockQuery && stockFilter !== "all") { stockFilter = "all"; document.querySelectorAll("[data-sf]").forEach((x) => x.setAttribute("aria-pressed", x.dataset.sf === "all")); } draw(); };
    draw();
  },
  orders() {
    bindAgent();
    document.querySelectorAll("[data-undo]").forEach((b) => (b.onclick = () => {
      const input = document.querySelector(`input.qty[data-line="${b.dataset.line}"]`);
      input.value = b.dataset.undo; toast("Set back to the rules' amount");
    }));
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
      const form = el.querySelector(".receive-form");
      el.querySelector(".open-receive")?.addEventListener("click", (ev) => { form.hidden = false; ev.target.closest(".btns").hidden = true; });
      el.querySelector(".cancel-receive")?.addEventListener("click", () => { form.hidden = true; el.querySelector(".btns").hidden = false; });
      el.querySelector(".receive")?.addEventListener("click", async (ev) => {
        const lines = [...form.querySelectorAll("input[data-ing]")].map((i) => ({ ingredient_id: +i.dataset.ing, qty: parseFloat(i.value) || 0 })).filter((l) => l.qty > 0);
        if (!lines.length) return toast("Enter what arrived for at least one item", true);
        ev.target.disabled = true;
        try { await api(`/api/purchase-orders/${id}/receive`, { method: "POST", body: JSON.stringify({ lines, invoice_ref: form.querySelector(".inv-ref").value.trim() || null }) });
          toast("Delivery added to stock"); render(); }
        catch (e) { toast(e.message, true); ev.target.disabled = false; }
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
        // matched lines get a quantity box: Claude fills it when the invoice shows a weight, volume or pack size,
        // otherwise the manager types what arrived
        const matched = r.lines.filter((l) => l.ingredient_id);
        out.innerHTML = `<div class="po" style="margin-top:12px"><div class="top"><span class="sup">${esc(r.supplier_name || "Supplier")}</span><span class="muted">${esc(r.invoice_number || "")}</span></div>
          <table>${r.lines.map((l) => `<tr><td>${esc(l.description)}${l.quantity != null ? ` <span class="muted num">× ${fmt(l.quantity)}</span>` : ""}${l.ingredient ? `<br><span class="muted">→ ${esc(l.ingredient)}</span>` : '<br><span class="muted">not matched</span>'}</td><td class="q">${l.ingredient_id
            ? `<input class="qty num" type="number" min="0" step="any" value="${l.qty_in_unit ?? ""}" placeholder="?" data-ing="${l.ingredient_id}" aria-label="Quantity of ${esc(l.ingredient)} received"> ${esc(l.unit)}`
            : "–"}</td></tr>`).join("")}</table>
          ${r.notes.map((n) => `<div class="note">${esc(n)}</div>`).join("")}
          ${matched.length ? `<div class="btns"><button class="approve" id="inv-ok">Add matched lines to stock</button></div>` : ""}</div>`;
        $("inv-ok")?.addEventListener("click", async () => {
          const lines = [...out.querySelectorAll("input[data-ing]")].map((i) => ({ ingredient_id: +i.dataset.ing, qty: parseFloat(i.value) })).filter((l) => l.qty > 0);
          if (!lines.length) return toast("Enter the quantity received for at least one line", true);
          await api("/api/deliveries", { method: "POST", body: JSON.stringify({ lines, invoice_ref: r.invoice_number }) });
          toast("Delivery added to stock"); render();
        });
      } catch (err) { out.innerHTML = ""; toast(err.message, true); }
    };
  },
};

(async () => {
  status = await api("/api/status");
  $("store").textContent = `${status.store} · ${new Date().toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}`;
  $("back-icon").innerHTML = ICONS.back;
  $("ai-badge").textContent = status.ai_enabled ? "AI on" : "AI off";
  $("ai-badge").classList.toggle("on", status.ai_enabled);
  $("ai-badge").title = status.ai_enabled ? "The agents use Claude." : "No Claude key is set, so the agents use the built-in rules: fixed calculations, no AI.";
  $("ai-badge").onclick = () => toast($("ai-badge").title);
  window.onhashchange = () => { const t = location.hash.slice(1); if (t && t !== tab && VIEWS[t]) { tab = t; render(); } };
  render();
})();
