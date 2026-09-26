/* Liquidity Radar — 페이지 로직.
 *
 * data/latest.json · data/history.json(update.py가 평일마다 생성)만 읽어서 index.html의
 * 시안 마크업을 채운다. 판정은 여기서 다시 하지 않는다 — 상태·압력 단계·요인 값은 전부
 * 파이프라인(assess.py)이 낸 것을 그대로 보여준다. 여기서 하는 계산은 표시용 파생값
 * (범위, 비율, 문장)뿐이다.
 */
(function () {
  "use strict";
  var LR = window.LiquidityRadar;
  var MINUS = "−";

  /* ---------- 포맷 ---------- */
  function signed(v, d) { return (v > 0 ? "+" : v < 0 ? MINUS : "") + Math.abs(v).toFixed(d); }
  function tn(v) { var a = Math.abs(v); return (v < 0 ? MINUS : "") + a.toFixed(a >= 10 ? 1 : a < 0.01 ? 3 : 2); }
  function delta(v) { return signed(v, Math.abs(v) < 0.001 ? 4 : 3); }
  function money(usd) {
    if (usd == null) return "확인 불가";
    if (usd === 0) return "$0";
    return usd >= 1e9 ? "$" + (usd / 1e9).toFixed(1) + "B" : "$" + Math.round(usd / 1e6) + "M";
  }
  var WD = ["일", "월", "화", "수", "목", "금", "토"];
  function ymd(d) { return d.toISOString().slice(0, 10); }
  function utc(s) { return new Date(s + "T00:00:00Z"); }
  function withWeekday(s) { return s + " (" + WD[utc(s).getUTCDay()] + ")"; }
  function md(s) { return s.slice(5); }
  function kst(iso) {
    var d = new Date(Date.parse(iso) + 9 * 3600e3);
    return d.toISOString().slice(0, 16).replace("T", " ") + " KST 자동 갱신";
  }
  function range(arr, fmt) {
    var v = arr.filter(function (x) { return x != null; });
    return fmt(Math.min.apply(null, v)) + "~" + fmt(Math.max.apply(null, v));
  }
  function median(arr) {
    var v = arr.filter(function (x) { return x != null; }).sort(function (a, b) { return a - b; });
    var m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  }
  // 차트 엔진은 null을 못 그린다. history는 파이프라인에서 이미 ffill돼 있지만
  // 시리즈 시작 전 구간이 비어 있을 수 있어 앞은 첫 값으로, 중간은 직전 값으로 채운다.
  function filled(arr) {
    var first = null; for (var i = 0; i < arr.length; i++) if (arr[i] != null) { first = arr[i]; break; }
    var prev = first; return arr.map(function (x) { if (x != null) prev = x; return prev; });
  }

  /* ---------- DOM ---------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function fill(key, text) { $$('[data-f="' + key + '"]').forEach(function (n) { n.textContent = text; }); }

  /* ---------- 상태 배지 (색 + 아이콘 + 글자) ---------- */
  var STATUS = {
    healthy: { cls: "good", label: "양호" }, neutral: { cls: "neutral", label: "중립" },
    watch: { cls: "caution", label: "주의" }, warning: { cls: "warning", label: "경고" },
    critical: { cls: "danger", label: "위험" }, unknown: { cls: "neutral", label: "판정 불가" }
  };
  var ICON = {
    good: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.8"/>',
    neutral: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    caution: '<path d="M12 3.5L21.5 20h-19z"/><path d="M12 10v4.5"/><circle cx="12" cy="17.2" r=".6" fill="currentColor"/>',
    warning: '<path d="M12 2.5l9.5 9.5-9.5 9.5L2.5 12z"/><path d="M12 8v5"/><circle cx="12" cy="15.8" r=".6" fill="currentColor"/>',
    danger: '<path d="M8.3 3h7.4L21 8.3v7.4L15.7 21H8.3L3 15.7V8.3z"/><path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6"/>'
  };
  function paintBadge(node, status, large) {
    var s = STATUS[status] || STATUS.unknown;
    node.className = "lr-badge lr-badge--" + s.cls + (large ? " lr-badge--lg" : "");
    node.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICON[s.cls] + "</svg>";
    node.appendChild(document.createTextNode(s.label));
  }

  /* ---------- 헤드라인 문장 ---------- */
  var DIR = { up: "늘어남", flat: "보합", down: "줄어듦" };
  function reasonText(r) {
    var m;
    if ((m = /^sofr_zscore_([+-][\d.]+)$/.exec(r))) return "스프레드 Z-score " + signed(+m[1], 1);
    if ((m = /^sofr_spread_over_(\d+)bp$/.exec(r))) return "SOFR−IORB +" + m[1] + "bp 돌파";
    if ((m = /^sofr_spread_([+-]\d+)bp$/.exec(r))) return "SOFR−IORB " + signed(+m[1], 0) + "bp";
    if ((m = /^sofr_persistent_(\d+)of(\d+)d$/.exec(r))) return m[2] + "일 중 " + m[1] + "일 +5bp 이상";
    if ((m = /^srf_([\d.]+)B(_critical)?$/.exec(r))) return "SRF $" + m[1] + "B";
    return null;
  }
  function headline(A, P) {
    var lv = P.level, dir = A.quantity_direction, chg = A.net_liquidity_30d_change_trillions;
    var amt = chg == null ? "" : Math.abs(chg).toFixed(3) + "조$";
    var seen = {}, why = (P.level_reasons || []).map(reasonText).filter(function (t) { if (!t || seen[t]) return false; return (seen[t] = true); });
    var whyTxt = why.length ? " (" + why.join(", ") + ")" : "";
    if (A.status === "unknown") return "유동성 수위 데이터를 확인하지 못해 판정하지 못했습니다";
    if (lv >= 3) return "자금시장에서 조달 실패 신호가 나왔습니다(L3)" + whyTxt;
    if (lv === 2) return "자금시장 압력이 이어지고 있습니다(L2)" + whyTxt;
    if (lv === 1) return dir === "down"
      ? "자금시장 압력 신호(L1)와 유동성 수위 감소(30일 " + MINUS + amt + ")가 겹쳤습니다" + whyTxt
      : "자금시장에 하루짜리 압력 신호가 켜졌습니다(L1)" + whyTxt;
    if (dir === "up") return "자금시장 압력은 없고(L0), 유동성 수위가 30일간 " + amt + " 늘었습니다";
    if (dir === "flat") return "자금시장 압력은 없고(L0), 유동성 수위도 30일간 큰 변화가 없습니다";
    return "자금시장 압력은 없지만(L0), 유동성 수위가 30일간 " + amt + " 줄었습니다";
  }

  /* ---------- 요인 분해 (지급준비금에 준 영향) ---------- */
  // 대차대조표 항등식: ΔWRESBAL = ΔWALCL − ΔTGA − ΔRRP − Δ유통화폐 − Δ기타 부채
  var FACTOR_NOUN = {
    walcl: ["연준 자산 확대", "연준 자산 축소"], tga: ["정부 금고에서 풀린 돈", "정부 금고로 빠져나간 돈"],
    rrp: ["역레포에서 나온 돈", "역레포로 들어간 돈"], cur: ["은행으로 돌아온 현금", "늘어난 현금 수요"]
  };
  function renderFactors(dc, reservesNow) {
    var box = $("#factors");
    var need = ["delta_walcl_trillions", "delta_wtregen_trillions", "delta_rrpontsyd_trillions", "delta_wcurcir_trillions", "delta_wresbal_trillions"];
    if (!dc || need.some(function (k) { return dc[k] == null; })) {
      box.innerHTML = '<p class="lr-caption">요인 분해에 필요한 값이 없어 이번에는 표시하지 않습니다.</p>'; return;
    }
    var dW = dc.delta_walcl_trillions, dT = dc.delta_wtregen_trillions, dR = dc.delta_rrpontsyd_trillions,
        dC = dc.delta_wcurcir_trillions, dRes = dc.delta_wresbal_trillions;
    var rows = [
      { key: "walcl", label: "연준 총자산", code: "WALCL" + (dc.delta_treast_trillions != null && dc.delta_wshomcb_trillions != null ? " · 국채 " + delta(dc.delta_treast_trillions) + " · MBS " + delta(dc.delta_wshomcb_trillions) : ""), color: "series-netliq", effect: dW, change: dW },
      { key: "tga", label: "정부 금고 TGA", code: "WTREGEN", color: "series-tga", effect: -dT, change: dT },
      { key: "rrp", label: "역레포 RRP", code: "RRPONTSYD", color: "series-rrp", effect: -dR, change: dR },
      { key: "cur", label: "유통화폐", code: "WCURCIR", color: "series-currency", effect: -dC, change: dC },
      { key: "other", label: "기타 (잔차)", code: "작은 부채·집계 시점 차이", color: "series-other", effect: dRes - (dW - dT - dR - dC), note: "계산값", mod: "residual" },
      { key: "res", label: "지급준비금 30일 변화", code: "잔액 " + tn(reservesNow) + "조$ 중", color: "series-reserves", effect: dRes, note: "변화량", mod: "result" }
    ];
    var scale = Math.max.apply(null, rows.map(function (r) { return Math.abs(r.effect); })) * 1.25 || 1;
    box.innerHTML = "";
    rows.forEach(function (r) {
      var w = (Math.abs(r.effect) / scale * 50).toFixed(2) + "%";
      var pos = r.effect >= 0 ? "left:50%" : "right:50%";
      var small = r.note || (delta(r.change) + " " + (r.change >= 0 ? "증가" : "감소"));
      var row = document.createElement("div");
      row.className = "lr-factor" + (r.mod ? " lr-factor--" + r.mod : "");
      row.innerHTML = '<div class="lr-factor__label"></div>' +
        '<div class="lr-factor__track" role="img" aria-label="' + r.label + " 지급준비금에 " + delta(r.effect) + '조$"><span class="lr-factor__bar" style="' + pos + ";width:" + w + ";background:var(--" + r.color + ')"></span></div>' +
        '<div class="lr-factor__val">' + delta(r.effect) + "<small>" + small + "</small></div>";
      var lab = row.firstChild; lab.textContent = r.label;
      var sm = document.createElement("small"); sm.textContent = r.code; lab.appendChild(sm);
      box.appendChild(row);
    });
    // 해석: 잔차를 뺀 요인 중 영향이 큰 두 개를 말한다
    var top = rows.slice(0, 4).filter(function (r) { return Math.abs(r.effect) >= 0.001; })
      .sort(function (a, b) { return Math.abs(b.effect) - Math.abs(a.effect); }).slice(0, 2);
    var head = "지급준비금이 30일간 " + Math.abs(dRes).toFixed(3) + "조$ " + (dRes >= 0 ? "늘었습니다." : "줄었습니다.");
    var body = top.length ? " 가장 크게 작용한 것은 " + top.map(function (r) {
      return FACTOR_NOUN[r.key][r.effect >= 0 ? 0 : 1] + "(" + delta(r.effect) + ")";
    }).join("과 ") + "입니다." : "";
    fill("factornote", head + body);
  }

  /* ---------- 데이터 발표주기 ---------- */
  function renderFreshness(L) {
    var s = L.series, asOf = L.as_of_date;
    function obs(id) { return s[id] ? s[id].observation_date : null; }
    function last(date, stale) {
      if (!date) return '<span class="lr-rel__last">확인 불가</span>';
      return '<span class="lr-rel__last">' + (stale ? '<span class="lr-dot lr-dot--stale"></span><span class="lr-fresh__stale">이전 값</span> ' : "최신 ") + "<b>" + md(date) + "</b></span>";
    }
    var daily = ["RRPONTSYD", "IORB", "SP500"].map(obs).filter(Boolean).sort();
    var dailyOld = daily[0];
    $("#fresh").innerHTML =
      '<div class="lr-rel__group"><span class="lr-rel__head">매일 <span class="lr-muted">(미국 영업일)</span></span>' +
      '<div class="lr-rel__row"><span>RRP · IORB · S&amp;P 500</span>' + last(dailyOld, dailyOld && dailyOld < asOf) + "</div>" +
      '<div class="lr-rel__row"><span>SOFR <small>다음 영업일 아침에 발표</small></span>' + last(obs("SOFR"), obs("SOFR") < asOf) + "</div></div>" +
      '<div class="lr-rel__group"><span class="lr-rel__head">매주</span>' +
      '<div class="lr-rel__row"><span><i class="lr-mk lr-mk--h41" aria-hidden="true"></i>WALCL · TGA · 지급준비금 <small>H.4.1 · 목요일 발표, 수요일 기준 값</small></span>' + last(obs("WALCL"), obs("WALCL") < asOf) + "</div>" +
      '<div class="lr-rel__row"><span><i class="lr-mk lr-mk--h8" aria-hidden="true"></i>은행 총자산 <small>H.8 · 금요일 발표, 9일 전 수요일 기준 값</small></span>' + last(obs("TLAACBW027SBOG"), obs("TLAACBW027SBOG") < asOf) + "</div></div>";
  }

  // 연준 휴일. 토요일 휴일은 연준이 금요일에 쉬지 않고, 일요일 휴일만 월요일로 옮긴다.
  function fedHolidays(y) {
    var out = {};
    function add(d, name) { if (d.getUTCDay() === 0) d = new Date(d.getTime() + 864e5); if (d.getUTCDay() !== 6) out[ymd(d)] = name; }
    function nth(m, wd, n) { var d = new Date(Date.UTC(y, m, 1)); d.setUTCDate(1 + (wd - d.getUTCDay() + 7) % 7 + (n - 1) * 7); return d; }
    function lastWd(m, wd) { var d = new Date(Date.UTC(y, m + 1, 0)); d.setUTCDate(d.getUTCDate() - (d.getUTCDay() - wd + 7) % 7); return d; }
    add(new Date(Date.UTC(y, 0, 1)), "신정"); add(nth(0, 1, 3), "마틴 루서 킹 데이"); add(nth(1, 1, 3), "대통령의 날");
    add(lastWd(4, 1), "메모리얼 데이"); add(new Date(Date.UTC(y, 5, 19)), "준틴스"); add(new Date(Date.UTC(y, 6, 4)), "독립기념일");
    add(nth(8, 1, 1), "노동절"); add(nth(9, 1, 2), "콜럼버스 데이"); add(new Date(Date.UTC(y, 10, 11)), "재향군인의 날");
    add(nth(10, 4, 4), "추수감사절"); add(new Date(Date.UTC(y, 11, 25)), "크리스마스");
    return out;
  }
  function releaseOf(d, hol) { // H.4.1 목요일, H.8 금요일. 휴일이면 표시하지 않는다(실제 발표일은 옮겨짐)
    if (hol[ymd(d)]) return null;
    return d.getUTCDay() === 4 ? "h41" : d.getUTCDay() === 5 ? "h8" : null;
  }
  function renderCalendar(asOf) {
    var a = utc(asOf), y = a.getUTCFullYear(), m = a.getUTCMonth();
    var hol = Object.assign(fedHolidays(y), fedHolidays(y + 1));
    var first = new Date(Date.UTC(y, m, 1)), days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    var html = WD.map(function (w) { return '<span class="lr-cal__w">' + w + "</span>"; }).join("");
    for (var i = 0; i < first.getUTCDay(); i++) html += '<span class="lr-cal__d is-out"></span>';
    var notes = [];
    for (var dd = 1; dd <= days; dd++) {
      var d = new Date(Date.UTC(y, m, dd)), key = ymd(d), wd = d.getUTCDay(), rel = releaseOf(d, hol);
      var cls = ["lr-cal__d"], label = (m + 1) + "월 " + dd + "일";
      if (wd === 0 || wd === 6) cls.push("is-weekend");
      if (hol[key]) { cls.push("is-holiday"); label += " " + hol[key] + " 휴장"; notes.push(dd + "일은 " + hol[key] + " 휴장"); }
      if (rel) label += rel === "h41" ? " H.4.1 발표" : " H.8 발표";
      if (key === asOf) { cls.push("is-today"); label += " 기준일"; }
      html += '<span class="' + cls.join(" ") + '" aria-label="' + label + '"><b>' + dd + "</b>" + (rel ? '<i class="lr-mk lr-mk--' + rel + '" aria-hidden="true"></i>' : "") + "</span>";
    }
    var tail = (first.getUTCDay() + days) % 7; for (i = 0; tail && i < 7 - tail; i++) html += '<span class="lr-cal__d is-out"></span>';
    var cal = $("#cal");
    cal.setAttribute("aria-label", y + "년 " + (m + 1) + "월 주간 지표 발표일");
    cal.innerHTML = '<div class="lr-cal__top"><b>' + y + "년 " + (m + 1) + '월</b><span class="lr-legend"><span><i class="lr-mk lr-mk--h41"></i>H.4.1</span><span><i class="lr-mk lr-mk--h8"></i>H.8</span><span><i class="lr-cal__todaykey"></i>기준일</span></span></div><div class="lr-cal__grid">' + html + "</div>";
    // 다음 발표일
    var next = {};
    for (var k = 1; k <= 21 && !(next.h41 && next.h8); k++) {
      var n = new Date(a.getTime() + k * 864e5), r = releaseOf(n, hol);
      if (r && !next[r]) next[r] = ymd(n);
    }
    var out = $('[data-f="nextrel"]');
    function mdw(s) { return md(s) + " (" + WD[utc(s).getUTCDay()] + ")"; }
    out.innerHTML = "다음 발표 " + (next.h41 ? '<b class="lr-ink">' + mdw(next.h41) + " H.4.1</b>" : "") +
      (next.h8 ? ' · <b class="lr-ink">' + mdw(next.h8) + " H.8</b>" : "") +
      ". 미국 동부 오후 발표라 한국 시간으로는 다음 날 새벽에 반영됩니다. 휴일이 낀 주는 발표일이 옮겨집니다." +
      (notes.length ? " " + notes.join(", ") + "." : "");
  }

  /* ---------- 압력 단계 타임라인 ---------- */
  var LV_NAME = ["L0 정상", "L1 주의", "L2 경계", "L3 심각"];
  function renderTimeline(dates, levels, nowLevel) {
    var box = $("#tl"), tip = $("#tl-tip"), NS = "http://www.w3.org/2000/svg";
    function el(n, a) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); return e; }
    var T = dates.map(function (s) { return utc(s).getTime(); }), S = T[0], E = T[T.length - 1], span = Math.max(1, E - S);
    var l3 = [], l0 = 0, known = 0;
    levels.forEach(function (v, i) { if (v == null) return; known++; if (v === 0) l0++; if (v === 3) l3.push(dates[i]); });
    function draw() {
      var W = box.clientWidth; if (!W) return;
      var H = 96, top = 8, base = 64, old = box.querySelector("svg"); if (old) old.remove();
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "최근 3년 압력 단계. L0가 " + Math.round(l0 / Math.max(1, known) * 100) + "%, L3는 " + l3.length + "일." });
      var X = function (t) { return (t - S) / span * W; };
      for (var y = utc(dates[0]).getUTCFullYear() + 1; y <= utc(dates[dates.length - 1]).getUTCFullYear(); y++) {
        var x = X(Date.UTC(y, 0, 1));
        svg.appendChild(el("line", { class: "t-grid", x1: x, x2: x, y1: top, y2: base + 6 }));
        var t = el("text", { class: "t-tick", x: x + 4, y: base + 22 }); t.textContent = String(y); svg.appendChild(t);
      }
      svg.appendChild(el("rect", { class: "t-base", x: 0, y: base - 4, width: W, height: 4 }));
      var hs = [0, 18, 34, 52];
      levels.forEach(function (v, i) { if (v > 0) svg.appendChild(el("rect", { class: "t-l" + v, x: X(T[i]) - 2, y: base - 4 - hs[v], width: 4, height: hs[v] })); });
      svg.appendChild(el("rect", { class: "t-now", x: W - 2, y: base - 10, width: 2, height: 14 }));
      var nt = el("text", { class: "t-now", x: W - 1, y: base + 22, "text-anchor": "end" }); nt.textContent = "지금 " + (nowLevel == null ? "판정 불가" : "L" + nowLevel); svg.appendChild(nt);
      var cross = el("line", { class: "t-cross", x1: 0, x2: 0, y1: top, y2: base + 4, visibility: "hidden" }); svg.appendChild(cross);
      box.insertBefore(svg, tip);
      function show(px) {
        var t = S + px / W * span, best = 0, bd = Infinity;
        for (var i = 0; i < T.length; i++) { var dd = Math.abs(T[i] - t); if (dd < bd) { bd = dd; best = i; } }
        // 가까운 경보일(4일 이내)이 있으면 그 날에 붙는다. 3년 폭에서 1px ≈ 1일이라 가는 막대를 잡기 어렵다.
        for (var j = 0; j < T.length; j++) if (levels[j] > 0 && Math.abs(T[j] - t) < 4 * 864e5 && (levels[best] === 0 || levels[j] > levels[best])) best = j;
        var x = X(T[best]), lv = levels[best];
        cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
        tip.hidden = false; tip.style.left = (x > W - 200 ? x - 188 : x + 10) + "px"; tip.style.top = top + "px";
        tip.innerHTML = "<b>" + dates[best] + "</b>압력 " + (lv == null ? "판정 불가" : LV_NAME[lv]);
      }
      svg.addEventListener("mousemove", function (ev) { var r = svg.getBoundingClientRect(); show(ev.clientX - r.left); });
      svg.addEventListener("mouseleave", function () { cross.setAttribute("visibility", "hidden"); tip.hidden = true; });
    }
    draw();
    var rt; window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(draw, 80); });
    fill("tlnote", "최근 3년 중 " + Math.round(l0 / Math.max(1, known) * 100) + "%의 날은 L0입니다. 압력은 분기말·월말 부근에 짧게 튑니다. " +
      (l3.length ? "L3까지 오른 날은 " + l3.length + "일이며, 가장 최근은 " + l3[l3.length - 1] + "입니다." : "L3까지 오른 날은 없었습니다."));
    return draw;
  }

  /* ---------- 채우기 ---------- */
  function build(L, H) {
    var S = H.series, Dv = H.derived, dates = H.dates, A = L.assessment, P = L.pressure;
    function now(id) { return L.series[id] ? L.series[id].normalized_value : null; }

    // 차트용 배열 (시안의 LR.demo.weekly / daily 모양)
    var W = {
      dates: dates, netliq: filled(Dv.net_liquidity_trillions), reserves: filled(S.WRESBAL), tga: filled(S.WTREGEN),
      rrp: filled(S.RRPONTSYD), currency: filled(S.WCURCIR), walcl: filled(S.WALCL), spx: filled(S.SP500)
    };
    W.other = W.walcl.map(function (w, i) { return w - W.reserves[i] - W.currency[i] - W.tga[i] - W.rrp[i]; });
    var bank = filled(S.TLAACBW027SBOG);
    W.ratio = W.reserves.map(function (r, i) { return r / bank[i] * 100; });
    var Dd = {
      dates: dates, iorb: filled(S.IORB), sofr: filled(S.SOFR), spread: filled(Dv.sofr_minus_iorb_bp),
      srf: Dv.srf_usd ? Dv.srf_usd.map(function (v) { return v / 1e9; }) : null, level: Dv.pressure_level || []
    };
    LR.spx = { dates: dates, values: W.spx };

    // 헤더
    fill("asof", withWeekday(L.as_of_date));
    fill("updated", kst(L.generated_at));

    // 상태
    paintBadge($("[data-status-badge]"), A.status, true);
    fill("headline", headline(A, P));
    $$("[data-scale]").forEach(function (n) { if (n.getAttribute("data-scale") === A.status) n.setAttribute("aria-current", "true"); else n.removeAttribute("aria-current"); });
    if (!P.level_data_complete) {
      var inc = $('[data-f="incomplete"]'); inc.hidden = false;
      inc.textContent = "압력 지표 일부를 확인하지 못했습니다. 낮은 단계를 ‘압력 없음’으로 읽지 마세요.";
    }

    // 값
    var v = {
      walcl: now("WALCL"), tga: now("WTREGEN"), rrp: now("RRPONTSYD"), res: now("WRESBAL"), cur: now("WCURCIR"),
      bank: now("TLAACBW027SBOG"), nl: L.derived.net_liquidity_trillions
    };
    v.other = v.walcl - v.res - v.cur - v.tga - v.rrp;
    ["walcl", "tga", "rrp", "res", "cur", "bank", "nl", "other"].forEach(function (k) { if (v[k] != null) fill(k, tn(v[k])); });
    fill("ratio", (v.res / v.bank * 100).toFixed(1) + "%");
    fill("wrong", tn(v.res - v.tga - v.rrp));
    var chg = A.net_liquidity_30d_change_trillions;
    fill("nlchg", chg == null ? "확인 불가" : Math.abs(chg) < 0.0005 ? "변화 없음" : (chg > 0 ? "▲ " : "▼ ") + Math.abs(chg).toFixed(3) + "조");
    var sp = P.spreads_bp ? P.spreads_bp.sofr_minus_iorb : null;
    fill("spread", sp == null ? "–" : signed(sp, 0));
    var z = P.zscore && P.zscore.sofr_minus_iorb ? P.zscore.sofr_minus_iorb["6M"] : null;
    fill("z6m", z == null ? "계산 불가" : signed(z, 2));
    var srf = P.srf_usage;
    fill("srf", money(srf ? srf.total_accepted_usd : null));
    fill("srfdate", srf ? "· " + md(srf.operation_date) + " 기준" : "· 조회 실패");

    // 수위 탭 해설 숫자
    var t2 = function (x) { return x.toFixed(2); };
    fill("nlrange", range(W.netliq, t2) + "조$");
    var lo = Math.min.apply(null, W.netliq), hi = Math.max.apply(null, W.netliq), p = (v.nl - lo) / Math.max(1e-9, hi - lo);
    fill("nlpos", p < 1 / 3 ? "범위의 아래쪽" : p < 2 / 3 ? "범위의 가운데쯤" : "범위의 위쪽");
    fill("currange", range(W.currency, t2) + "조$");
    fill("tgarange", range(W.tga, t2) + "조$");
    fill("rrp0", tn(W.rrp[0])); fill("walcl0", tn(W.walcl[0]));
    fill("rrpverb", v.rrp < W.rrp[0] * 0.05 ? "로 사실상 사라졌습니다" : v.rrp < W.rrp[0] ? "로 줄었습니다" : "로 늘었습니다");
    var i6 = LR.startIndex(dates, "6m"), n = dates.length - 1;
    var inl = W.netliq[n] / W.netliq[i6] * 100, isp = W.spx[n] / W.spx[i6] * 100, gap = isp - inl;
    fill("idxnl", inl.toFixed(1)); fill("idxspx", isp.toFixed(1));
    fill("idxsay", gap > 5 ? "주가가 유동성보다 훨씬 앞서 있습니다." : gap > 1 ? "주가가 유동성보다 조금 앞서 있습니다." : gap < -5 ? "유동성이 주가보다 훨씬 앞서 있습니다." : gap < -1 ? "유동성이 주가보다 조금 앞서 있습니다." : "둘이 비슷하게 움직였습니다.");

    // 압력 탭 해설 숫자
    fill("iorb", now("IORB") == null ? "–" : now("IORB").toFixed(2) + "%");
    fill("sofr", now("SOFR") == null ? "–" : now("SOFR").toFixed(2) + "%");
    fill("sprange", range(Dd.spread, function (x) { return signed(x, 0); }) + "bp");
    fill("spmed", signed(median(Dd.spread), 0) + "bp");
    if (Dd.srf) {
      var big = 0, mx = 0, mxd = null;
      Dd.srf.forEach(function (x, i) { if (x >= 1) big++; if (x > mx) { mx = x; mxd = dates[i]; } });
      fill("srfsay", big ? "3년간 $1B를 넘은 날은 " + big + "일, 최대는 $" + mx.toFixed(1) + "B(" + mxd + ")였습니다." : "3년간 $1B를 넘은 날은 없었습니다.");
    } else {
      fill("srfsay", "이번에는 SRF 이력을 불러오지 못했습니다.");
      $('[data-f="srfmissing"]').hidden = false;
    }

    // 종합 판정
    var lv = P.level, dir = A.quantity_direction;
    $$("[data-badge]").forEach(function (n) { paintBadge(n, n.getAttribute("data-badge"), false); });
    var cell = $('[data-cell="' + lv + "-" + dir + '"]');
    if (cell) { cell.classList.add("is-now"); cell.setAttribute("aria-current", "true"); }
    var step = $('[data-step="' + lv + '"]');
    if (step) { step.classList.add("is-now"); step.setAttribute("aria-current", "true"); step.lastElementChild.className = "lr-here"; step.lastElementChild.textContent = "지금 여기"; }
    fill("verdictnow", "지금: 압력 L" + lv + " · 수위 " + (DIR[dir] || "확인 불가") + " → " + (STATUS[A.status] || STATUS.unknown).label);

    // 요약 탭의 나머지
    renderFactors(A.decomposition, v.res);
    renderFreshness(L);
    renderCalendar(L.as_of_date);
    var redrawTimeline = renderTimeline(dates, Dd.level, lv);

    // 차트 — 시안의 spec 그대로, demoAt(툴팁 고정)만 뺐다
    var F = LR.fmt;
    var wrong = W.reserves.map(function (r, i) { return r - W.tga[i] - W.rrp[i]; });
    var specs = {
      nl: { dates: dates, series: [{ label: "Net Liquidity", color: "series-netliq", values: W.netliq }], fmt: F.tn, aria: "Net Liquidity 추이" },
      res: { dates: dates, series: [{ label: "Net Liquidity", color: "series-netliq", values: W.netliq }, { label: "지급준비금", color: "series-reserves", values: W.reserves }], fmt: F.tn, aria: "Net Liquidity와 지급준비금" },
      "m-nl": { dates: dates, mini: true, series: [{ label: "Net Liquidity", color: "series-netliq", values: W.netliq }], fmt: F.tn },
      "m-res": { dates: dates, mini: true, series: [{ label: "지급준비금", color: "series-reserves", values: W.reserves }], fmt: F.tn },
      "m-tga": { dates: dates, mini: true, series: [{ label: "TGA", color: "series-tga", values: W.tga }], fmt: F.tn },
      "m-rrp": { dates: dates, mini: true, includeZero: true, series: [{ label: "RRP", color: "series-rrp", values: W.rrp }], fmt: F.tn },
      stack: { dates: dates, stacked: true, series: [{ label: "지급준비금", color: "series-reserves", values: W.reserves }, { label: "유통화폐", color: "series-currency", values: W.currency }, { label: "TGA", color: "series-tga", values: W.tga }, { label: "RRP", color: "series-rrp", values: W.rrp }, { label: "기타", color: "series-other", values: W.other }], fmt: F.tn, aria: "연준 부채 구성 누적" },
      ratio: { dates: dates, series: [{ label: "지급준비금 ÷ 은행 총자산", short: "비율", color: "series-reserves", values: W.ratio }], fmt: F.pct },
      spx: { dates: dates, index100: true, overlay: false, series: [{ label: "Net Liquidity", color: "series-netliq", values: W.netliq }, { label: "S&P 500", color: "series-spx", values: W.spx }], fmt: F.idx, aria: "시작일=100 지수" },
      wrong: { dates: dates, series: [{ label: "Net Liquidity (올바름)", short: "Net Liquidity", color: "series-netliq", values: W.netliq }, { label: "지급준비금 (올바름)", short: "지급준비금", color: "series-reserves", values: W.reserves }, { label: "지급준비금 − TGA − RRP (틀림)", short: "틀린 계산", color: "series-other", dash: true, values: wrong }], fmt: F.tn },
      rates: { dates: dates, series: [{ label: "IORB (기준)", short: "IORB", color: "series-iorb", values: Dd.iorb }, { label: "SOFR (시장)", short: "SOFR", color: "series-sofr", values: Dd.sofr }], fmt: F.rate, aria: "IORB와 SOFR" },
      spread: { dates: dates, includeZero: true, series: [{ label: "SOFR − IORB", color: "series-sofr", values: Dd.spread }], fmt: F.bp, endLabels: false,
        thresholds: [{ value: 5, label: "+5 L1", color: "pressure-1" }, { value: 15, label: "+15 L2", color: "pressure-2" }, { value: 30, label: "+30 L3", color: "pressure-3" }] },
      srf: Dd.srf ? { kind: "bars", dates: dates, values: Dd.srf, aria: "SRF 사용액 로그 막대" } : null
    };
    $$("[data-chart]").forEach(function (node) { var s = specs[node.getAttribute("data-chart")]; if (s) LR.chart(node, s); });
    return redrawTimeline;
  }

  /* ---------- 탭 · 칩 · 토글 ---------- */
  var TABS = ["summary", "level", "pressure", "learn"];
  function wire(redrawTimeline) {
    function show(name, focus) {
      TABS.forEach(function (t) {
        var on = t === name;
        $("#panel-" + t).hidden = !on;
        var b = $("#tab-" + t); b.setAttribute("aria-selected", on ? "true" : "false"); b.tabIndex = on ? 0 : -1;
        if (on && focus) b.focus();
      });
      LR.renderAll();
      if (name === "summary" && redrawTimeline) redrawTimeline();
    }
    function fromHash() {
      var h = location.hash.slice(1);
      if (TABS.indexOf(h) >= 0) return h;
      var target = h && document.getElementById(h);            // #floor 같은 본문 앵커
      var panel = target && target.closest("[data-tabpanel]");
      return panel ? panel.getAttribute("data-tabpanel") : "summary";
    }
    $$(".lr-tab").forEach(function (b) {
      b.addEventListener("click", function () { var t = b.getAttribute("data-tab"); if (location.hash !== "#" + t) history.replaceState(null, "", "#" + t); show(t); });
      b.addEventListener("keydown", function (e) {
        var i = TABS.indexOf(b.getAttribute("data-tab"));
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          var t = TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
          history.replaceState(null, "", "#" + t); show(t, true); e.preventDefault();
        }
      });
    });
    window.addEventListener("hashchange", function () { show(fromHash()); });

    // 기간 칩과 S&P 비교 토글은 수위·압력 탭에 하나씩 있다. 한쪽을 바꾸면 양쪽이 같이 바뀐다.
    var periodGroups = $$("[data-lr-period]");
    periodGroups.forEach(function (g) {
      LR.chips(g, function (p) {
        periodGroups.forEach(function (o) { $$("button[data-value]", o).forEach(function (x) { x.setAttribute("aria-pressed", x.getAttribute("data-value") === p ? "true" : "false"); }); });
        LR.setPeriod(p);
      });
    });
    var overlayBtns = $$("[data-lr-overlay]");
    overlayBtns.forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (btn.getAttribute("aria-disabled") === "true") return;
        var on = !LR.overlay;
        overlayBtns.forEach(function (o) { o.setAttribute("aria-pressed", on ? "true" : "false"); });
        LR.setOverlay(on);
      });
    });

    var level = $("#panel-level"), pressure = $("#panel-pressure");
    var lvBtn = $("[data-lr-overlay]", level);
    LR.subtabs($("[data-lr-sub]", level), level, function (id) {
      var off = id === "four" || id === "spx";
      lvBtn.setAttribute("aria-disabled", off ? "true" : "false");
      lvBtn.title = off ? (id === "spx" ? "이 차트에는 이미 S&P 500이 있습니다" : "작은 차트 네 개에는 붙이지 않습니다") : "차트 아래에 S&P 500을 같은 기간으로 붙여 봅니다";
    });
    var pw = $("[data-lr-periodwrap]", pressure);
    LR.subtabs($("[data-lr-sub]", pressure), pressure, function (id) { pw.style.visibility = id === "verdict" ? "hidden" : "visible"; });

    show(fromHash());
    // #zscore 같은 본문 앵커로 들어오면, 첫 로드 때는 탭이 숨겨져 있어 브라우저가 스크롤하지 못한다
    var anchor = location.hash.length > 1 && TABS.indexOf(location.hash.slice(1)) < 0 && document.getElementById(location.hash.slice(1));
    if (anchor) anchor.scrollIntoView();
  }

  /* ---------- 시작 ---------- */
  function getJSON(url) {
    return fetch(url, { cache: "no-cache" }).then(function (r) {
      if (!r.ok) throw new Error(url + " — HTTP " + r.status);
      return r.json();
    });
  }
  Promise.all([getJSON("data/latest.json"), getJSON("data/history.json")])
    .then(function (res) { wire(build(res[0], res[1])); })
    .catch(function (err) {
      $("#loadfail").hidden = false;
      fill("loaderror", String(err && err.message || err));
      wire(null);
      if (window.console) console.error(err);
    });
})();
