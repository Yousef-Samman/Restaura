const state = { menu: [], cat: null, q: "", cart: [], seq: 0 };
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
  const n = state.cart.reduce((s, l) => s + l.qty, 0);
  $("count").textContent = n ? `${n} item${n > 1 ? "s" : ""}` : "";
  if (!state.cart.length) ul.innerHTML = `<li class="empty-order">${ICONS.bag}<div>Tap an item to start an order</div></li>`;
  for (const l of state.cart) {
    const li = document.createElement("li");
    li.className = "line";
    li.innerHTML = `<span class="mini">${icon(l.item.category)}</span>
      <div><div class="n">${esc(l.item.name)}</div><div class="unit num">${sar(l.item.price * l.qty)}</div>${l.eventId ? '<span class="tag">✦ HELPER</span>' : ""}</div>
      <div class="stepper"><button aria-label="Remove one">−</button><b class="num">${l.qty}</b><button aria-label="Add one">+</button></div>`;
    const [minus, plus] = li.querySelectorAll("button");
    minus.onclick = () => { l.qty -= 1; if (!l.qty) state.cart.splice(state.cart.indexOf(l), 1); renderCart(); refreshSuggestions(); };
    plus.onclick = () => add(l.item);
    ul.append(li);
  }
  const total = state.cart.reduce((s, l) => s + l.item.price * l.qty, 0);
  const net = total / 1.15;
  $("subtotal").textContent = sar2(net);
  $("vat").textContent = sar2(total - net);
  $("total").textContent = sar(total);
  $("charge").disabled = !state.cart.length;
  $("charge").textContent = state.cart.length ? `Charge ${sar(total)}` : "Charge";
}

async function refreshSuggestions() {
  const box = $("suggestions");
  if (!state.cart.length) { box.innerHTML = '<p class="hint">Add an item and I’ll suggest what fits the order.</p>'; return; }
  const seq = ++state.seq;
  box.innerHTML = '<p class="hint dots"><span></span><span></span><span></span></p>';
  try {
    const out = await api("/api/cashier/suggest", { method: "POST", body: JSON.stringify({ lines: state.cart.map((l) => ({ item_id: l.item.id, qty: l.qty })) }) });
    if (seq !== state.seq) return;
    if (!out.suggestions.length) { box.innerHTML = '<p class="hint">This order looks complete.</p>'; return; }
    box.innerHTML = "";
    for (const s of out.suggestions) {
      const d = document.createElement("div");
      d.className = "s";
      d.innerHTML = `<span class="pitch">“${esc(s.pitch)}”</span><span class="why">${esc(s.reason)}</span><button class="add">+ Add ${esc(s.name)} · ${sar(s.price)}</button>`;
      d.querySelector("button").setAttribute("aria-label", `Add ${s.name}`);
      d.querySelector("button").onclick = () => add(state.menu.find((i) => i.id === s.item_id), s.event_id);
      box.append(d);
    }
  } catch { if (seq === state.seq) box.innerHTML = '<p class="hint">Suggestions are unavailable right now.</p>'; }
}

async function loadToday() {
  const t = await api("/api/today");
  $("k-orders").textContent = t.orders;
  $("k-sales").textContent = sar(t.sales);
  $("k-addons").textContent = `${t.suggestions_accepted} · ${sar(t.suggested_sales)}`;
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
    render();
    loadToday();
  } catch (e) { toast(e.message, true); renderCart(); }
}

async function init() {
  $("search-icon").innerHTML = ICONS.search;
  $("spark").innerHTML = ICONS.spark;
  $("logout").innerHTML = `${ICONS.logout}Sign out`;
  $("logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); location.href = "/login"; };
  const [status, menu] = await Promise.all([api("/api/status"), api("/api/menu")]);
  const me = await api("/api/auth/me");
  $("store").textContent = `${me.user.name} · ${me.device?.name ?? ""} · ${new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}`;
  $("ai-badge").textContent = status.ai_enabled ? "AI on" : "Rules mode";
  $("ai-badge").classList.toggle("on", status.ai_enabled);
  state.menu = menu;
  render();
  renderCart();
  refreshSuggestions();
  loadToday();
  $("search").oninput = (e) => { state.q = e.target.value.trim().toLowerCase(); render(); };
  $("charge").onclick = charge;
  $("clear").onclick = () => { state.cart = []; renderCart(); refreshSuggestions(); };
}
init().catch((e) => toast(e.message, true));
