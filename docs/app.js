"use strict";

const app = document.getElementById("app");
const meta = document.getElementById("meta");
const SVG_NS = "http://www.w3.org/2000/svg";

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

const rm = (n) => (n === null || n === undefined ? "-" : "RM " + Math.round(n).toLocaleString("en-MY"));
const signed = (n) => (n > 0 ? "+" : n < 0 ? "-" : "") + Math.abs(Math.round(n));
const niceDate = (iso) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-GB", {
    weekday: "short", day: "numeric", month: "short", year: "numeric",
  });
const shortDate = (iso) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });

function lineChart(series, low) {
  const W = 340, H = 130, L = 40, R = 10, T = 10, B = 22;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "chart");
  svg.setAttribute("role", "img");
  const prices = series.map((s) => s[1]);
  let lo = Math.min(...prices), hi = Math.max(...prices);
  if (hi === lo) { lo -= 10; hi += 10; }
  const pad = (hi - lo) * 0.15;
  lo -= pad; hi += pad;
  const x = (i) => L + (series.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (series.length - 1));
  const y = (p) => T + ((hi - p) * (H - T - B)) / (hi - lo);
  const add = (tag, attrs, text) => {
    const n = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    svg.append(n);
    return n;
  };
  add("line", { class: "axis", x1: L, y1: H - B, x2: W - R, y2: H - B });
  add("text", { x: L - 6, y: y(hi - pad) + 3, "text-anchor": "end" }, Math.round(hi - pad));
  add("text", { x: L - 6, y: y(lo + pad) + 3, "text-anchor": "end" }, Math.round(lo + pad));
  if (low !== null && series.length > 1) {
    add("line", { class: "lowline", x1: L, y1: y(low), x2: W - R, y2: y(low) });
  }
  add("polyline", { class: "line", points: series.map((s, i) => `${x(i)},${y(s[1])}`).join(" ") });
  series.forEach((s, i) => {
    if (series.length <= 40 || i === series.length - 1) add("circle", { class: "dot", cx: x(i), cy: y(s[1]), r: 2.5 });
  });
  add("text", { x: L, y: H - 6 }, shortDate(series[0][0]));
  add("text", { x: W - R, y: H - 6, "text-anchor": "end" }, shortDate(series[series.length - 1][0]));
  svg.setAttribute("aria-label", `Price over time: from ${rm(series[0][1])} to ${rm(series[series.length - 1][1])}`);
  return svg;
}

function changeNote(it) {
  if (it.change_vs_prev === null) return null;
  const c = it.change_vs_prev;
  const cls = c > 0 ? "up" : c < 0 ? "down" : "flat";
  const txt = c === 0 ? "no change since last check" : `${signed(c)} since last check`;
  return el("small", { class: cls }, txt);
}

function card(it) {
  const sigClass = "sig-" + it.signal.toLowerCase().replace(/\s+/g, "-");
  const c = el("article", { class: "card" });
  c.append(
    el("div", { class: "top" }, el("h2", {}, it.label), el("span", { class: "pill " + sigClass }, it.signal)),
    el("p", { class: "sub" }, `${niceDate(it.travel_date)} · ${it.days_to_departure} days to go`)
  );
  if (!it.latest) {
    c.append(el("p", { class: "muted" }, it.reasons[0]));
    return c;
  }
  c.append(el("p", { class: "price" }, rm(it.latest.price), changeNote(it)));
  c.append(el("p", { class: "muted" },
    `${it.latest.airline} ${it.latest.flight_no} · departs ${it.latest.dep_time || "?"}`));
  c.append(lineChart(it.series, it.checks > 1 ? it.low : null));
  c.append(el("div", { class: "facts" },
    el("div", {}, el("span", {}, "Lowest seen"), rm(it.low)),
    el("div", {}, el("span", {}, "Highest seen"), rm(it.high)),
    el("div", {}, el("span", {}, "Since first check"), it.change_vs_first === null ? "-" : signed(it.change_vs_first)),
    el("div", {}, el("span", {}, "Checks"), it.checks)));
  const ul = el("ul", { class: "reasons" }, it.reasons.map((r) => el("li", {}, r)));
  if (it.forecast.expected_7d !== null) {
    ul.append(el("li", {}, `Rough 7-day projection: ${rm(it.forecast.expected_7d)} (${it.forecast.confidence} confidence).`));
  }
  c.append(ul);
  if (it.offers.length) {
    const t = el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "Airline"), el("th", {}, "Flight"), el("th", {}, "Departs"), el("th", { class: "num" }, "Price"))),
      el("tbody", {}, it.offers.map((o) => el("tr", {},
        el("td", {}, o.airline), el("td", {}, o.flight_no), el("td", {}, o.dep_time), el("td", { class: "num" }, rm(o.price))))));
    c.append(el("details", {}, el("summary", {}, `Today's flights (${it.offers.length})`), t));
  }
  return c;
}

function movementTable(items) {
  const rows = items.filter((it) => it.checks > 1).map((it) => el("tr", {},
    el("td", {}, `${it.label} (${shortDate(it.travel_date)})`),
    el("td", { class: "num" }, it.checks),
    el("td", { class: "num" }, it.stats.rises),
    el("td", { class: "num" }, it.stats.drops),
    el("td", { class: "num" }, it.stats.avg_rise === null ? "-" : rm(it.stats.avg_rise)),
    el("td", { class: "num" }, it.stats.avg_drop === null ? "-" : rm(it.stats.avg_drop)),
    el("td", { class: "num" }, it.stats.rise_share === null ? "-" : Math.round(it.stats.rise_share * 100) + "%")));
  if (!rows.length) return el("p", { class: "muted" }, "Needs at least two daily checks per route to show how prices move.");
  return el("div", { class: "panel" }, el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "Route"), el("th", { class: "num" }, "Checks"), el("th", { class: "num" }, "Rises"),
      el("th", { class: "num" }, "Drops"), el("th", { class: "num" }, "Avg rise"),
      el("th", { class: "num" }, "Avg drop"), el("th", { class: "num" }, "Days rising"))),
    el("tbody", {}, rows)));
}

const weekday = (iso) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short" });
const isWeekend = (iso) => [0, 6].includes(new Date(iso + "T00:00:00").getDay());

// One bar per travel date: today's cheapest fare. The cheapest date is highlighted.
function dateChart(items) {
  const W = 720, H = 190, L = 44, R = 8, T = 12, B = 34;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "chart datechart");
  svg.setAttribute("role", "img");
  const priced = items.filter((it) => it.latest);
  const hi = Math.max(...priced.map((it) => it.latest.price)) * 1.08;
  const lo = Math.min(...priced.map((it) => it.latest.price));
  const best = priced.reduce((a, b) => (b.latest.price < a.latest.price ? b : a));
  const slot = (W - L - R) / items.length;
  const y = (p) => T + ((hi - p) * (H - T - B)) / hi;
  const add = (tag, attrs, text) => {
    const n = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    svg.append(n);
    return n;
  };
  add("line", { class: "axis", x1: L, y1: H - B, x2: W - R, y2: H - B });
  add("text", { x: L - 6, y: T + 8, "text-anchor": "end" }, Math.round(hi));
  add("text", { x: L - 6, y: H - B, "text-anchor": "end" }, "0");
  add("line", { class: "lowline", x1: L, y1: y(lo), x2: W - R, y2: y(lo) });
  items.forEach((it, i) => {
    const x = L + i * slot;
    if (isWeekend(it.travel_date)) add("rect", { class: "wknd", x, y: T, width: slot, height: H - T - B });
    if (it.latest) {
      const cls = "bar" + (it === best ? " best" : "");
      const bar = add("rect", { class: cls, x: x + slot * 0.15, y: y(it.latest.price),
        width: slot * 0.7, height: H - B - y(it.latest.price) });
      const tip = document.createElementNS(SVG_NS, "title");
      tip.textContent = `${niceDate(it.travel_date)}: ${rm(it.latest.price)} (${it.signal})`;
      bar.append(tip);
    }
    if (i % Math.ceil(items.length / 12) === 0) {
      add("text", { x: x + slot / 2, y: H - 18, "text-anchor": "middle" }, shortDate(it.travel_date));
      add("text", { x: x + slot / 2, y: H - 6, "text-anchor": "middle" }, weekday(it.travel_date));
    }
  });
  svg.setAttribute("aria-label", `Cheapest fare for each travel date; cheapest is ${niceDate(best.travel_date)} at ${rm(best.latest.price)}`);
  return svg;
}

function dateTable(items) {
  const rows = items.map((it) => {
    const sigClass = "sig-" + it.signal.toLowerCase().replace(/\s+/g, "-");
    const chg = it.change_vs_prev;
    return el("tr", {},
      el("td", {}, `${weekday(it.travel_date)} ${shortDate(it.travel_date)}`),
      el("td", { class: "num" }, it.latest ? rm(it.latest.price) : "-"),
      el("td", { class: "num " + (chg > 0 ? "up" : chg < 0 ? "down" : "flat") }, chg === null ? "-" : signed(chg)),
      el("td", { class: "num" }, it.latest ? rm(it.low) : "-"),
      el("td", { class: "num" }, it.latest ? it.latest.airline : "-"),
      el("td", {}, el("span", { class: "pill " + sigClass }, it.signal)));
  });
  return el("div", { class: "panel" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}, "Date"), el("th", { class: "num" }, "Cheapest now"),
      el("th", { class: "num" }, "Change"), el("th", { class: "num" }, "Lowest seen"),
      el("th", { class: "num" }, "Airline"), el("th", {}, "Signal"))),
    el("tbody", {}, rows)));
}

function routeSection(label, items) {
  items = items.slice().sort((a, b) => a.travel_date.localeCompare(b.travel_date));
  const priced = items.filter((it) => it.latest);
  const sec = el("section", { class: "route" }, el("h2", { class: "routehead" }, label));
  if (items.length <= 6) {  // a few dates: show full cards
    sec.append(el("div", { class: "grid" }, items.map(card)));
    return sec;
  }
  if (!priced.length) {
    sec.append(el("p", { class: "muted" }, `${items.length} dates watched. No prices yet; the first daily check will fill this in.`));
    return sec;
  }
  const cheapest = priced.slice().sort((a, b) => a.latest.price - b.latest.price);
  const top = cheapest[0];
  sec.append(el("p", { class: "muted" },
    `${items.length} dates watched, ${priced.length} with prices. Cheapest now: `,
    el("strong", {}, `${niceDate(top.travel_date)} at ${rm(top.latest.price)}`), ` (${top.signal}).`));
  sec.append(el("div", { class: "panel chartpanel" }, dateChart(items)));
  sec.append(el("h3", {}, "The cheapest dates in detail"));
  sec.append(el("div", { class: "grid" }, cheapest.slice(0, 3).map(card)));
  sec.append(el("details", { class: "alldates" }, el("summary", {}, `All ${items.length} dates`), dateTable(items)));
  return sec;
}

async function main() {
  let data;
  try {
    const res = await fetch("data/summary.json?" + Date.now());
    if (!res.ok) throw new Error(res.status);
    data = await res.json();
  } catch (e) {
    meta.textContent = "No data yet.";
    app.append(el("p", { class: "empty" }, "No price data has been recorded yet. Run the \"Daily price check\" workflow once from the Actions tab."));
    return;
  }
  meta.textContent = `Updated ${data.updated} · Source: Google Flights` +
    (data.searches_used ? ` · SerpApi backup searches this month: ${data.searches_used} of ${data.search_limit}` : "");
  if (!data.items.length) {
    app.append(el("p", { class: "empty" }, "Nothing to show. Add [[range]] entries with future dates in config.toml."));
    return;
  }
  const labels = [...new Set(data.items.map((it) => it.label))];
  labels.forEach((label) => app.append(routeSection(label, data.items.filter((it) => it.label === label))));
  const moves = movementTable(data.items);
  app.append(el("h3", {}, "How prices move between checks"),
    data.items.length > 12 ? el("details", {}, el("summary", {}, "Show the table"), moves) : moves);
}

main();
