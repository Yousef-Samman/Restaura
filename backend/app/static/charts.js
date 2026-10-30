// Small SVG charts: one series each, so the title names the series and no legend is needed.
const Charts = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const nice = (v) => { if (v <= 0) return 1; const p = 10 ** Math.floor(Math.log10(v)); const n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p; };
  const niceMax = (v) => nice(v / 4) * 4;  // four clean steps
  const fmt = (v) => (v >= 10000 ? `${Math.round(v / 1000)}K` : Math.round(v).toLocaleString("en-US"));
  const el = (tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
  // a column with a 4px rounded data-end and a square baseline
  const colPath = (x, y, w, h) => { const r = Math.min(4, h, w / 2); return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`; };
  const barPath = (x, y, w, h) => { const r = Math.min(4, w, h / 2); return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`; };

  function tooltip(host) {
    let t = host.querySelector(".ctip");
    if (!t) { t = document.createElement("div"); t.className = "ctip"; host.append(t); }
    return {
      show(html, x, y) { t.innerHTML = html; t.style.opacity = 1; const w = t.offsetWidth; t.style.left = `${Math.max(0, Math.min(host.clientWidth - w, x - w / 2))}px`; t.style.top = `${y - t.offsetHeight - 10}px`; },
      hide() { t.style.opacity = 0; },
    };
  }

  function columns(host, data, { color = css("--chart"), height = 200, labelEvery = 1 } = {}) {
    host.classList.add("chart"); host.innerHTML = "";
    const W = host.clientWidth || 320, H = height, L = 40, B = 24, T = 10;
    const max = niceMax(Math.max(...data.map((d) => d.value)));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" });
    for (let i = 0; i <= 4; i++) {
      const y = T + (H - T - B) * (1 - i / 4);
      svg.append(el("line", { x1: L, x2: W, y1: y, y2: y, stroke: css("--line"), "stroke-width": 1 }));
      const tx = el("text", { x: L - 8, y: y + 4, "text-anchor": "end", class: "tick" }); tx.textContent = fmt((max * i) / 4); svg.append(tx);
    }
    const slot = (W - L) / data.length, bw = Math.min(24, slot * 0.62);
    const tip = tooltip(host);
    data.forEach((d, i) => {
      const h = ((H - T - B) * d.value) / max, x = L + slot * i + (slot - bw) / 2, y = H - B - h;
      if (h > 0) svg.append(el("path", { d: colPath(x, y, bw, h), fill: color }));
      if (i % labelEvery === 0) { const tx = el("text", { x: x + bw / 2, y: H - 6, "text-anchor": "middle", class: "tick" }); tx.textContent = d.label; svg.append(tx); }
      const hit = el("rect", { x: L + slot * i, y: T, width: slot, height: H - T - B, fill: "transparent" });
      hit.addEventListener("pointerenter", () => tip.show(d.tip, x + bw / 2, Math.max(y, T + 30)));
      hit.addEventListener("pointerleave", () => tip.hide());
      svg.append(hit);
    });
    host.prepend(svg);
  }

  function bars(host, data, { color = css("--chart"), unit = "" } = {}) {
    host.classList.add("chart"); host.innerHTML = "";
    const W = host.clientWidth || 320, row = 34, H = data.length * row, labelW = Math.min(150, W * 0.42), valW = 74;
    const max = Math.max(...data.map((d) => d.value), 1);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" });
    const tip = tooltip(host);
    data.forEach((d, i) => {
      const y = i * row, w = ((W - labelW - valW) * d.value) / max;
      const name = el("text", { x: 0, y: y + row / 2 + 4, class: "lbl" }); name.textContent = d.label; svg.append(name);
      svg.append(el("path", { d: barPath(labelW, y + (row - 18) / 2, Math.max(w, 2), 18), fill: color }));
      const v = el("text", { x: labelW + w + 8, y: y + row / 2 + 4, class: "val" }); v.textContent = `${Math.round(d.value).toLocaleString("en-US")}${unit}`; svg.append(v);
      const hit = el("rect", { x: 0, y, width: W, height: row, fill: "transparent" });
      hit.addEventListener("pointerenter", () => tip.show(d.tip, labelW + w / 2, y + 6));
      hit.addEventListener("pointerleave", () => tip.hide());
      svg.append(hit);
    });
    host.prepend(svg);
    // shorten names that would run into the bar; the tooltip keeps the full name
    svg.querySelectorAll("text.lbl").forEach((t) => {
      const full = t.textContent;
      while (t.getComputedTextLength() > labelW - 10 && t.textContent.length > 4) t.textContent = t.textContent.slice(0, -2) + "…";
      if (t.textContent !== full) t.append(Object.assign(el("title"), { textContent: full }));
    });
  }
  return { columns, bars, fmt };
})();
