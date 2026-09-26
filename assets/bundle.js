/* Liquidity Radar — chart engine. window.LiquidityRadar
   liquidity-radar-design/design-system/components/bundle.js에서 복사.
   시안용 LR.demo를 떼어냈고, S&P 비교 띠는 app.js가 채우는 LR.spx({dates, values})를 쓴다. */
(function () {
  var NS = "http://www.w3.org/2000/svg";
  var LR = { period: "1y", charts: [] };
  function el(n, a, p) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }
  function h(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function cvar(name) { return "var(--" + name + ")"; }
  var DAY = 864e5;
  function toT(s) { return Date.parse(s + "T00:00:00Z"); }
  function startIndex(dates, period) {
    if (period === "3y") return 0;
    var months = period === "6m" ? 6 : 12;
    var last = new Date(toT(dates[dates.length - 1]));
    last.setUTCMonth(last.getUTCMonth() - months);
    var t = last.getTime();
    for (var i = 0; i < dates.length; i++) if (toT(dates[i]) >= t) return i;
    return 0;
  }
  function nice(lo, hi, n) {
    if (lo === hi) { lo -= 1; hi += 1; }
    var span = hi - lo, step = Math.pow(10, Math.floor(Math.log10(span / n))), err = span / n / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    var a = Math.floor(lo / step) * step, b = Math.ceil(hi / step) * step, ticks = [];
    for (var v = a; v <= b + step / 2; v += step) ticks.push(+v.toFixed(10));
    return { lo: a, hi: b, ticks: ticks, step: step };
  }
  function fmtTick(v, step) { var d = step < 0.01 ? 3 : step < 0.1 ? 2 : step < 1 ? 1 : 0; return (v < 0 ? "−" : "") + Math.abs(v).toFixed(d); }
  function xTicks(t0, t1, px) {
    var out = [], months = (t1 - t0) / DAY / 30.4, stepM = 12;
    [1, 2, 3, 6, 12].some(function (s) { if (months / s * 60 <= (px || 800)) { stepM = s; return true; } });
    var d = new Date(t0); d.setUTCDate(1); d.setUTCMonth(d.getUTCMonth() + 1);
    while (d.getTime() <= t1) {
      var m = d.getUTCMonth();
      if (m % stepM === 0) out.push({ t: d.getTime(), label: m === 0 ? String(d.getUTCFullYear()) : (m + 1) + "월", major: m === 0 });
      d.setUTCMonth(m + 1);
    }
    return out;
  }
  function legend(series) {
    var lg = h("div", "lr-chart__legend");
    series.forEach(function (s) {
      lg.appendChild(h("span", "", '<i style="background:' + cvar(s.color) + (s.dash ? ';background:none;border-top:2px dashed ' + cvar(s.color) + ';height:0' : '') + '"></i>' + s.label));
    });
    return lg;
  }


  /* ---------- S&P 500 comparison strip (own y-axis, shared x/crosshair) ---------- */
  var OV_H = 112, OV_GAP = 20;
  function useOverlay(spec) { return LR.overlay && !!LR.spx && !spec.mini && spec.overlay !== false; }
  function overlayStrip(svg, t0, t1, x0, x1, top) {
    var S = LR.spx, TT = S.dates.map(toT), a = 0, b = TT.length - 1;
    while (a < b && TT[a + 1] <= t0) a++;
    while (b > a && TT[b - 1] >= t1) b--;
    var base = S.values[a], pts = [];
    for (var i = a; i <= b; i++) pts.push({ t: TT[i], d: S.dates[i], v: S.values[i] / base * 100 });
    var lo = Infinity, hi = -Infinity; pts.forEach(function (p) { lo = Math.min(lo, p.v); hi = Math.max(hi, p.v); });
    var yN = nice(lo, hi, 2), h = OV_H - 20, y0 = top + 20;
    var X = function (t) { return x0 + (Math.max(t0, Math.min(t1, t)) - t0) / Math.max(1, t1 - t0) * (x1 - x0); };
    var Y = function (v) { return y0 + (yN.hi - v) / (yN.hi - yN.lo) * h; };
    var lab = el("text", { class: "c-ovlabel", x: x0, y: top + 10 }, svg); lab.textContent = "S&P 500 · 기간 시작=100 · 모양만 비교합니다";
    el("line", { class: "c-divider", x1: x0, x2: x1, y1: top - OV_GAP / 2, y2: top - OV_GAP / 2 }, svg);
    yN.ticks.forEach(function (v) {
      el("line", { class: "c-grid", x1: x0, x2: x1, y1: Y(v), y2: Y(v) }, svg);
      var t = el("text", { class: "c-tick", x: x0 - 8, y: Y(v) + 4, "text-anchor": "end" }, svg); t.textContent = fmtTick(v, yN.step);
    });
    el("path", { class: "c-line", d: "M" + pts.map(function (p) { return X(p.t).toFixed(1) + "," + Y(p.v).toFixed(1); }).join("L"), style: "stroke:" + cvar("series-spx") }, svg);
    var dot = el("circle", { r: 4, style: "fill:" + cvar("series-spx") + ";stroke:" + cvar("surface-raised") + ";stroke-width:2", visibility: "hidden" }, svg);
    return {
      bottom: top + OV_H,
      at: function (t) { var k = 0, bd = Infinity; pts.forEach(function (p, j) { var dd = Math.abs(p.t - t); if (dd < bd) { bd = dd; k = j; } }); var p = pts[k]; dot.setAttribute("cx", X(t)); dot.setAttribute("cy", Y(p.v)); dot.setAttribute("visibility", "visible"); return p; },
      hide: function () { dot.setAttribute("visibility", "hidden"); },
      row: function (p) { return '<div class="lr-tip__row"><i style="background:' + cvar("series-spx") + '"></i><span>S&amp;P 500 (시작=100, ' + p.d.slice(5) + ')</span><b>' + p.v.toFixed(1) + "</b></div>"; }
    };
  }

  /* ---------- line / area ---------- */
  function drawXY(root, spec) {
    var dates = spec.dates, i0 = spec.fixedStart != null ? spec.fixedStart : startIndex(dates, spec.period || LR.period);
    var D = dates.slice(i0), T = D.map(toT), n = D.length;
    var series = spec.series.map(function (s) {
      var v = s.values.slice(i0);
      if (spec.index100) { var b = v[0]; v = v.map(function (x) { return x / b * 100; }); }
      return Object.assign({}, s, { v: v });
    });
    if (spec.stacked) { var acc = new Array(n).fill(0); series.forEach(function (s) { s.base = acc.slice(); s.top = s.v.map(function (x, i) { return acc[i] += x; }); }); }
    var mini = !!spec.mini, W = root.clientWidth || 600, H = spec.height || (mini ? 140 : 320);
    var endLabels = !mini && spec.endLabels !== false && W >= 560;
    var m = { l: mini ? 40 : 52, r: endLabels ? 104 : (spec.thresholds ? 64 : 12), t: 12, b: 28 };
    var lo = Infinity, hi = -Infinity;
    series.forEach(function (s) { (s.top || s.v).forEach(function (x) { if (x < lo) lo = x; if (x > hi) hi = x; }); if (s.base) lo = Math.min(lo, 0); });
    (spec.thresholds || []).forEach(function (t) { if (t.value < lo) lo = t.value; if (t.value > hi) hi = t.value; });
    if (spec.includeZero || spec.stacked) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    var pad = (hi - lo) * 0.06; if (!spec.stacked && !spec.includeZero) { lo -= pad; } hi += pad;
    var yN = nice(lo, hi, mini ? 3 : 5);
    var X = function (t) { return m.l + (t - T[0]) / Math.max(1, T[n - 1] - T[0]) * (W - m.l - m.r); };
    var Y = function (v) { return m.t + (yN.hi - v) / (yN.hi - yN.lo) * (H - m.t - m.b); };
    var ovOn = useOverlay(spec), SH = ovOn ? H + OV_GAP + OV_H : H;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + SH, width: W, height: SH, role: "img", "aria-label": spec.aria || "" });
    var ov = ovOn ? overlayStrip(svg, T[0], T[n - 1], m.l, W - m.r, H + OV_GAP) : null;
    yN.ticks.forEach(function (v) {
      el("line", { class: v === 0 ? "c-zero" : "c-grid", x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, svg);
      var t = el("text", { class: "c-tick", x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" }, svg); t.textContent = fmtTick(v, yN.step);
    });
    xTicks(T[0], T[n - 1], W - m.l - m.r).forEach(function (k) {
      var t = el("text", { class: "c-tick" + (k.major ? " c-major" : ""), x: X(k.t), y: H - 8, "text-anchor": "middle" }, svg); t.textContent = k.label;
    });
    (spec.thresholds || []).forEach(function (th) {
      el("line", { x1: m.l, x2: W - m.r, y1: Y(th.value), y2: Y(th.value), style: "stroke:" + cvar(th.color || "line-strong") + ";stroke-width:1" }, svg);
      var t = el("text", { class: "c-th", x: W - m.r + 6, y: Y(th.value) + 4, style: "fill:" + cvar(th.color || "ink-muted") }, svg); t.textContent = th.label;
    });
    series.forEach(function (s) {
      if (s.top) {
        var d = "M" + s.top.map(function (v, i) { return X(T[i]).toFixed(1) + "," + Y(v).toFixed(1); }).join("L");
        for (var i = n - 1; i >= 0; i--) d += "L" + X(T[i]).toFixed(1) + "," + Y(s.base[i]).toFixed(1);
        el("path", { d: d + "Z", style: "fill:" + cvar(s.color) + ";stroke:" + cvar("surface-raised") + ";stroke-width:1" }, svg);
      } else {
        el("path", { d: "M" + s.v.map(function (v, i) { return X(T[i]).toFixed(1) + "," + Y(v).toFixed(1); }).join("L"), class: "c-line", style: "stroke:" + cvar(s.color) + (s.dash ? ";stroke-dasharray:6 4" : "") }, svg);
      }
    });
    if (endLabels) {
      var labs = series.map(function (s) { var v = s.top ? (s.top[n - 1] + s.base[n - 1]) / 2 : s.v[n - 1]; return { s: s, y: Y(v) }; }).sort(function (a, b) { return a.y - b.y; });
      for (var i = 1; i < labs.length; i++) if (labs[i].y - labs[i - 1].y < 15) labs[i].y = labs[i - 1].y + 15;
      labs.forEach(function (l) { var t = el("text", { class: "c-end", x: W - m.r + 8, y: l.y + 4, style: "fill:" + cvar(l.s.color) }, svg); t.textContent = l.s.short || l.s.label; });
    }
    // crosshair
    var cross = el("line", { class: "c-cross", y1: m.t, y2: ov ? ov.bottom : H - m.b, visibility: "hidden" }, svg);
    var dots = series.map(function (s) { return el("circle", { r: 4, style: "fill:" + cvar(s.color) + ";stroke:" + cvar("surface-raised") + ";stroke-width:2", visibility: "hidden" }, svg); });
    var hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: (ov ? ov.bottom : H - m.b) - m.t, fill: "transparent" }, svg);
    var tip = h("div", "lr-tip"); tip.hidden = true;
    var fmt = spec.fmt || function (v) { return v.toFixed(2); };
    function show(i) {
      var x = X(T[i]); cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      var rows = series.map(function (s, k) {
        var yv = s.top ? s.top[i] : s.v[i]; dots[k].setAttribute("cx", x); dots[k].setAttribute("cy", Y(yv)); dots[k].setAttribute("visibility", "visible");
        return '<div class="lr-tip__row"><i style="background:' + cvar(s.color) + '"></i><span>' + s.label + '</span><b>' + fmt(s.v[i], s) + "</b></div>";
      });
      if (ov) rows.push(ov.row(ov.at(T[i])));
      if (spec.stacked) rows.push('<div class="lr-tip__row lr-tip__total"><span>합계</span><b>' + fmt(series[series.length - 1].top[i]) + "</b></div>");
      tip.innerHTML = "<b>" + D[i] + "</b>" + rows.join("");
      tip.hidden = false;
      var tw = tip.offsetWidth; tip.style.left = (x + 12 + tw > W ? x - 12 - tw : x + 12) + "px"; tip.style.top = m.t + "px";
    }
    function near(px) { var t = T[0] + (px - m.l) / (W - m.l - m.r) * (T[n - 1] - T[0]), b = 0, bd = Infinity; for (var i = 0; i < n; i++) { var dd = Math.abs(T[i] - t); if (dd < bd) { bd = dd; b = i; } } return b; }
    hit.addEventListener("mousemove", function (e) { var r = svg.getBoundingClientRect(); show(near(e.clientX - r.left)); });
    hit.addEventListener("mouseleave", function () { cross.setAttribute("visibility", "hidden"); dots.forEach(function (d) { d.setAttribute("visibility", "hidden"); }); if (ov) ov.hide(); tip.hidden = true; });
    root.innerHTML = "";
    if (series.length > 1 && spec.legend !== false) root.appendChild(legend(series));
    var wrap = h("div", "lr-chart__plot"); wrap.appendChild(svg); wrap.appendChild(tip); root.appendChild(wrap);
    if (spec.demoAt != null) show(spec.demoAt === "last" ? n - 1 : Math.round(n * spec.demoAt));
  }

  /* ---------- log bars ---------- */
  function drawBars(root, spec) {
    var dates = spec.dates, i0 = startIndex(dates, spec.period || LR.period), D = dates.slice(i0), V = spec.values.slice(i0), n = D.length, T = D.map(toT);
    var W = root.clientWidth || 600, H = spec.height || 300, m = { l: 56, r: 72, t: 12, b: 28 };
    var lo = -2, hi = 2; // 0.01 .. 100 ($B)
    var X = function (t) { return m.l + (t - T[0]) / Math.max(1, T[n - 1] - T[0]) * (W - m.l - m.r); };
    var Y = function (v) { return m.t + (hi - Math.log10(v)) / (hi - lo) * (H - m.t - m.b); };
    var ovOn = useOverlay(spec), SH = ovOn ? H + OV_GAP + OV_H : H;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + SH, width: W, height: SH, role: "img", "aria-label": spec.aria || "" });
    var ov = ovOn ? overlayStrip(svg, T[0], T[n - 1], m.l, W - m.r, H + OV_GAP) : null;
    [0.01, 0.1, 1, 10, 100].forEach(function (v) {
      el("line", { class: "c-grid", x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) }, svg);
      var t = el("text", { class: "c-tick", x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" }, svg); t.textContent = v >= 1 ? "$" + v + "B" : "$" + (v * 1000) + "M";
    });
    [{ v: 1, c: "pressure-2", l: "$1B 주의" }, { v: 10, c: "pressure-3", l: "$10B 심각" }].forEach(function (th) {
      el("line", { x1: m.l, x2: W - m.r, y1: Y(th.v), y2: Y(th.v), style: "stroke:" + cvar(th.c) }, svg);
      var t = el("text", { class: "c-th", x: W - m.r + 6, y: Y(th.v) + 4, style: "fill:" + cvar(th.c) }, svg); t.textContent = th.l;
    });
    xTicks(T[0], T[n - 1], W - m.l - m.r).forEach(function (k) { var t = el("text", { class: "c-tick" + (k.major ? " c-major" : ""), x: X(k.t), y: H - 8, "text-anchor": "middle" }, svg); t.textContent = k.label; });
    var bw = Math.max(2, Math.min(6, (W - m.l - m.r) / n * 0.8));
    var col = function (v) { return v >= 10 ? "pressure-3" : v >= 1 ? "pressure-2" : "series-other"; };
    V.forEach(function (v, i) { if (v <= 0) return; var y = Y(Math.max(v, 0.0101)); el("rect", { x: X(T[i]) - bw / 2, y: y, width: bw, height: Y(0.01) - y, style: "fill:" + cvar(col(v)) }, svg); });
    el("line", { class: "c-zero", x1: m.l, x2: W - m.r, y1: Y(0.01), y2: Y(0.01) }, svg);
    var cross = el("line", { class: "c-cross", y1: m.t, y2: ov ? ov.bottom : H - m.b, visibility: "hidden" }, svg);
    var hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: (ov ? ov.bottom : H - m.b) - m.t, fill: "transparent" }, svg);
    var tip = h("div", "lr-tip"); tip.hidden = true;
    function money(v) { return v === 0 ? "$0" : v >= 1 ? "$" + v.toFixed(1) + "B" : "$" + Math.round(v * 1000) + "M"; }
    function show(i) {
      var x = X(T[i]); cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
      var v = V[i], lab = v >= 10 ? "심각" : v >= 1 ? "주의" : "노이즈";
      tip.innerHTML = "<b>" + D[i] + '</b><div class="lr-tip__row"><i style="background:' + cvar(col(v)) + '"></i><span>SRF 사용액</span><b>' + money(v) + '</b></div><div class="lr-tip__row"><span>구간</span><b>' + lab + "</b></div>" + (ov ? ov.row(ov.at(T[i])) : "");
      tip.hidden = false; var tw = tip.offsetWidth; tip.style.left = (x + 12 + tw > W ? x - 12 - tw : x + 12) + "px"; tip.style.top = m.t + "px";
    }
    hit.addEventListener("mousemove", function (e) { var r = svg.getBoundingClientRect(), px = e.clientX - r.left, t = T[0] + (px - m.l) / (W - m.l - m.r) * (T[n - 1] - T[0]), b = 0, bd = Infinity; for (var i = 0; i < n; i++) { var dd = Math.abs(T[i] - t); if (dd < bd) { bd = dd; b = i; } } show(b); });
    hit.addEventListener("mouseleave", function () { cross.setAttribute("visibility", "hidden"); if (ov) ov.hide(); tip.hidden = true; });
    root.innerHTML = ""; var wrap = h("div", "lr-chart__plot"); wrap.appendChild(svg); wrap.appendChild(tip); root.appendChild(wrap);
    if (spec.demoAt) { var k = D.indexOf(spec.demoAt); if (k >= 0) show(k); }
  }

  function render(root) { var s = root._lrSpec; if (!s || !root.offsetParent && root.clientWidth === 0) return; (s.kind === "bars" ? drawBars : drawXY)(root, s); }
  LR.chart = function (root, spec) { root._lrSpec = spec; root.classList.add("lr-chart"); if (LR.charts.indexOf(root) < 0) LR.charts.push(root); render(root); return root; };
  LR.renderAll = function () { LR.charts.forEach(render); };
  LR.setPeriod = function (p) { LR.period = p; LR.renderAll(); };
  LR.overlay = false;
  LR.setOverlay = function (on) { LR.overlay = !!on; LR.renderAll(); };
  /* toggle button [aria-pressed] → S&P 500 comparison strip on every chart that allows it */
  LR.overlayToggle = function (btn) {
    btn.addEventListener("click", function () { if (btn.getAttribute("aria-disabled") === "true") return; var on = btn.getAttribute("aria-pressed") !== "true"; btn.setAttribute("aria-pressed", on ? "true" : "false"); LR.setOverlay(on); });
  };
  LR.startIndex = startIndex;
  var rt; window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(LR.renderAll, 80); });

  /* chip groups: [data-lr-chips] with buttons [data-value]; calls onChange(value) */
  LR.chips = function (group, onChange) {
    group.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-value]"); if (!b) return;
      group.querySelectorAll("button[data-value]").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      onChange(b.getAttribute("data-value"));
    });
  };
  /* sub-tab panels: chips with data-value = panel id; panels [data-panel] */
  LR.subtabs = function (group, scope, onShow) {
    function showP(id) { scope.querySelectorAll("[data-panel]").forEach(function (p) { p.hidden = p.getAttribute("data-panel") !== id; }); LR.renderAll(); if (onShow) onShow(id); }
    LR.chips(group, showP);
    var cur = group.querySelector('[aria-pressed="true"]'); if (cur) showP(cur.getAttribute("data-value"));
  };
  LR.fmt = {
    tn: function (v) { return v.toFixed(v < 0.1 ? 3 : 2) + "조$"; },
    pct: function (v) { return v.toFixed(1) + "%"; },
    rate: function (v) { return v.toFixed(2) + "%"; },
    bp: function (v) { return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(0) + "bp"; },
    idx: function (v) { return v.toFixed(1); }
  };
  window.LiquidityRadar = LR;
})();
