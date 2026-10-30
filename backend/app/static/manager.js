const $ = (id) => document.getElementById(id);
const sar = (n) => `${Number(n).toLocaleString("en-US", { maximumFractionDigits: 0 })} SAR`;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (n) => Number(n).toLocaleString("en-US", { maximumFractionDigits: 1 });
const TABS = [
  { id: "today", label: "Today", icon: "today" },
  { id: "orders", label: "Orders", icon: "orders" },
  { id: "stock", label: "Stock", icon: "stock" },
  { id: "deliveries", label: "Deliveries", icon: "delivery" },
];
let tab = location.hash.slice(1) || "today";
let status = {};

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
  $("tabs").innerHTML = TABS.map((t) => `<button data-tab="${t.id}" ${t.id === tab ? 'aria-current="page"' : ""}>${ICONS[t.icon]}${t.label}
    ${t.id === "orders" && today.drafts ? `<span class="dot">${today.drafts}</span>` : ""}${t.id === "stock" && today.low_stock ? `<span class="dot">${today.low_stock}</span>` : ""}</button>`).join("");
  $("tabs").querySelectorAll("button").forEach((b) => (b.onclick = () => go(b.dataset.tab)));
}

function go(t) { tab = t; location.hash = t; render(); window.scrollTo(0, 0); }

async function render() {
  $("title").textContent = TABS.find((t) => t.id === tab).label;
  document.body.classList.toggle("has-hero", tab === "today");
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
  async today() {
    const [t, ins, runs, devs] = await Promise.all([api("/api/today"), api("/api/insights/cashier"), api("/api/agents/runs"), api("/api/devices")]);
    const rate = ins.acceptance_rate == null ? "–" : `${Math.round(ins.acceptance_rate * 100)}%`;
    return `<div class="hero">
        <div><div class="label">Sales</div><div class="value num">${sar(t.sales)}</div></div>
        <div><div class="label">Orders</div><div class="value num">${t.orders}</div></div>
        <div><div class="label">Avg. ticket</div><div class="value num">${sar(t.avg_ticket)}</div></div>
        <div><div class="label">Helper sales</div><div class="value num">${sar(t.suggested_sales)}</div></div>
      </div>
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
        ${po.status === "sent" ? `<div class="btns"><button class="approve receive">Mark as delivered</button></div>` : ""}
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
      <div class="section"><h2>Emails to suppliers</h2><div class="panel">${mails.length ? mails.slice(0, 8).map((m) => `<div class="list-item"><span>${esc(m.subject)}<br><span class="muted">${esc(m.to)}</span></span><span class="chip ${m.status === "sent" ? "received" : m.status === "failed" ? "negative" : "draft"}">${m.status}</span></div>`).join("") : '<div class="muted">No emails yet.</div>'}</div></div>`;
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
  today() {
    bindAgent();
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
