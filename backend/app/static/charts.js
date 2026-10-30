// Small SVG charts. Line, column and bar charts carry one series, so the title names it and no legend is needed.
// The donut has one slice per category, with a legend that names each one.
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
  // line with a soft area, for change over time; crosshair and dot follow the pointer
  function line(host, data, { color = css("--chart"), height = 200, labelEvery = 1, area = true } = {}) {
    host.classList.add("chart"); host.innerHTML = "";
    const W = host.clientWidth || 320, H = height, L = 40, R = 8, B = 24, T = 10;
    const max = niceMax(Math.max(...data.map((d) => d.value)));
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img" });
    for (let i = 0; i <= 4; i++) {
      const y = T + (H - T - B) * (1 - i / 4);
      svg.append(el("line", { x1: L, x2: W, y1: y, y2: y, stroke: css("--line"), "stroke-width": 1 }));
      const tx = el("text", { x: L - 8, y: y + 4, "text-anchor": "end", class: "tick" }); tx.textContent = fmt((max * i) / 4); svg.append(tx);
    }
    const step = (W - L - R) / Math.max(1, data.length - 1);
    const pts = data.map((d, i) => [L + step * i, T + (H - T - B) * (1 - d.value / max)]);
    const dLine = pts.map((p, i) => `${i ? "L" : "M"}${p[0]},${p[1]}`).join("");
    if (area) {
      const gid = `g${Math.random().toString(36).slice(2, 8)}`;
      const g = el("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 });
      g.append(el("stop", { offset: 0, "stop-color": color, "stop-opacity": 0.22 }), el("stop", { offset: 1, "stop-color": color, "stop-opacity": 0 }));
      const defs = el("defs"); defs.append(g); svg.append(defs);
      svg.append(el("path", { d: `${dLine}L${pts.at(-1)[0]},${H - B}L${L},${H - B}Z`, fill: `url(#${gid})` }));
    }
    svg.append(el("path", { d: dLine, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    data.forEach((d, i) => {
      if (i % labelEvery === 0) { const tx = el("text", { x: pts[i][0], y: H - 6, "text-anchor": "middle", class: "tick" }); tx.textContent = d.label; svg.append(tx); }
    });
    const cross = el("line", { y1: T, y2: H - B, stroke: css("--muted"), "stroke-width": 1, "stroke-dasharray": "3 3", opacity: 0 });
    const dot = el("circle", { r: 5, fill: color, stroke: css("--paper"), "stroke-width": 2, opacity: 0 });
    svg.append(cross, dot);
    const tip = tooltip(host);
    const hit = el("rect", { x: L, y: T, width: W - L, height: H - T - B, fill: "transparent" });
    hit.addEventListener("pointermove", (e) => {
      const r = svg.getBoundingClientRect(), x = ((e.clientX - r.left) * W) / r.width;
      const i = Math.max(0, Math.min(data.length - 1, Math.round((x - L) / step)));
      const [px, py] = pts[i];
      cross.setAttribute("x1", px); cross.setAttribute("x2", px); cross.setAttribute("opacity", 1);
      dot.setAttribute("cx", px); dot.setAttribute("cy", py); dot.setAttribute("opacity", 1);
      tip.show(data[i].tip, px, Math.max(py, T + 30));
    });
    hit.addEventListener("pointerleave", () => { tip.hide(); cross.setAttribute("opacity", 0); dot.setAttribute("opacity", 0); });
    svg.append(hit);
    host.prepend(svg);
  }

  // donut for parts of a whole (five slices at most), with a legend listing value and share
  const SLICES = ["#0E8A62", "#D19A2A", "#3F7FC1", "#C25B3A", "#8C64B0"];
  function donut(host, data, { center = "", size = 180 } = {}) {
    host.classList.add("chart", "donut"); host.innerHTML = "";
    const total = data.reduce((a, d) => a + d.value, 0) || 1, R = size / 2, r = R * 0.62;
    const svg = el("svg", { viewBox: `0 0 ${size} ${size}`, width: size, height: size, role: "img" });
    const tip = tooltip(host);
    let a0 = -Math.PI / 2;
    const pt = (rad, a) => [R + rad * Math.cos(a), R + rad * Math.sin(a)];
    data.forEach((d, i) => {
      const a1 = a0 + (2 * Math.PI * d.value) / total, big = a1 - a0 > Math.PI ? 1 : 0;
      const [x0, y0] = pt(R, a0), [x1, y1] = pt(R, Math.min(a1, a0 + 2 * Math.PI - 1e-4)), [x2, y2] = pt(r, Math.min(a1, a0 + 2 * Math.PI - 1e-4)), [x3, y3] = pt(r, a0);
      const seg = el("path", { d: `M${x0},${y0}A${R},${R} 0 ${big} 1 ${x1},${y1}L${x2},${y2}A${r},${r} 0 ${big} 0 ${x3},${y3}Z`, fill: SLICES[i % SLICES.length], stroke: css("--paper"), "stroke-width": 2 });
      const mid = (a0 + a1) / 2, [tx, ty] = pt((R + r) / 2, mid);
      seg.addEventListener("pointerenter", () => tip.show(d.tip, tx, ty));
      seg.addEventListener("pointerleave", () => tip.hide());
      svg.append(seg); a0 = a1;
    });
    const c1 = el("text", { x: R, y: R - 2, "text-anchor": "middle", class: "dc-v" }); c1.textContent = Math.round(total).toLocaleString("en-US");
    const c2 = el("text", { x: R, y: R + 16, "text-anchor": "middle", class: "dc-l" }); c2.textContent = center;
    svg.append(c1, c2);
    const legend = document.createElement("ul"); legend.className = "legend";
    legend.innerHTML = data.map((d, i) => `<li><i style="background:${SLICES[i % SLICES.length]}"></i><span>${d.label}</span><b class="num">${Math.round((100 * d.value) / total)}%</b></li>`).join("");
    host.prepend(svg); host.append(legend);
  }
  return { columns, bars, line, donut, fmt };
})();
