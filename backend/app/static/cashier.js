const state = { menu: [], cat: null, cart: [], suggestions: [], seq: 0 };
const $ = (id) => document.getElementById(id);
const sar = (n) => `${Number(n).toFixed(0)} SAR`;

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
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

function renderMenu() {
  const cats = [...new Set(state.menu.map((i) => i.category))];
  state.cat ??= cats[0];
  $("tabs").innerHTML = "";
  for (const c of cats) {
    const b = document.createElement("button");
    b.textContent = c;
    b.setAttribute("aria-pressed", c === state.cat);
    b.onclick = () => { state.cat = c; renderMenu(); };
    $("tabs").append(b);
  }
  $("grid").innerHTML = "";
  for (const item of state.menu.filter((i) => i.category === state.cat)) {
    const b = document.createElement("button");
    b.className = "item";
    b.disabled = !item.available;
    b.innerHTML = `<span class="name"></span>${item.available ? "" : '<span class="oos">Out of stock</span>'}<span class="price">${sar(item.price)}</span>`;
    b.querySelector(".name").textContent = item.name;
    b.onclick = () => add(item);
    $("grid").append(b);
  }
}

function add(item, eventId = null) {
  const line = state.cart.find((l) => l.item.id === item.id);
  if (line) { line.qty += 1; if (eventId) line.eventId = eventId; }
  else state.cart.push({ item, qty: 1, eventId });
  renderCart();
  refreshSuggestions();
}

function renderCart() {
  const ul = $("lines");
  ul.innerHTML = "";
  if (!state.cart.length) ul.innerHTML = '<li class="empty">No items yet.</li>';
  for (const l of state.cart) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="qty"><button aria-label="Remove one">−</button><b>${l.qty}</b><button aria-label="Add one">+</button></span>
      <span class="n"></span><span>${sar(l.item.price * l.qty)}</span>`;
    li.querySelector(".n").textContent = l.item.name;
    if (l.eventId) li.querySelector(".n").insertAdjacentHTML("beforeend", '<span class="tag">suggested</span>');
    const [minus, plus] = li.querySelectorAll("button");
    minus.onclick = () => { l.qty -= 1; if (!l.qty) state.cart.splice(state.cart.indexOf(l), 1); renderCart(); refreshSuggestions(); };
    plus.onclick = () => add(l.item);
    ul.append(li);
  }
  const total = state.cart.reduce((s, l) => s + l.item.price * l.qty, 0);
  $("total").textContent = sar(total);
  $("charge").disabled = !state.cart.length;
}

async function refreshSuggestions() {
  const box = $("suggestions");
  if (!state.cart.length) { box.innerHTML = '<p class="hint">Add an item and I\'ll suggest what fits.</p>'; return; }
  const seq = ++state.seq;
  box.innerHTML = '<p class="hint">Thinking…</p>';
  try {
    const out = await api("/api/cashier/suggest", { method: "POST", body: JSON.stringify({ lines: state.cart.map((l) => ({ item_id: l.item.id, qty: l.qty })) }) });
    if (seq !== state.seq) return;
    box.innerHTML = "";
    if (!out.suggestions.length) { box.innerHTML = '<p class="hint">Nothing to add. This order looks complete.</p>'; return; }
    for (const s of out.suggestions) {
      const d = document.createElement("div");
      d.className = "s";
      d.innerHTML = `<span class="pitch"></span><span class="why"></span><button>Add ${s.name} · ${sar(s.price)}</button>`;
      d.querySelector(".pitch").textContent = `“${s.pitch}”`;
      d.querySelector(".why").textContent = s.reason;
      d.querySelector("button").onclick = () => add(state.menu.find((i) => i.id === s.item_id), s.event_id);
      box.append(d);
    }
  } catch (e) { box.innerHTML = '<p class="hint">Suggestions are unavailable right now.</p>'; }
}

async function charge() {
  $("charge").disabled = true;
  try {
    const out = await api("/api/orders", { method: "POST", body: JSON.stringify({ lines: state.cart.map((l) => ({ item_id: l.item.id, qty: l.qty, suggestion_event_id: l.eventId })) }) });
    toast(`Order #${out.order_id} charged · ${sar(out.total)}`);
    state.cart = [];
    renderCart();
    refreshSuggestions();
    state.menu = await api("/api/menu");
    renderMenu();
  } catch (e) { toast(e.message, true); $("charge").disabled = false; }
}

async function init() {
  const [status, menu] = await Promise.all([api("/api/status"), api("/api/menu")]);
  $("store").textContent = status.store;
  $("ai-badge").textContent = status.ai_enabled ? "AI on" : "Rules mode";
  $("ai-badge").classList.toggle("on", status.ai_enabled);
  state.menu = menu;
  renderMenu();
  renderCart();
  $("charge").onclick = charge;
  $("clear").onclick = () => { state.cart = []; renderCart(); refreshSuggestions(); };
}
init().catch((e) => toast(e.message, true));
