const state = { menu: [], cat: null, q: "", cart: [], seq: 0, payments: [] };
const $ = (id) => document.getElementById(id);
const sar = (n) => `${Number(n).toFixed(0)} SAR`;
const sar2 = (n) => `${Number(n).toFixed(2)} SAR`;
const icon = (cat) => ICONS[cat] || ICONS.bag;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
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
  setTimeout(() => t.remove(), 2600);
}

function renderCats() {
  const cats = [...new Set(state.menu.map((i) => i.category))];
  state.cat ??= cats[0];
  $("cats").innerHTML = cats.map((c) => `<button class="cat" aria-pressed="${c === state.cat && !state.q}" data-cat="${esc(c)}">${icon(c)}${esc(c)}</button>`).join("");
  $("cats").querySelectorAll("button").forEach((b) => (b.onclick = () => { state.cat = b.dataset.cat; state.q = ""; $("search").value = ""; render(); }));
}

function renderMenu() {
  const items = state.q
    ? state.menu.filter((i) => i.name.toLowerCase().includes(state.q))
    : state.menu.filter((i) => i.category === state.cat);
  $("cat-title").textContent = state.q ? `Results for “${state.q}”` : state.cat;
  $("grid").innerHTML = "";
  for (const item of items) {
    const b = document.createElement("button");
    b.className = "card";
    if (["Waffles", "Drinks"].includes(item.category)) b.dataset.tone = "accent";
    b.disabled = !item.available;
    const flag = !item.available ? "Out of stock" : item.popular ? "Popular" : "";
    b.innerHTML = `${flag ? `<span class="flag">${flag}</span>` : ""}<div class="tile">${icon(item.category)}</div>
      <div class="body"><span class="name">${esc(item.name)}</span>
      <div class="row"><span class="price num">${sar(item.price)}</span><span class="plus" aria-hidden="true">+</span></div></div>`;
    b.setAttribute("aria-label", `${item.name}, ${sar(item.price)}${item.available ? "" : ", out of stock"}`);
    b.onclick = () => add(item);
    $("grid").append(b);
  }
  if (!items.length) $("grid").innerHTML = '<p class="muted">No items match.</p>';
}

function render() { renderCats(); renderMenu(); }

// The order moves through fixed steps. AI suggestions are made once, after the order is complete,
// so the helper is not called on every tap; the cashier can't reach payment without seeing them.
const STEPS = [["order", "Order"], ["suggest", "AI suggestions"], ["pay", "Payment"]];
const total = () => state.cart.reduce((s, l) => s + l.item.price * l.qty, 0);
// part payments: cash short of the total is taken and the rest is paid by NearPay or more cash
const paidSoFar = () => state.payments.reduce((s, p) => s + p.amount, 0);
const remaining = () => Math.max(0, Math.round((total() - paidSoFar()) * 100) / 100);
state.step = "order";

function add(item, eventId = null) {
  if (state.step === "paid") { state.paid = null; state.step = "order"; }
  const line = state.cart.find((l) => l.item.id === item.id);
  if (line) { line.qty += 1; if (eventId) line.eventId = eventId; }
  else state.cart.push({ item, qty: 1, eventId });
  renderCart();
}

function go(step) { state.step = step; renderCart(); if (step === "suggest") loadSuggestions(); }

function linesHtml() {
  return state.cart.map((l, i) => `<li class="line"><span class="mini">${icon(l.item.category)}</span>
    <div><div class="n">${esc(l.item.name)}</div><div class="unit num">${sar(l.item.price * l.qty)}</div>${l.eventId ? '<span class="tag">✦ Suggested</span>' : ""}</div>
    <div class="stepper"><button data-minus="${i}" aria-label="Remove one">−</button><b class="num">${l.qty}</b><button data-plus="${i}" aria-label="Add one">+</button></div></li>`).join("");
}

function renderCart() {
  const t = total(), n = state.cart.reduce((s, l) => s + l.qty, 0);
  $("count").textContent = n ? `${n} item${n > 1 ? "s" : ""}` : "";
  const at = STEPS.findIndex(([k]) => k === state.step || (k === "pay" && state.step === "cash"));
  $("stepsbar").innerHTML = state.step === "paid" ? "" : STEPS.map(([k, label], i) =>
    `<li class="${i < at ? "done" : i === at ? "now" : ""}"${i === at ? ' aria-current="step"' : ""}><i>${i < at ? ICONS.check : i + 1}</i><span>${label}</span></li>`).join("");
  document.querySelector(".pos").classList.toggle("wide-order", state.step === "suggest");
  const pane = $("pane"), acts = $("actions");
  if (state.step === "paid") {
    const p = state.paid;
    pane.innerHTML = `<div class="paid"><span class="tick">${ICONS.check}</span><b>Paid · ${sar(p.total)}</b>
      <span>Order #${p.id} · ${p.payments.map((x) => `${x.method === "card" ? "NearPay" : "Cash"} ${sar2(x.amount)}`).join(" + ")}</span>
      ${p.change > 0 ? `<span>Change given ${sar2(p.change)}</span>` : ""}
      ${p.addons ? `<span>${p.addons} suggested add-on${p.addons > 1 ? "s" : ""} added</span>` : ""}</div>`;
    acts.innerHTML = `<button class="btn solid wide" id="next">Next customer</button>`;
    $("next").onclick = () => { state.paid = null; go("order"); };
  } else if (state.step === "order") {
    pane.innerHTML = state.cart.length ? `<ul class="lines">${linesHtml()}</ul>` : `<div class="empty-order">${ICONS.bag}<div>Tap an item to start an order</div></div>`;
    acts.innerHTML = `<button class="btn ghost" id="clear">Clear</button><button class="btn solid" id="next" ${state.cart.length ? "" : "disabled"}>${ICONS.spark}Continue to AI suggestions</button>`;
    $("clear").onclick = () => { state.cart = []; state.suggest = null; renderCart(); };
    $("next").onclick = () => go("suggest");
  } else if (state.step === "suggest") {
    pane.innerHTML = `<div class="sg" id="sg">${suggestHtml()}</div><div class="sg-order"><div class="lbl">In the order</div><ul class="lines">${linesHtml()}</ul></div>`;
    acts.innerHTML = `<button class="btn ghost" id="back">Back</button><button class="btn solid" id="next">Go to payment</button>`;
    $("back").onclick = () => go("order");
    $("next").onclick = () => go("pay");
    bindSuggestions();
  } else if (state.step === "pay") {
    const part = state.payments.length;
    pane.innerHTML = `<div class="pay">${part ? `<div class="part"><span>Paid so far · ${state.payments.map((x) => `${x.method === "card" ? "NearPay" : "Cash"} ${sar2(x.amount)}`).join(" + ")}</span><b class="num">${sar2(remaining())} left to pay</b></div>` : ""}
      <div class="pay-h">${part ? "How is the customer paying the rest?" : "How is the customer paying?"}</div>
      <button class="pay-opt" id="m-card"><span class="pi">${ICONS.card}</span><span><b>NearPay</b><small>Card or phone, tap on this iPad</small></span>${ICONS.chevron}</button>
      <button class="pay-opt" id="m-cash"><span class="pi">${ICONS.wallet}</span><span><b>Cash</b><small>Enter what the customer gives</small></span>${ICONS.chevron}</button></div>`;
    acts.innerHTML = part ? `<button class="btn ghost wide" id="back">Undo part payment</button>` : `<button class="btn ghost wide" id="back">Back to suggestions</button>`;
    $("back").onclick = () => { if (part) { state.payments = []; renderCart(); } else go("suggest"); };
    $("m-card").onclick = openTap;
    $("m-cash").onclick = () => { state.cash = ""; go("cash"); };
  } else if (state.step === "cash") {
    const due = remaining(), given = parseFloat(state.cash) || 0, change = given - due;
    const quick = [...new Set([Math.ceil(due), Math.ceil(due / 10) * 10, Math.ceil(due / 50) * 50, Math.ceil(due / 100) * 100, 500])].filter((v) => v >= due).slice(0, 4);
    pane.innerHTML = `<div class="cash"><div class="pay-h">Cash received <span class="muted">· due ${sar2(due)}</span></div>
      <div class="cash-in num">${state.cash ? `${state.cash} SAR` : '<span class="muted">0 SAR</span>'}</div>
      <div class="cash-quick">${quick.map((v) => `<button data-q="${v}">${v === Math.ceil(due) ? "Exact" : `${v}`}</button>`).join("")}</div>
      <div class="keys cash-keys">${["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"].map((k) => `<button data-k="${k}">${k}</button>`).join("")}</div>
      <div class="change ${given >= due ? "ok" : given ? "short" : ""}">${given >= due ? `Change to give back <b class="num">${sar2(change)}</b>` : given ? `Short by <b class="num">${sar2(-change)}</b>, the rest is paid next` : "Tap the amount the customer gave"}</div></div>`;
    acts.innerHTML = `<button class="btn ghost" id="back">Back</button><button class="btn solid" id="next" ${given > 0 ? "" : "disabled"}>${given >= due || !given ? "Close the bill" : `Take ${sar2(given)} · pay the rest`}</button>`;
    pane.querySelectorAll("[data-q]").forEach((b) => (b.onclick = () => { state.cash = b.dataset.q; renderCart(); }));
    pane.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => {
      const k = b.dataset.k;
      state.cash = k === "⌫" ? state.cash.slice(0, -1) : k === "." && state.cash.includes(".") ? state.cash : (state.cash + k).slice(0, 7);
      renderCart();
    }));
    $("back").onclick = () => go("pay");
    $("next").onclick = () => {
      if (given >= due) { state.payments.push({ method: "cash", amount: due }); closeBill(change).then((ok) => ok || state.payments.pop()); }
      else { state.payments.push({ method: "cash", amount: given }); go("pay"); }
    };
  }
  pane.querySelectorAll("[data-minus]").forEach((b) => (b.onclick = () => { const l = state.cart[+b.dataset.minus]; l.qty -= 1; if (!l.qty) state.cart.splice(+b.dataset.minus, 1); renderCart(); }));
  pane.querySelectorAll("[data-plus]").forEach((b) => (b.onclick = () => add(state.cart[+b.dataset.plus].item)));
  const shown = state.step === "paid" ? state.paid.total : t, net = shown / 1.15;
  $("subtotal").textContent = sar2(net);
  $("vat").textContent = sar2(shown - net);
  $("total").textContent = sar(shown);
}

// one call per order: reused if the cashier goes back without changing the order
async function loadSuggestions() {
  const key = state.cart.filter((l) => !l.eventId).map((l) => `${l.item.id}x${l.qty}`).join(",");
  if (state.suggest?.key === key) return;
  state.suggest = { key, loading: true, list: [] };
  renderCart();
  try {
    const out = await api("/api/cashier/suggest", { method: "POST", body: JSON.stringify({ lines: state.cart.map((l) => ({ item_id: l.item.id, qty: l.qty })) }) });
    if (state.suggest.key !== key) return;
    state.suggest = { key, list: out.suggestions };
  } catch { state.suggest = { key, list: [], error: true }; }
  if (state.step === "suggest") renderCart();
}

function suggestHtml() {
  const sg = state.suggest;
  const head = `<div class="sg-h">${ICONS.spark}<div><b>Offer before payment</b><small>Read the line out. Tap Add if the customer says yes.</small></div></div>`;
  if (!sg || sg.loading) return head + '<p class="hint dots"><span></span><span></span><span></span></p>';
  if (sg.error) return head + '<p class="hint">Suggestions are unavailable right now. Go on to payment.</p>';
  if (!sg.list.length) return head + '<p class="hint">This order looks complete. Go on to payment.</p>';
  return head + sg.list.map((s, i) => {
    const added = state.cart.some((l) => l.eventId === s.event_id);
    return `<div class="sg-card${added ? " added" : ""}"><div class="sg-top"><b>${esc(s.name)}</b><span class="num">+${sar(s.price)}</span></div>
      <p>“${esc(s.pitch)}”</p><button class="sg-add" data-sg="${i}" ${added ? "disabled" : ""}>${added ? `${ICONS.check}Added` : "+ Add"}</button></div>`;
  }).join("");
}

function bindSuggestions() {
  $("pane").querySelectorAll("[data-sg]").forEach((b) => (b.onclick = () => {
    const s = state.suggest.list[+b.dataset.sg];
    add(state.menu.find((i) => i.id === s.item_id), s.event_id);
  }));
}

// NearPay: on this iPad the card or phone is tapped on the screen; in the demo a button stands in for the tap
function openTap() {
  const t = remaining();
  $("tap-amt").textContent = sar2(t);
  $("tap-amt-ar").textContent = `${t.toLocaleString("ar-SA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ر.س`;
  $("tap-say").innerHTML = '<b>Present card or phone</b><span lang="ar" dir="rtl">قدّم البطاقة أو الجوال</span>';
  $("tap").className = "tap"; $("tap").hidden = false; $("tap-sim").disabled = false;
}
async function tapped() {
  $("tap-sim").disabled = true;
  $("tap").className = "tap reading";
  $("tap-say").innerHTML = '<b>Reading card…</b><span lang="ar" dir="rtl">جارٍ قراءة البطاقة</span>';
  await new Promise((r) => setTimeout(r, 1400));
  state.payments.push({ method: "card", amount: remaining() });
  const ok = await closeBill(0);
  if (!ok) { state.payments.pop(); $("tap").hidden = true; return; }
  $("tap").className = "tap ok";
  $("tap-say").innerHTML = '<b>Approved</b><span lang="ar" dir="rtl">تمت الموافقة</span>';
  setTimeout(() => { $("tap").hidden = true; }, 1600);
}

async function closeBill(change) {
  try {
    const out = await api("/api/orders", { method: "POST", body: JSON.stringify({ lines: state.cart.map((l) => ({ item_id: l.item.id, qty: l.qty, suggestion_event_id: l.eventId })) }) });
    state.paid = { id: out.order_id, total: out.total, payments: state.payments, change, addons: state.cart.filter((l) => l.eventId).length };
    state.cart = []; state.suggest = null; state.payments = []; state.step = "paid";
    renderCart();
    state.menu = await api("/api/menu");
    render();
    loadToday();
    return true;
  } catch (e) { toast(e.message, true); return false; }
}

async function loadToday() {
  const t = await api("/api/today");
  $("k-orders").textContent = t.orders;
  $("k-sales").textContent = sar(t.sales);
  $("k-addons").textContent = `${t.suggestions_accepted} · ${sar(t.suggested_sales)}`;
}

// clock in and out with a PIN
let pin = "";
function renderPin() {
  $("pin-dots").innerHTML = [0, 1, 2, 3].map((i) => `<i class="${i < pin.length ? "on" : ""}"></i>`).join("");
}
async function pressKey(k) {
  if (k === "⌫") pin = pin.slice(0, -1);
  else if (k && pin.length < 4) pin += k;
  renderPin();
  if (pin.length === 4) {
    try {
      const r = await api("/api/staff/clock", { method: "POST", body: JSON.stringify({ pin }) });
      toast(r.action === "in" ? `Welcome, ${r.name}. Clocked in at ${r.at}.` : `Bye, ${r.name}. Clocked out at ${r.at} (${r.hours} h).`);
      $("pin-sheet").hidden = true;
    } catch (e) { toast(e.message, true); }
    pin = ""; renderPin();
  }
}

// daily checklists: staff tick tasks here; the manager sees them in Routines
async function loadTasks(open = false) {
  const r = await api("/api/routines");
  const late = r.filter((x) => x.overdue).length;
  $("tasks-btn").innerHTML = `${ICONS.list}Tasks${late ? `<span class="dot">${late}</span>` : ""}`;
  if (!open && $("sheet").hidden) return;
  $("sheet").hidden = false;
  $("sheet-body").innerHTML = `<div class="who-line">Ticking as <b>${esc(state.me)}</b></div>` + r.map((x) => `<section><h3>${x.label} <span class="muted">due ${x.due} · ${x.done}/${x.total}</span>${x.overdue ? ' <span class="chip negative">Late</span>' : ""}</h3>
    ${x.tasks.map((t) => `<button class="task ${t.done ? "done" : ""}" data-task="${t.id}"><span class="tick">${ICONS.check}</span><span>${esc(t.text)}${t.done ? `<br><span class="muted">${esc(t.done_by || "")} · ${t.done_at}</span>` : ""}</span></button>`).join("")}</section>`).join("");
  $("sheet-body").querySelectorAll("[data-task]").forEach((b) => (b.onclick = async () => {
    await api(`/api/routines/tasks/${b.dataset.task}/toggle`, { method: "POST", body: "{}" });
    loadTasks(true);
  }));
}

async function init() {
  $("search-icon").innerHTML = ICONS.search;
  $("logout").innerHTML = `${ICONS.logout}Sign out`;
  $("logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.href = "/login"; };
  const [status, menu] = await Promise.all([api("/api/status"), api("/api/menu")]);
  const me = await api("/api/auth/me");
  state.me = me.user.name;
  $("store").textContent = `${me.user.name} · ${me.device?.name ?? ""} · ${new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}`;
  state.menu = menu;
  render();
  renderCart();
  loadToday();
  $("search").oninput = (e) => { state.q = e.target.value.trim().toLowerCase(); render(); };
  $("tasks-btn").onclick = () => loadTasks(true);
  $("clock-btn").innerHTML = `${ICONS.clock}Clock in`;
  $("keys").innerHTML = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "⌫"].map((k) => `<button ${k ? "" : "disabled"} data-k="${k}">${k}</button>`).join("");
  $("keys").querySelectorAll("button").forEach((b) => (b.onclick = () => pressKey(b.dataset.k)));
  $("clock-btn").onclick = () => { pin = ""; renderPin(); $("pin-sheet").hidden = false; };
  $("pin-close").onclick = () => { $("pin-sheet").hidden = true; };
  $("sheet-close").onclick = () => { $("sheet").hidden = true; };
  loadTasks();
  $("tap-sim").onclick = tapped;
  $("tap-cancel").onclick = () => { $("tap").hidden = true; };
}
init().catch((e) => toast(e.message, true));
