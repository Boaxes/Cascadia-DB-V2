/*
 * The dashboard's charts, drawn as SVG with nothing to load.
 *
 * Magnitudes only, so one hue: the site's sea blue, columns for time and
 * bars for ranked categories. Thin marks with a 4px rounded end, hairline
 * gridlines, and a tooltip on every mark. Each chart fills its card, so the
 * whole dashboard fits one screen.
 */
(function () {
  var data = JSON.parse(document.getElementById("chart-data").textContent);
  var css = getComputedStyle(document.documentElement);
  var INK = css.getPropertyValue("--accent").trim() || "#1f5f7c";
  var GRID = css.getPropertyValue("--border-soft").trim() || "#e8eef2";
  var NS = "http://www.w3.org/2000/svg";
  var fmt = function (n) { return n.toLocaleString(); };

  var tip = document.createElement("div");
  tip.className = "chart-tip";
  document.body.appendChild(tip);
  function showTip(e, label, value, unit) {
    tip.innerHTML = "";
    var v = document.createElement("strong"); v.textContent = fmt(value) + " " + unit;
    var l = document.createElement("span"); l.textContent = label;
    tip.appendChild(v); tip.appendChild(l);
    tip.style.display = "block";
    tip.style.left = (e.clientX + 12) + "px";
    tip.style.top = (e.clientY - 12) + "px";
  }
  function hideTip() { tip.style.display = "none"; }

  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }
  function niceMax(v) {
    var p = Math.pow(10, Math.floor(Math.log10(v || 1)));
    return [1, 2, 2.5, 5, 10].map(function (m) { return m * p; }).find(function (m) { return m >= v; });
  }
  /* A bar with a 4px rounded end away from the baseline. */
  function barPath(x, y, w, h, horizontal) {
    var r = Math.min(4, w / 2, h);
    if (horizontal) return "M" + x + "," + y + "h" + (h - r) + "q" + r + ",0 " + r + "," + r +
      "v" + (w - 2 * r) + "q0," + r + " -" + r + "," + r + "h-" + (h - r) + "z";
    return "M" + x + "," + (y + h) + "v-" + (h - r) + "q0,-" + r + " " + r + ",-" + r +
      "h" + (w - 2 * r) + "q" + r + ",0 " + r + "," + r + "v" + (h - r) + "z";
  }
  function hover(node, label, value, unit) {
    node.addEventListener("pointermove", function (e) { showTip(e, label, value, unit); });
    node.addEventListener("pointerleave", hideTip);
  }

  function column(W, H, d) {
    var L = 38, B = 18, T = 6;
    var max = niceMax(Math.max.apply(null, d.values));
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", "aria-label": d.title });
    for (var i = 0; i <= 2; i++) {
      var y = T + (H - T - B) * (1 - i / 2);
      el("line", { x1: L, x2: W, y1: y, y2: y, stroke: GRID }, svg);
      el("text", { x: L - 6, y: y + 4, "text-anchor": "end", class: "chart-axis" }, svg).textContent = fmt(max * i / 2);
    }
    var band = (W - L) / d.values.length, bw = Math.min(24, band * 0.7);
    var every = Math.ceil(d.values.length / Math.max(1, Math.floor((W - L) / 34)));
    d.values.forEach(function (v, i) {
      var h = (H - T - B) * v / max, x = L + band * i + (band - bw) / 2;
      if (h > 0) el("path", { d: barPath(x, H - B - h, bw, h), fill: INK }, svg);
      hover(el("rect", { x: L + band * i, y: T, width: band, height: H - T - B, fill: "transparent" }, svg),
            d.labels[i], v, d.unit);
      if (i % every === 0)
        el("text", { x: L + band * i + band / 2, y: H - 4, "text-anchor": "middle", class: "chart-axis" }, svg)
          .textContent = d.labels[i];
    });
    return svg;
  }

  function bar(W, H, d) {
    var row = H / d.values.length, L = Math.min(150, W * 0.45), R = 46;
    var thick = Math.min(12, row * 0.6);
    var max = Math.max.apply(null, d.values);
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img", "aria-label": d.title });
    d.values.forEach(function (v, i) {
      var y = i * row, mid = y + row / 2, w = (W - L - R) * v / max;
      var textX = 0;
      if (d.dots) { el("circle", { cx: 4, cy: mid, r: 3.5, fill: d.dots[i] }, svg); textX = 12; }
      var label = d.labels[i], room = Math.floor((L - textX - 6) / 6.3);
      el("text", { x: textX, y: mid + 4, class: "chart-label" }, svg).textContent =
        label.length > room ? label.slice(0, room - 1) + "…" : label;
      el("path", { d: barPath(L, mid - thick / 2, thick, Math.max(w, 2), true), fill: INK }, svg);
      el("text", { x: L + w + 5, y: mid + 4, class: "chart-value" }, svg).textContent = fmt(v);
      hover(el("rect", { x: 0, y: y, width: W, height: row, fill: "transparent" }, svg), label, v, d.unit);
    });
    return svg;
  }

  var cards = document.querySelectorAll("[data-chart]");
  cards.forEach(function (card) {
    var d = data[card.dataset.chart];
    var h = document.createElement("h3");
    h.textContent = d.title;
    var body = document.createElement("div");
    body.className = "chart-body";
    card.appendChild(h); card.appendChild(body);
  });
  function drawAll() {
    cards.forEach(function (card) {
      var d = data[card.dataset.chart], body = card.querySelector(".chart-body");
      body.innerHTML = "";
      if (card.closest(".folded")) return;
      var W = body.clientWidth, H = body.clientHeight;
      if (W < 50 || H < 40) return;
      body.appendChild((card.dataset.kind === "bar" ? bar : column)(W, H, d));
    });
  }
  /* The two sections, Needs attention and Statistics, fold away by clicking
     their titles, and stay folded next time. The charts are drawn again to
     fill whatever room is left. */
  var KEY = "admin-dashboard-folded";
  function folded() {
    try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch (e) { return []; }
  }
  document.querySelectorAll("[data-band]").forEach(function (band) {
    var name = band.dataset.band;
    if (folded().indexOf(name) !== -1) band.classList.add("folded");
    band.querySelector(".dash-toggle").addEventListener("click", function () {
      band.classList.toggle("folded");
      var names = folded().filter(function (n) { return n !== name; });
      if (band.classList.contains("folded")) names.push(name);
      try { localStorage.setItem(KEY, JSON.stringify(names)); } catch (e) { /* private window */ }
      drawAll();
    });
  });

  drawAll();
  window.addEventListener("resize", drawAll);
})();
