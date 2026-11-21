/* HubFare dashboard – dependency-free SPA (ECharts for charts). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const eur = (n) => (n == null ? "—" : "€" + Math.round(n).toLocaleString("en-GB"));
const api = async (path, opts = {}) => {
  const r = await fetch("/api" + path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
};
const ago = (iso) => {
  if (!iso) return "never";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
};
const until = (iso) => {
  if (!iso) return "—";
  const m = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (m <= 0) return "due now";
  if (m < 60) return `in ${m} min`;
  return `in ${Math.round(m / 60)} h`;
};
const toast = (msg) => { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3200); };
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };

const I = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  flight: '<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>',
  package: '<rect x="5" y="7" width="14" height="14" rx="2"/><path d="M9 7V4.5A1.5 1.5 0 0 1 10.5 3h3A1.5 1.5 0 0 1 15 4.5V7M9 11v6M15 11v6"/>',
  cruise: '<path d="M2 21c.6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1 .6.5 1.2 1 2.5 1 2.5 0 2.5-2 5-2 1.3 0 1.9.5 2.5 1"/><path d="M19.4 19.5A11.6 11.6 0 0 0 21 14l-9-4-9 4c0 2 .5 3.8 1.5 5.5M19 13V7a2 2 0 0 0-2-2H7a2 2 0 0 0-2 2v6M12 10v4M12 2v3"/>',
  saved: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
  alerts: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  settings: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  ext: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9"/>',
  star: '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
  food: '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M7 2v20M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3zm0 0v7"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  bag: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4zM3 6h18M16 10a4 4 0 0 1-8 0"/>',
  trend: '<path d="m22 17-8.5-8.5-5 5L2 7"/><path d="M16 17h6v-6"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5"/>',
};
const ic = (n) => `<svg viewBox="0 0 24 24">${I[n] || ""}</svg>`;

const NAV = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "flights", label: "Flight Deals", icon: "flight", cat: "flight" },
  { id: "packages", label: "Holiday Packages", icon: "package", cat: "package" },
  { id: "cruises", label: "Cruises + Flights", icon: "cruise", cat: "cruise" },
  { sep: true },
  { id: "saved", label: "Saved Deals", icon: "saved" },
  { id: "alerts", label: "Alerts", icon: "alerts" },
  { id: "settings", label: "Settings", icon: "settings" },
];
const CAT_META = {
  flight: { label: "Flights", sub: "Error fares, long-haul & premium cabins", page: "flights", icon: "flight" },
  package: { label: "Holiday Packages", sub: "Flights + hotel from European operators", page: "packages", icon: "package" },
  cruise: { label: "Cruises + Flights", sub: "Judged on complete trip cost", page: "cruises", icon: "cruise" },
};
const state = { overview: null, counts: {}, filters: store.get("te-filters", {}), lastNotifId: store.get("te-last-notif", 0) };

/* ------------------------------------------------------------------ shell */
function renderNav(active) {
  $("#nav").innerHTML = NAV.map((n) => n.sep ? '<div class="sep"></div>' :
    `<a href="#/${n.id}" class="${n.id === active ? "active" : ""}">${ic(n.icon)}<span>${n.label}</span>${
      n.cat && state.counts[n.cat] != null ? `<span class="count">${state.counts[n.cat]}</span>` : ""}</a>`).join("");
}

function renderMonitoring(m, airports) {
  if (!m) return;
  const cls = m.state === "ok" ? "" : m.state === "degraded" ? "warn" : "off";
  const label = m.state === "off" || !m.worker_running ? "Paused" : "Live";
  $("#live-status").innerHTML = `<span class="pulse ${cls}"></span><span class="txt">${label}</span>`;
  $("#live-status").title = `Worker heartbeat: ${ago(m.worker_heartbeat)}\nLast successful scan: ${ago(m.last_scan)}\nNext scan: ${until(m.next_scan)}${
    m.sources_failing.length ? "\nFailing: " + m.sources_failing.join(", ") : ""}`;
  $("#sidebar-status").innerHTML = "";
  if (airports) {
    const a = airports.slice(0, 4).join(" · ");
    $("#pref-chip").innerHTML = `${ic("pin")}<span>From ${a}${airports.length > 4 ? ` +${airports.length - 4}` : ""}</span>`;
  }
}

/* ------------------------------------------------------------------ cards */
const scoreCls = (s) => (s >= 95 ? "s95" : s >= 85 ? "s85" : s >= 70 ? "s70" : "");
const scoreBadge = (s) => `<div class="score ${scoreCls(s)}" title="Deal Score">${s}</div>`;
const basisLabel = (d) => d.price_basis === "total" ? "total for 2" : d.price_basis === "per_night" ? "/night" : d.subtype === "flight" ? (d.trip_type === "one_way" ? "one-way" : "return") : "pp";
function tags(d) {
  const t = [];
  if (d.error_flag !== "none") t.push(`<span class="tag err">${ic("zap")}${d.error_flag === "suspected_source" ? "Error fare" : "Possible error"}</span>`);
  if (d.last_minute) t.push(`<span class="tag lm">${ic("clock")}Last minute</span>`);
  if (d.is_new) t.push('<span class="tag new">New</span>');
  if (d.cabin && d.cabin !== "economy") t.push(`<span class="tag">${d.cabin[0].toUpperCase() + d.cabin.slice(1)}</span>`);
  if (d.subtype === "cruise") t.push(d.trip_kind === "fly_cruise_package" ? `<span class="tag prot">${ic("shield")}Fly & cruise package</span>` : '<span class="tag">Cruise + own flights</span>');
  return t.join("");
}
function facts(d) {
  const f = [];
  if (d.nights) f.push(`<span>${ic("moon")}${d.nights} nights</span>`);
  if (d.stars) f.push(`<span>${ic("star")}${d.stars}★ hotel</span>`);
  if (d.board) f.push(`<span>${ic("food")}${esc(d.board)}</span>`);
  if (d.subtype === "flight" && d.baggage === "included") f.push(`<span>${ic("bag")}Bag included</span>`);
  if (d.port) f.push(`<span>${ic("pin")}From ${esc(d.port)}</span>`);
  if (d.depart_date && f.length < 3) f.push(`<span>${ic("clock")}${esc(fmtDate(d.depart_date))} – ${esc(fmtDate(d.return_date))}</span>`);
  if (d.live_status === "confirmed") f.unshift(`<span class="lv ok">✓ Live price checked</span>`);
  else if (d.live_status === "higher") f.unshift(`<span class="lv warn">Price rose – re-scored at ${eur(d.live_price)}</span>`);
  else if (d.live_status === "unavailable") f.unshift(`<span class="lv warn">No matching live offer</span>`);
  if (d.travel_window && f.length < 3) f.push(`<span>${ic("clock")}${esc(d.travel_window.slice(0, 28))}</span>`);
  return f.length ? `<div class="facts-row">${f.join("")}</div>` : "";
}
function routeLine(d) {
  const pos = d.positioning, dest = `${esc(d.dest)}${d.dest_country && d.dest_country !== d.dest ? ", " + esc(d.dest_country) : ""}`;
  if (pos && pos.mode === "flight") return `<span class="hub">${esc(pos.hub_name)}</span> ✈ ${esc(d.origin_label)} → ${dest}`;
  if (pos && pos.mode === "nearby") return `<span class="hub">${esc(pos.hub_name)}</span> 🚆 ${esc(d.origin_label)} → ${dest}`;
  if (d.origin === "EU*" && d.subtype === "cruise") return `${dest} <span class="muted">· flights to the port from your hub included</span>`;
  if (d.origin === "EU*") return `${dest} <span class="muted">· departure airport not specified</span>`;
  return `${esc(d.origin_label)} → ${dest}`;
}
// one price everywhere (cards, list, drawer, sorting): the whole trip from your home city – computed by the API
const total = (d) => d.total || d.home_total || (d.subtype === "cruise" && d.trip_total ? d.trip_total : d.price);
const sharedNote = (d) => d.shared_price ? `lowest of ${d.shared_price.cities} cities in the post – may cost more from ${esc(d.origin_label)}` : "";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDate = (iso) => (iso && /^\d{4}-\d{2}-\d{2}/.test(iso) ? `${+iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]}` : iso || "");
const bg = (url) => (url ? `style="background-image:url('${esc(url)}')"` : "");
function dealCard(d, compact = false) {
  const pos = d.positioning;
  const main = total(d);
  const mainLabel = d.home_total ? `total from ${esc(pos.hub_name)}` : d.subtype === "cruise" ? "complete trip pp" : basisLabel(d);
  const sp = d.trip_split;
  const ref = d.subtype === "cruise" && sp ? `Cruise ${eur(sp.fare)} + ${sp.flights_included ? "flights included" : `flights ${eur(sp.flights)}`} + fees ${eur(sp.extras)}${d.home_total && pos && pos.price ? ` + ${pos.estimated ? "≈" : ""}${eur(pos.price)} to ${esc(pos.gateway_name || "the departure airport")}` : ""} · typical ${eur(d.reference)}` :
    d.subtype === "cruise" ? `Cruise fare ${eur(d.price)} · typical trip ${eur(d.reference)}` :
    d.price_for_two && !d.home_total ? `${eur(d.price_for_two)} for 2 · typical ${eur(d.reference)}` : `typical ${eur(d.reference)}`;
  return `<article class="panel deal" data-id="${d.id}" tabindex="0">
    <div class="ph" ${bg(d.image)}><div class="tags">${tags(d)}</div><div class="dest">${esc(d.dest)}</div></div>
    <div class="body">
      <div class="from">${routeLine(d)}</div>
      ${compact ? "" : facts(d)}
      <div class="row">
        <div><div class="price num">${eur(main)}<small>${mainLabel}</small></div>
        <div class="ref">${d.home_total && pos && pos.price && d.subtype !== "cruise" ? `${eur(main - pos.price * (d.price_basis === "total" ? 2 : 1))} deal + ${pos.estimated ? "≈" : ""}${eur(pos.price)} ${pos.mode === "nearby" ? "train/bus" : pos.hotel ? "flight + hotel night" : "flight"} · ` : ""}${ref}${d.savings > 0 ? ` · <b>save ${eur(d.savings)}</b>` : ""}${d.shared_price ? `<div class="shared">${sharedNote(d)}</div>` : ""}</div></div>
        ${scoreBadge(d.score)}
      </div>
      ${compact ? "" : `<div class="foot"><span>${esc(d.provider_name)}</span><span>${d.urgency.level === "high" ? `<span style="color:var(--urgent)">${esc(d.urgency.label)}</span>` : "seen " + ago(d.last_seen_at)}</span></div>`}
    </div></article>`;
}
// compact table-like view for scanning many offers quickly
const listHead = () => `<div class="lrow head"><span>Destination</span><span>Route</span><span>Dates</span><span class="r">Total</span><span class="r">Saving</span><span class="r">Score</span></div>`;
// departure airports for the "From" picker: home hubs first, then the other airports being watched
function fromOptions(sel) {
  const ap = state.airports || [];
  const opt = (a) => `<option value="${a.iata}" ${sel === a.iata ? "selected" : ""}>From ${esc(a.city)} (${a.iata})</option>`;
  const hubs = ap.filter((a) => a.home), others = ap.filter((a) => !a.home && a.enabled);
  return `<option value="">From any airport</option>${hubs.length ? `<optgroup label="Your home airports">${hubs.map(opt).join("")}</optgroup>` : ""}` +
    (others.length ? `<optgroup label="Other airports">${others.map(opt).join("")}</optgroup>` : "");
}
// "Search & book": exact searches from the post first, then searches HubFare builds from route + dates
function bookingSection(d) {
  const links = d.booking || [];
  if (!links.length) return "";
  const fromPost = links.filter((l) => l.from_post), built = links.filter((l) => !l.from_post);
  const row = (l) => `<a class="book-link" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">
      <span class="site">${esc(l.site)}</span><span class="lbl">${esc(l.label)}</span>${ic("ext")}</a>`;
  return `<div class="sec"><h4>Search &amp; book</h4>
    ${fromPost.length ? `<div class="muted" style="font-size:12px;margin-bottom:6px">Exact searches from the original post</div><div class="book-list">${fromPost.map(row).join("")}</div>` : ""}
    ${built.length ? `<div class="muted" style="font-size:12px;margin:${fromPost.length ? 12 : 0}px 0 6px">${d.depart_date ? "Live searches for these dates" : "Live searches – pick your dates on the site"}</div><div class="book-list">${built.map(row).join("")}</div>` : ""}
    <div class="muted" style="font-size:11.5px;margin-top:8px">Opens a live search – the advertised price may have changed. HubFare never books anything.</div></div>`;
}
function listRow(d) {
  const when = d.depart_date ? `${fmtDate(d.depart_date)} – ${fmtDate(d.return_date)}` : d.nights ? `${d.nights} nights` : esc((d.travel_window || "flexible").slice(0, 24));
  return `<div class="lrow" data-id="${d.id}" tabindex="0">
    <span class="dst"><b>${esc(d.dest)}</b>${d.live_status === "confirmed" ? ' <span class="ok">✓</span>' : ""}</span>
    <span class="muted rt">${routeLine(d)}</span>
    <span class="muted">${when}</span>
    <span class="r num"><b>${eur(total(d))}</b></span>
    <span class="r num save">−${Math.round(d.discount)}%</span>
    <span class="r">${scoreBadge(d.score)}</span></div>`;
}
function miniRow(d, sub) {
  return `<div class="mini" data-id="${d.id}"><div class="thumb" ${bg(d.image)}></div>
    <div style="min-width:0"><div class="t">${routeLine(d)}</div><div class="s">${esc(sub)}</div></div>
    <div class="p num">${eur(total(d))}<small>${d.score}/100</small></div></div>`;
}
function bindCards(root) {
  root.querySelectorAll("[data-id]").forEach((el) => {
    el.addEventListener("click", () => openDeal(+el.dataset.id));
    el.addEventListener("keydown", (e) => e.key === "Enter" && openDeal(+el.dataset.id));
  });
}

/* ------------------------------------------------------------------ overview */
async function viewOverview(v) {
  setTitle("Overview", "What the scanners found for you – only offers that beat typical prices");
  v.innerHTML = `<div class="cat-grid">${[0, 1, 2].map(() => '<div class="skeleton" style="height:76px"></div>').join("")}</div>
    <div class="ov-row"><div class="skeleton" style="height:300px"></div><div class="skeleton" style="height:300px"></div></div>`;
  const o = await api("/overview");
  state.overview = o;
  state.counts = Object.fromEntries(Object.entries(o.categories).map(([k, c]) => [k, c.active]));
  renderNav("overview");
  renderMonitoring(o.monitoring, o.my_airports);
  setBell(o.unread);
  const cats = Object.entries(CAT_META).map(([k, m]) => {
    const c = o.categories[k];
    return `<a class="panel cat-card" href="#/${m.page}"><div class="cat-icon">${ic(m.icon)}</div>
      <div class="cat-body"><div class="name">${m.label}</div><div class="meta">${c.best_price ? `From ${eur(c.best_price)}` : m.sub}${c.error_fares ? ` · <span style="color:#ff8aa0">${c.error_fares} possible error fare${c.error_fares > 1 ? "s" : ""}</span>` : ""}</div></div>
      <div class="cat-stats"><div class="big num">${c.active}</div><div class="new">${c.new ? `+${c.new} new` : "active"}</div></div></a>`;
  }).join("");
  const b = o.best;
  const best = b ? `<article class="panel best" data-id="${b.id}">
      <div class="bg" ${bg(b.image)}></div>
      <div class="inner">
        <div style="display:flex;gap:6px;flex-wrap:wrap"><span class="tag flat">Best opportunity</span>${tags(b)}</div>
        <div><h3>${esc(b.dest)}</h3><div class="route">${routeLine(b)} · ${CAT_META[b.category].label}</div></div>
        ${facts(b)}
        <div class="price-line"><span class="price num">${eur(total(b))}</span>
          <span class="was num">${eur(b.reference)}</span>
          <span style="color:var(--save);font-weight:600">−${Math.round(b.discount)}%</span></div>
        <div class="facts"><span><b style="color:var(--text)">${b.score}/100</b> ${esc(b.band)}</span><span>${esc(b.provider_name)}</span><span>Seen ${ago(b.last_seen_at)}</span></div>
      </div></article>` : `<div class="panel empty">No qualifying deals yet – the worker is scanning sources.</div>`;
  const exp = o.expiring.length ? o.expiring.map((d) => miniRow(d, d.urgency.label)).join("") : '<div class="empty">Nothing urgent right now.</div>';
  const latest = o.latest.length ? `<div class="grid compact">${o.latest.map((d) => dealCard(d, true)).join("")}</div>` : '<div class="panel empty">No exceptional deals in the last scans.</div>';
  const drops = o.price_drops.length ? o.price_drops.map((d) => miniRow(d, `Dropped from ${eur(d.previous)} → ${eur(d.price)}`)).join("") :
    '<div class="empty">No price drops detected yet. Prices are re-checked on every scan.</div>';
  const m = o.monitoring;
  v.innerHTML = `
    <div class="cat-grid">${cats}</div>
    <div class="ov-row">${best}
      <div class="panel side-list"><div class="head"><h3>May disappear soon</h3><span class="muted" style="font-size:12px">${o.expiring.length}</span></div>${exp}</div>
    </div>
    <div class="section-head"><h2>Latest exceptional deals</h2><span class="muted" style="font-size:12.5px">${o.relevant_count} of ${o.total_count} active deals depart from your airports or markets${o.unresolved_count ? ` · ${o.unresolved_count} without a departure airport are kept out of the top lists` : ""}</span></div>
    ${latest}
    <div class="section-head"><h2>Recent price drops</h2></div>
    <div>
      <div class="panel side-list">${drops}</div>
      ${!m.worker_running ? `<div class="notice warn" style="margin-top:12px">New deals are paused – the scanner isn't running. See Settings → Monitoring status.</div>` : ""}
    </div>`;
  bindCards(v);
}

/* ------------------------------------------------------------------ category lists */
const CAT_FILTERS = {
  flight: [["error", "Error fares", "zap"], ["last_minute", "Last minute", "clock"], ["premium", "Business & premium", "star"]],
  package: [["error", "Possible pricing errors", "zap"], ["last_minute", "Last minute", "clock"]],
  cruise: [["fly", "Fly & cruise packages", "shield"], ["own", "Independent combos", "flight"], ["last_minute", "Last minute", "clock"]],
};
async function viewCategory(v, cat) {
  const meta = CAT_META[cat];
  const subs = {
    flight: "Suspected error fares, exceptional long-haul discounts and premium cabins from European airports",
    package: "Complete holidays with flights + accommodation. Prices are per person unless stated; total for two shown on each card",
    cruise: "Ranked by the complete trip cost: cruise fare + flights to the port + fees, transfers and a pre-cruise night",
  };
  setTitle(NAV.find((n) => n.cat === cat).label, subs[cat]);
  const f = state.filters[cat] || (state.filters[cat] = { sort: "score" });
  const regions = (state.regions ||= (await api("/settings")).regions);
  const chips = CAT_FILTERS[cat].map(([k, l, i]) => {
    const on = f[k] ? (k === "error" ? "on-err" : k === "last_minute" ? "on-lm" : "on") : "";
    return `<button class="chip ${on}" data-f="${k}">${ic(i)}${l}</button>`;
  }).join("");
  v.innerHTML = `<div class="filters">${chips}
      <button class="chip ${f.relevant ? "on" : ""}" data-f="relevant">${ic("pin")}From my airports</button>
      <select id="f-from" title="Show every deal as a trip from this airport">${fromOptions(f.from)}</select>
      <select id="f-region"><option value="">All destinations</option>${regions.map((r) => `<option value="${r.key}" ${f.region === r.key ? "selected" : ""}>${esc(r.label)}</option>`).join("")}</select>
      <select id="f-sort">${[["score", "Best score"], ["new", "Newest"], ["price", "Lowest price"], ["savings", "Biggest savings"]].map(([k, l]) => `<option value="${k}" ${f.sort === k ? "selected" : ""}>${l}</option>`).join("")}</select>
      <span class="spacer"></span><span class="result-count" id="count"></span>
      <div class="seg" role="group" aria-label="Layout"><button data-layout="cards" class="${store.get("te-layout", "cards") === "cards" ? "on" : ""}">Cards</button><button data-layout="list" class="${store.get("te-layout", "cards") === "list" ? "on" : ""}">List</button></div></div>
    <div class="grid" id="list">${[0, 1, 2, 3, 4, 5].map(() => '<div class="skeleton" style="height:300px"></div>').join("")}</div>`;
  v.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.f; f[k] = !f[k];
    if (k === "fly" && f.fly) f.own = false;
    if (k === "own" && f.own) f.fly = false;
    store.set("te-filters", state.filters); viewCategory(v, cat);
  }));
  $("#f-from").onchange = (e) => { f.from = e.target.value; store.set("te-filters", state.filters); load(); };
  $("#f-region").onchange = (e) => { f.region = e.target.value; store.set("te-filters", state.filters); load(); };
  v.querySelectorAll("[data-layout]").forEach((b) => (b.onclick = () => { store.set("te-layout", b.dataset.layout); viewCategory(v, cat); }));
  $("#f-sort").onchange = (e) => { f.sort = e.target.value; store.set("te-filters", state.filters); load(); };
  async function load() {
    const q = new URLSearchParams({ category: cat, sort: f.sort || "score" });
    if (f.error) q.set("error", "true");
    if (f.last_minute) q.set("last_minute", "true");
    if (f.relevant) q.set("relevant", "true");
    if (f.region) q.set("region", f.region);
    if (f.from) q.set("from_airport", f.from);
    if (f.fly) q.set("trip_kind", "fly_cruise_package");
    if (f.own) q.set("trip_kind", "independent_combination");
    let { items, count } = await api("/offers?" + q);
    if (f.premium) items = items.filter((d) => d.cabin !== "economy");
    $("#count").textContent = `${f.premium ? items.length : count} qualifying offer${count === 1 ? "" : "s"}`;
    const list = $("#list");
    const asList = store.get("te-layout", "cards") === "list";
    list.className = asList ? "deal-list panel" : "grid";
    list.innerHTML = items.length ? (asList ? listHead() + items.map(listRow).join("") : items.map((d) => dealCard(d)).join("")) :
      `<div class="panel empty" style="grid-column:1/-1">No ${meta.label.toLowerCase()} match these filters right now.<br>The scanners keep looking – matching deals will appear here and trigger your alerts.</div>`;
    bindCards(list);
  }
  load();
}

/* ------------------------------------------------------------------ deal drawer */
let chart;
async function openDeal(id) {
  const dr = $("#drawer");
  $("#drawer-backdrop").hidden = false;
  dr.classList.add("open"); dr.setAttribute("aria-hidden", "false");
  dr.innerHTML = '<div class="skeleton" style="height:230px;border-radius:0"></div>';
  const d = await api(`/offers/${id}`);
  const b = d.breakdown || {};
  const tc = b.trip_cost;
  const flagNotice = d.error_flag === "suspected_source"
    ? `<div class="notice err"><b>Suspected error fare.</b> The publishing source describes this as an error/mistake fare. It is <u>not confirmed</u> – airlines may cancel tickets issued at mistaken prices. Avoid non-refundable extras until the booking is ticketed.</div>`
    : d.error_flag === "suspected_statistical"
      ? `<div class="notice err"><b>Possible pricing error (unconfirmed).</b> This price is an extreme statistical outlier (${Math.round(d.discount)}% below the reference). No source has confirmed a mistake – it may also be an aggressive promotion.</div>` : "";
  const urg = d.urgency.level !== "low" ? `<div class="notice warn" style="margin-top:8px">${esc(d.urgency.label)}</div>` : "";
  const mainPrice = total(d);
  const tripRows = tc ? `<div class="sec"><h4>Complete trip cost (per person)</h4>
      <div class="notice ${tc.kind === "fly_cruise_package" ? "ok" : ""}" style="margin-bottom:10px">${tc.kind === "fly_cruise_package"
        ? "<b>Fly & cruise package</b> – flights are sold together with the cruise, so you are protected if a flight delay makes you miss embarkation (EU package travel rules)."
        : "<b>Independent combination</b> – cruise and flights are booked separately. You carry the risk of missed connections; arrive the day before."}</div>
      <div class="breakdown">${tc.parts.map((p) => `<div class="line"><span>${esc(p.label)} <span class="muted">· ${esc(p.source)}</span></span><span class="num">${eur(p.eur)}</span></div>`).join("")}
      <div class="line"><b>Estimated complete trip</b><b class="num">${eur(tc.total_pp)}</b></div></div></div>` : "";
  const mods = (b.modifiers || []).map((m) => `<div class="line"><span>${esc(m.label)}</span><span class="${m.points >= 0 ? "pos" : "neg"}">${m.points >= 0 ? "+" : ""}${m.points}</span></div>`).join("");
  const basis = d.home_total && d.positioning
    ? `From ${esc(d.positioning.hub_name)}: ${eur(d.subtype === "cruise" && d.trip_total ? d.trip_total : d.price)} deal + ${d.positioning.estimated ? "≈" : ""}${eur(d.positioning.price)} getting there`
    : d.price_basis === "total" ? "Total for 2 travellers" : d.subtype === "flight" ? "Per person" : `Per person · ${eur(d.price_for_two)} for 2`;
  dr.innerHTML = `
    <div class="hero" ${bg(d.image)}><button class="icon-btn close" id="dr-close" aria-label="Close">${ic("x")}</button>
      <div class="h"><div style="display:flex;gap:6px;flex-wrap:wrap">${tags(d)}</div><h2>${esc(d.dest)}</h2>
      <div class="muted" style="color:var(--text-2)">${esc(d.origin_label)} → ${esc(d.dest)}${d.dest_country !== d.dest ? ", " + esc(d.dest_country) : ""} · ${CAT_META[d.category].label}</div></div></div>
    <div class="sec">${flagNotice}${urg}
      <div class="price-box" style="margin-top:${flagNotice || urg ? 12 : 0}px">
        <div><div class="k">${tc ? "Complete trip" : "Price"}</div><div class="v num">${eur(mainPrice)}</div><div class="k">${tc ? "Cruise fare " + eur(d.price) : basis}</div></div>
        <div><div class="k">Typical comparable</div><div class="v num">${eur(d.reference)}</div><div class="k">${b.history_n ? `${b.history_n} observed prices` : "model reference"}</div></div>
        <div><div class="k">Estimated savings</div><div class="v save num">${eur(d.savings)}</div><div class="k">${Math.round(d.discount)}% below typical</div></div>
      </div></div>
    ${d.shared_price ? `<div class="sec"><div class="notice warn"><b>Price shared by ${d.shared_price.cities} departure cities.</b> The post gives one "from" price for ${esc(d.shared_price.listed.join(", "))}. It is usually available from only some of them – check the live search for ${esc(d.origin_label)}.</div></div>` : ""}
    ${bookingSection(d)}
    ${(d.other_cities || []).length ? `<div class="sec"><h4>Same post, other departure cities</h4><div class="breakdown">${d.other_cities.map((c) => `<div class="line"><a href="#" data-open="${c.id}">${esc(c.origin)} (${esc(c.code)})</a><span class="num">${eur(c.total)} <span class="muted">${c.positioning && c.positioning.hub_name ? "from " + esc(c.positioning.hub_name) : ""}</span></span></div>`).join("")}</div></div>` : ""}
    <div class="sec"><h4>Deal Score ${d.score}/100 · ${esc(b.band || "")}</h4>
      <div class="breakdown">
        <div class="line"><span>Base points from ${Math.round(d.discount)}% discount vs. reference</span><span class="pos">${b.base_points ?? "—"}</span></div>
        ${mods}
        <div class="line"><b>Deal Score</b><b>${d.score}</b></div>
        <div style="margin-top:10px" class="muted">How the reference price was built:</div>
        <ul>${(b.reference_explained || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        ${(b.parse_notes || []).length ? `<div class="muted" style="margin-top:6px">Data notes: ${esc(b.parse_notes.join("; "))}</div>` : ""}
      </div></div>
    ${tripRows}
    <div class="sec"><h4>Details</h4><dl class="kv">
      <dt>Departure</dt><dd>${esc(d.origin_label)}</dd>
      <dt>Destination</dt><dd>${esc(d.dest)}${d.dest_country !== d.dest ? ", " + esc(d.dest_country) : ""} <span class="muted">(${esc(d.region)})</span></dd>
      ${d.subtype === "flight" ? `<dt>Trip</dt><dd>${d.trip_type === "one_way" ? "One-way" : "Return"} · ${esc(d.cabin)}</dd><dt>Baggage</dt><dd>${esc(d.baggage)}</dd>` : ""}
      ${d.nights ? `<dt>Duration</dt><dd>${d.nights} nights</dd>` : ""}
      ${d.stars ? `<dt>Hotel</dt><dd>${d.stars}-star</dd>` : ""}
      ${d.board ? `<dt>Board</dt><dd>${esc(d.board)}</dd>` : ""}
      ${d.subtype !== "flight" ? `<dt>Pricing</dt><dd>${basis}${d.price_basis === "per_person" ? " – based on 2 adults sharing unless the offer says otherwise" : ""}</dd>` : ""}
      ${d.depart_date ? `<dt>Dates</dt><dd>${esc(fmtDate(d.depart_date))} – ${esc(fmtDate(d.return_date))}</dd>` : d.travel_window ? `<dt>Travel period</dt><dd>${esc(d.travel_window)}</dd>` : `<dt>Travel dates</dt><dd class="muted">Flexible – see provider for available dates</dd>`}
      ${d.currency !== "EUR" ? `<dt>Original price</dt><dd>${d.price_original.toLocaleString()} ${esc(d.currency)} (ECB rate)</dd>` : ""}
      ${d.positioning && d.positioning.note ? `<dt>Getting there</dt><dd>${esc(d.positioning.note)}${d.positioning.estimated ? ' <span class="muted">(estimate – real fare once Travelpayouts is connected)</span>' : d.positioning.airline ? ` · ${esc(d.positioning.airline)} ${esc(d.positioning.dates || "")}` : ""}</dd>` : ""}
      <dt>Provider</dt><dd>${esc(d.provider_name)}</dd>
      <dt>Published</dt><dd>${ago(d.published_at)}</dd>
      <dt>Last seen in feed</dt><dd>${ago(d.last_seen_at)}</dd>
      ${d.subtype === "flight" ? `<dt>Live airline price</dt><dd>${d.live_checked_at ? `${d.live_price ? eur(d.live_price) + " · " : ""}${esc(d.live_status)}${d.live_detail ? " · " + esc(d.live_detail) : ""} <span class="muted">(${ago(d.live_checked_at)})</span>` : '<span class="muted">not checked yet</span>'}</dd>` : ""}
      <dt>Link verified</dt><dd>${d.last_verified_at ? `${ago(d.last_verified_at)} – ${esc(d.link_status)}` : "pending"}</dd>
    </dl>
    <p class="muted" style="font-size:12.5px;margin-top:12px">${esc(d.title)}</p></div>
    <div class="sec"><h4>Price history – ${esc(d.dest)}</h4>${d.history.length > 1 ? '<div class="chart" id="hist-chart"></div>' : `<div class="notice">History builds up with every scan. ${d.history.length} observation so far for this destination.</div>`}</div>
    ${d.comparables.length ? `<div class="sec"><h4>Same destination, other offers</h4><div class="breakdown">${d.comparables.map((c) => `<div class="line"><span>${esc(c.origin)} <span class="muted">· ${esc(c.provider)}${c.duplicate ? " · duplicate" : ""}</span></span><span class="num">${eur(c.price)} <span class="muted">· ${c.score}</span></span></div>`).join("")}</div></div>` : ""}
    ${d.also_seen_at.length ? `<div class="sec"><h4>Also published by</h4><div class="breakdown">${d.also_seen_at.map((x) => `<div class="line"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.provider)}</a><span>${eur(x.price)}</span></div>`).join("")}</div></div>` : ""}
    <div class="cta-row">
      ${(d.booking || []).length
        ? `<a class="btn primary" href="${esc(d.booking[0].url)}" target="_blank" rel="noopener noreferrer">Search on ${esc(d.booking[0].site)} ${ic("ext")}</a>
           <a class="btn" href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">Read post</a>`
        : `<a class="btn primary" href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">View offer at ${esc(d.provider_name)} ${ic("ext")}</a>`}
      <button class="btn" id="dr-save">${ic("saved")}${d.saved ? "Saved" : "Save"}</button>
    </div>
    <p class="muted" style="font-size:11.5px;padding:0 24px 24px;margin:0">HubFare never books or pays for anything. Always confirm the final price, baggage and fees with the provider.</p>`;
  $("#dr-close").onclick = closeDeal;
  dr.querySelectorAll("[data-open]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); openDeal(+a.dataset.open); }));
  $("#dr-save").onclick = async () => { const r = await api(`/offers/${id}/save`, { method: "POST" }); $("#dr-save").innerHTML = ic("saved") + (r.saved ? "Saved" : "Save"); toast(r.saved ? "Saved to your deals" : "Removed from saved"); };
  if (d.history.length > 1 && window.echarts) {
    chart?.dispose();
    chart = echarts.init($("#hist-chart"), null, { renderer: "svg" });
    const byOrigin = {};
    d.history.forEach((h) => (byOrigin[h.origin] ||= []).push([h.t, h.price]));
    chart.setOption({
      backgroundColor: "transparent", grid: { left: 44, right: 12, top: 16, bottom: 28 },
      tooltip: { trigger: "item", valueFormatter: (v) => eur(v), backgroundColor: "#152038", borderColor: "#2a3858", textStyle: { color: "#e8edf7" } },
      xAxis: { type: "time", axisLine: { lineStyle: { color: "#2a3858" } }, axisLabel: { color: "#7d8aa5" }, splitLine: { show: false } },
      yAxis: { type: "value", axisLabel: { color: "#7d8aa5", formatter: (v) => "€" + v }, splitLine: { lineStyle: { color: "#1f2b45" } } },
      series: [...Object.entries(byOrigin).map(([o, pts]) => ({ name: o, type: "line", symbolSize: 7, data: pts, lineStyle: { width: 1.5 } })),
        { name: "Reference", type: "line", data: [], markLine: { symbol: "none", data: [{ yAxis: d.reference }], lineStyle: { color: "#34d399", type: "dashed" }, label: { color: "#34d399", formatter: "typical €" + d.reference } } }],
      color: ["#6d8bff", "#f5c76b", "#5ec8f5", "#fb923c", "#c084fc", "#f472b6"],
    });
  }
}
function closeDeal() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#drawer-backdrop").hidden = true; }

/* ------------------------------------------------------------------ saved */
async function viewSaved(v) {
  setTitle("Saved Deals", "Offers you bookmarked. Expired offers stay here so you can compare later");
  const r = await api("/saved");
  v.innerHTML = r.offers.length ? `<div class="grid" id="list">${r.offers.map((d) => dealCard(d)).join("")}</div>` :
    `<div class="panel empty">No saved deals yet. Open any deal and press <b>Save</b>.</div>`;
  bindCards(v);
}

/* ------------------------------------------------------------------ alerts */
const CAT_OPTS = [["flight", "Flights"], ["package", "Holiday packages"], ["cruise", "Cruises + flights"], ["error_fare", "Error fares only"], ["last_minute", "Last minute only"]];
async function viewAlerts(v) {
  setTitle("Alerts", "High-priority deals are sent instantly; everything else that matches arrives in one daily digest");
  const [a, s, n] = await Promise.all([api("/alerts"), api("/settings"), api("/notifications?limit=30")]);
  const chs = Object.entries(a.channels);
  const describe = (r) => [
    r.categories.length ? r.categories.map((c) => (CAT_OPTS.find((x) => x[0] === c) || [c, c])[1]).join(", ") : "All categories",
    r.origins.length ? "from " + r.origins.join(", ") : "any airport",
    r.destinations.length ? "to " + r.destinations.join(", ") : "any destination",
    r.max_price ? "≤ " + eur(r.max_price) : null, `score ≥ ${r.min_score}`,
    r.cabins?.length ? r.cabins.join("/") : null,
    r.min_nights || r.max_nights ? `${r.min_nights || 1}–${r.max_nights || "∞"} nights` : null,
    `${r.mode === "auto" ? "instant if ≥85 or error fare, else digest" : r.mode}`,
    "via " + r.channels.map((c) => a.channels[c]?.label.split(" ")[0] || c).join(", "),
  ].filter(Boolean).join(" · ");
  v.innerHTML = `
    <div class="panel"><div class="rule" style="align-items:center"><div><div class="name">Alert rules</div><div class="desc">Each rule is checked against every new offer and every price drop. A deal is never sent twice for the same rule and channel.</div></div>
      <div class="acts"><button class="btn primary small" id="new-rule">New alert</button></div></div>
      ${a.rules.map((r) => `<div class="rule"><div><div class="name">${esc(r.name)} <span class="muted" style="font-weight:500;font-size:12px">· ${r.matching_now} matching now</span></div><div class="desc">${esc(describe(r))}</div></div>
        <div class="acts"><button class="switch ${r.enabled ? "on" : ""}" data-toggle="${r.id}" aria-label="Enable"></button><button class="btn small ghost" data-edit="${r.id}">Edit</button><button class="btn small ghost danger" data-del="${r.id}">Delete</button></div></div>`).join("") || '<div class="empty">No alert rules yet.</div>'}
    </div>
    <div id="rule-form"></div>
    <div class="section-head"><h2>Notification channels</h2><span class="muted" style="font-size:12.5px">Credentials are read from environment variables – never stored in the browser</span></div>
    <div class="ch-list">${chs.map(([k, c]) => `<label class="ch"><input type="checkbox" value="${k}" ${k === "inapp" ? "checked" : ""} ${c.configured ? "" : "disabled"}>
      <div><div>${esc(c.label)}</div><div class="sub">${c.configured ? '<span style="color:var(--save)">Configured</span>' : "Needs " + esc(c.needs)}</div></div></label>`).join("")}</div>
    <div style="display:flex;gap:10px;margin-top:12px;align-items:center;flex-wrap:wrap">
      <button class="btn" id="test-btn">Send test notification</button>
      <button class="btn ghost" id="perm-btn">${"Notification" in window && Notification.permission === "granted" ? "Browser notifications on" : "Enable browser notifications"}</button>
      <span class="muted" style="font-size:12.5px">The test uses the current best real deal.</span></div>
    <div id="test-result"></div>
    <div class="section-head"><h2>Recent notifications</h2></div>
    <div class="panel">${n.items.length ? n.items.map((x) => `<div class="notif-item" data-n="${x.id}"><div class="t">${esc(x.title)}</div>
      <div class="m">${esc(x.kind)} · ${esc(x.channel)} · <span style="color:${x.status === "sent" ? "var(--save)" : x.status === "failed" ? "var(--danger)" : "var(--muted)"}">${esc(x.status)}</span> · ${ago(x.created_at)}${x.error ? " · " + esc(x.error) : ""}</div>
      <pre class="body" hidden>${esc(x.body)}</pre></div>`).join("") : '<div class="empty">No notifications yet.</div>'}</div>`;
  v.querySelectorAll("[data-n]").forEach((el) => el.addEventListener("click", () => { const p = el.querySelector("pre"); p.hidden = !p.hidden; }));
  v.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", async () => {
    const r = a.rules.find((x) => x.id == b.dataset.toggle); r.enabled = !r.enabled;
    await api(`/alerts/${r.id}`, { method: "PUT", body: r }); viewAlerts(v);
  }));
  v.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Delete this alert rule?")) return;
    await api(`/alerts/${b.dataset.del}`, { method: "DELETE" }); viewAlerts(v);
  }));
  v.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => ruleForm(a, s, a.rules.find((x) => x.id == b.dataset.edit), v)));
  $("#new-rule").onclick = () => ruleForm(a, s, null, v);
  $("#perm-btn").onclick = async () => { if ("Notification" in window) { await Notification.requestPermission(); viewAlerts(v); } };
  $("#test-btn").onclick = async () => {
    const chosen = [...v.querySelectorAll(".ch input:checked")].map((i) => i.value);
    const r = await api("/notifications/test", { method: "POST", body: { channels: chosen.length ? chosen : ["inapp"] } });
    $("#test-result").innerHTML = `<div class="notice ${r.results.every((x) => x.status === "sent" || x.channel === "inapp") ? "ok" : "warn"}" style="margin-top:10px">${r.results.map((x) => `${esc(x.channel)}: <b>${esc(x.status)}</b>${x.error ? " – " + esc(x.error) : ""}`).join("<br>")}</div>`;
    pollNotifications(true);
    setTimeout(() => viewAlerts(v), 1200);
  };
}
function ruleForm(a, s, r, v) {
  r = r || { name: "", origins: [], destinations: [], categories: [], cabins: [], max_price: null, min_score: 80, min_nights: null, max_nights: null, channels: ["inapp"], mode: "auto", enabled: true, min_discount_pct: null };
  const enabledAp = s.airports.filter((x) => x.enabled);
  const box = $("#rule-form");
  box.innerHTML = `<div class="panel card-pad" style="margin-top:14px">
    <div class="section-head" style="margin-top:0"><h2>${r.id ? "Edit alert" : "New alert"}</h2></div>
    <div class="form-grid">
      <label class="field">Name<input type="text" id="r-name" value="${esc(r.name)}" placeholder="e.g. Asia under €450 from Vienna"></label>
      <label class="field">Maximum price (€, per person)<input type="number" id="r-max" value="${r.max_price ?? ""}" placeholder="any"></label>
      <label class="field">Minimum Deal Score<input type="number" id="r-score" min="0" max="100" value="${r.min_score}"></label>
      <label class="field">Minimum discount (%)<input type="number" id="r-disc" value="${r.min_discount_pct ?? ""}" placeholder="any"></label>
      <label class="field">Min nights<input type="number" id="r-minn" value="${r.min_nights ?? ""}" placeholder="any"></label>
      <label class="field">Max nights<input type="number" id="r-maxn" value="${r.max_nights ?? ""}" placeholder="any"></label>
      <label class="field">Delivery<select id="r-mode"><option value="auto" ${r.mode === "auto" ? "selected" : ""}>Smart (instant if ≥85 / error fare, else digest)</option><option value="instant" ${r.mode === "instant" ? "selected" : ""}>Always instant</option><option value="digest" ${r.mode === "digest" ? "selected" : ""}>Daily digest only</option></select></label>
      <label class="field">Destinations<select id="r-dest" multiple size="4">${s.regions.map((x) => `<option value="${x.key}" ${r.destinations.includes(x.key) ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>
    </div>
    <div class="field" style="margin-top:14px">Categories<div class="checks">${CAT_OPTS.map(([k, l]) => `<button class="chip ${r.categories.includes(k) ? "on" : ""}" data-cat="${k}">${l}</button>`).join("")}</div></div>
    <div class="field" style="margin-top:12px">Cabin (flights)<div class="checks">${["economy", "premium", "business", "first"].map((k) => `<button class="chip ${r.cabins.includes(k) ? "on" : ""}" data-cab="${k}">${k}</button>`).join("")}</div></div>
    <div class="field" style="margin-top:12px">Departure airports (none = any)<div class="airports">${enabledAp.map((x) => `<button class="ap ${r.origins.includes(x.iata) ? "on" : ""}" data-ap="${x.iata}"><b>${x.iata}</b>${esc(x.city)}</button>`).join("")}</div></div>
    <div class="field" style="margin-top:12px">Channels<div class="checks">${Object.entries(a.channels).map(([k, c]) => `<button class="chip ${r.channels.includes(k) ? "on" : ""}" data-ch="${k}" title="${c.configured ? "" : "Not configured: " + esc(c.needs)}">${esc(c.label.split(" (")[0])}${c.configured ? "" : " ·  setup needed"}</button>`).join("")}</div></div>
    <div style="display:flex;gap:10px;margin-top:18px"><button class="btn primary" id="r-save">Save alert</button><button class="btn ghost" id="r-cancel">Cancel</button></div></div>`;
  const toggle = (sel, arr) => box.querySelectorAll(sel).forEach((b) => b.addEventListener("click", () => {
    const k = Object.values(b.dataset)[0]; const i = arr.indexOf(k);
    i >= 0 ? arr.splice(i, 1) : arr.push(k); b.classList.toggle("on");
  }));
  toggle("[data-cat]", r.categories); toggle("[data-cab]", r.cabins); toggle("[data-ap]", r.origins); toggle("[data-ch]", r.channels);
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  $("#r-cancel").onclick = () => (box.innerHTML = "");
  $("#r-save").onclick = async () => {
    const num = (id) => ($(id).value === "" ? null : +$(id).value);
    const body = { ...r, name: $("#r-name").value || "Untitled alert", max_price: num("#r-max"), min_score: num("#r-score") ?? 0,
      min_discount_pct: num("#r-disc"), min_nights: num("#r-minn"), max_nights: num("#r-maxn"), mode: $("#r-mode").value,
      destinations: [...$("#r-dest").selectedOptions].map((o) => o.value), channels: r.channels.length ? r.channels : ["inapp"] };
    delete body.id; delete body.matching_now;
    await api(r.id ? `/alerts/${r.id}` : "/alerts", { method: r.id ? "PUT" : "POST", body });
    toast("Alert saved"); viewAlerts(v);
  };
}

/* ------------------------------------------------------------------ settings */
async function viewSettings(v) {
  setTitle("Settings", "Departure airports, what counts as exceptional, and the data sources being monitored");
  const s = await api("/settings");
  const p = s.preferences;
  renderMonitoring(s.monitoring);
  const groups = {};
  s.airports.forEach((a) => (groups[a.priority === 1 ? "Priority" : a.priority === 2 ? "Central & Eastern Europe" : "Other European hubs"] ||= []).push(a));
  v.innerHTML = `
    <div class="cols-2">
      <div class="panel card-pad">
        <div class="section-head" style="margin-top:0"><h2>What counts as exceptional</h2></div>
        <div class="form-grid">
          <label class="field">Show deals with score ≥<input type="number" id="p-min" min="0" max="100" value="${p.min_display_score}"></label>
          <label class="field">Max flight price (€)<input type="number" id="p-mf" value="${p.max_price?.flight ?? ""}" placeholder="no limit"></label>
          <label class="field">Max package price (€ pp)<input type="number" id="p-mp" value="${p.max_price?.package ?? ""}" placeholder="no limit"></label>
          <label class="field">Max cruise trip (€ pp)<input type="number" id="p-mc" value="${p.max_price?.cruise ?? ""}" placeholder="no limit"></label>
        </div>
        <label style="display:flex;gap:10px;align-items:center;margin-top:14px;font-size:13px"><button class="switch ${p.only_my_airports ? "on" : ""}" id="p-only"></button>Only show deals departing from my airports / markets</label>
        <div style="margin-top:16px"><button class="btn primary small" id="p-save">Save preferences</button></div>
        <p class="muted" style="font-size:12.5px;margin-bottom:0">Score bands: 95–100 potential error fare · 85–94 exceptional · 70–84 very good · 50–69 moderate · below 50 ordinary. Methodology: see docs/SCORING.md.</p>
      </div>
      <div class="panel card-pad">
        <div class="section-head" style="margin-top:0"><h2>Monitoring status</h2><span class="status ${s.monitoring.state === "ok" ? "ok" : "failing"}">${s.monitoring.state}</span></div>
        <dl class="kv"><dt>Background worker</dt><dd>${s.monitoring.worker_running ? "Running" : "Not running"} · heartbeat ${ago(s.monitoring.worker_heartbeat)}</dd>
          <dt>Last successful scan</dt><dd>${ago(s.monitoring.last_scan)}</dd><dt>Next scheduled scan</dt><dd>${until(s.monitoring.next_scan)}</dd>
          <dt>Infrastructure cost</dt><dd>${esc(s.costs.infra_note)}</dd><dt>API costs</dt><dd>${esc(s.costs.api_note)}</dd></dl>
      </div>
    </div>
    <div class="section-head"><h2>Departure airports</h2><span class="muted" style="font-size:12.5px">Click to toggle. Deals from enabled airports are prioritised and used by the flight API scanner.</span></div>
    <div class="panel card-pad">${Object.entries(groups).map(([g, list]) => `<div class="eyebrow" style="margin:4px 0 8px">${g}</div><div class="airports" style="margin-bottom:14px">${list.map((a) => `<button class="ap ${a.enabled ? "on" : ""}" data-ap="${a.iata}" data-on="${a.enabled}"><b>${a.iata}</b>${esc(a.city)}${a.custom ? " ·" : ""}</button>`).join("")}</div>`).join("")}
      <div class="form-grid" style="grid-template-columns:repeat(auto-fill,minmax(140px,1fr));align-items:end">
        <label class="field">IATA code<input type="text" id="ap-iata" maxlength="4" placeholder="e.g. PLQ"></label>
        <label class="field">City<input type="text" id="ap-city" placeholder="Palanga"></label>
        <label class="field">Country (ISO-2)<input type="text" id="ap-cc" maxlength="2" placeholder="LT"></label>
        <button class="btn small" id="ap-add" style="height:34px">Add airport</button></div></div>
    <div class="section-head"><h2>Data sources</h2><span class="muted" style="font-size:12.5px">Only permitted feeds &amp; official APIs. Intervals ≥ 30 min.</span></div>
    <div class="panel" style="overflow-x:auto"><table class="table responsive"><thead><tr><th>Source</th><th>Status</th><th>Last success</th><th>Next scan</th><th>Active / collected</th><th>Interval</th><th>API calls (month)</th><th></th></tr></thead><tbody>
      ${s.providers.map((x) => `<tr><td><div style="font-weight:600">${esc(x.name)}${x.priority ? ' <span class="tag flat" style="height:18px">priority</span>' : ""}</div><div class="muted" style="font-size:12px">${esc(x.notes)}</div>${x.error ? `<div style="color:var(--danger);font-size:12px">${esc(x.error.slice(0, 140))}</div>` : ""}</td>
        <td><span class="status ${x.status}">${esc(x.status.replace("_", " "))}</span></td><td>${ago(x.last_success)}</td><td>${x.enabled ? until(x.next_run) : "disabled"}</td>
        <td class="num">${x.offers_active} / ${x.offers_total}</td>
        <td><select data-int="${x.key}">${[30, 45, 60, 90, 120, 180, 240, 360, 720].map((m) => `<option value="${m}" ${x.interval === m ? "selected" : ""}>${m < 60 ? m + " min" : m / 60 + " h"}</option>`).join("")}</select></td>
        <td class="num">${x.calls_month}${x.est_cost_month ? " · " + eur(x.est_cost_month) : " · free"}</td>
        <td style="white-space:nowrap"><button class="switch ${x.enabled ? "on" : ""}" data-pen="${x.key}" data-on="${x.enabled}" aria-label="Enable source"></button>
          <button class="btn small ghost" data-scan="${x.key}" title="Scan now">${ic("refresh")}</button></td></tr>`).join("")}
    </tbody></table></div>
    <div class="section-head"><h2>Researched but not connected</h2><span class="muted" style="font-size:12.5px">Not scraped – they block automated access or need a commercial agreement</span></div>
    <div class="panel">${s.unavailable.map((u) => `<div class="src-row" style="border-bottom:1px solid var(--line);padding:11px 16px"><span style="font-weight:500">${esc(u.name)}</span><span class="muted" style="text-align:right;max-width:60%">${esc(u.reason)}</span></div>`).join("")}</div>`;
  $("#p-only").onclick = (e) => e.currentTarget.classList.toggle("on");
  $("#p-save").onclick = async () => {
    const n = (id) => ($(id).value === "" ? null : +$(id).value);
    await api("/settings/preferences", { method: "PUT", body: { min_display_score: n("#p-min") ?? 60,
      max_price: { flight: n("#p-mf"), package: n("#p-mp"), cruise: n("#p-mc") }, preferred_destinations: p.preferred_destinations || [],
      only_my_airports: $("#p-only").classList.contains("on") } });
    toast("Preferences saved");
  };
  v.querySelectorAll("[data-ap]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/airports/${b.dataset.ap}?enabled=${b.dataset.on !== "true"}`, { method: "PATCH" }); viewSettings(v);
  }));
  $("#ap-add").onclick = async () => {
    const iata = $("#ap-iata").value.trim(), city = $("#ap-city").value.trim(), cc = $("#ap-cc").value.trim();
    if (!iata || !city || !cc) return toast("IATA code, city and country are required");
    await api("/airports", { method: "POST", body: { iata, city, country: cc } }); toast(`${iata.toUpperCase()} added`); viewSettings(v);
  };
  v.querySelectorAll("[data-int]").forEach((sel) => sel.addEventListener("change", async () => {
    await api(`/providers/${sel.dataset.int}`, { method: "PATCH", body: { interval: +sel.value } }); toast("Interval updated – the worker picks it up within 2 minutes");
  }));
  v.querySelectorAll("[data-pen]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/providers/${b.dataset.pen}`, { method: "PATCH", body: { enabled: b.dataset.on !== "true" } }); viewSettings(v);
  }));
  v.querySelectorAll("[data-scan]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true; toast("Scanning…");
    const r = await api(`/providers/${b.dataset.scan}/scan?wait=true`, { method: "POST" });
    toast(r.ok ? `${r.provider}: ${r.parsed} deals parsed, ${r.new} new` : `${r.provider}: ${r.error}`); viewSettings(v);
  }));
}

/* ------------------------------------------------------------------ notifications */
function setBell(n) { const c = $("#bell-count"); c.hidden = !n; c.textContent = n > 99 ? "99+" : n; }
async function pollNotifications(force = false) {
  try {
    const r = await api("/notifications?limit=15");
    const inapp = r.items.filter((x) => x.channel === "inapp");
    setBell(inapp.filter((x) => !x.read).length);
    const fresh = inapp.filter((x) => x.id > state.lastNotifId);
    if (fresh.length && state.lastNotifId && "Notification" in window && Notification.permission === "granted") {
      fresh.slice(0, 3).forEach((x) => {
        const note = new Notification(x.title, { body: x.body.split("\n").slice(1, 4).join("\n"), tag: "te-" + x.id });
        note.onclick = () => { window.focus(); x.offer_id && openDeal(x.offer_id); };
      });
    }
    if (inapp.length) { state.lastNotifId = Math.max(state.lastNotifId, ...inapp.map((x) => x.id)); store.set("te-last-notif", state.lastNotifId); }
    state.notifs = inapp;
  } catch (e) { if (force) console.warn(e); }
}
function renderNotifPanel() {
  const p = $("#notif-panel");
  const items = state.notifs || [];
  p.innerHTML = `<div class="head"><span>Notifications</span><a href="#/alerts" style="color:var(--accent);font-size:12.5px;font-weight:500">Manage alerts</a></div>
    ${items.length ? items.map((x) => `<div class="notif-item ${x.read ? "" : "unread"}" data-o="${x.offer_id || ""}"><div class="t">${esc(x.title)}</div><div class="m">${esc(x.body.split("\n")[1] || "")} · ${ago(x.created_at)}</div></div>`).join("") : '<div class="empty">No notifications yet.</div>'}`;
  p.querySelectorAll("[data-o]").forEach((el) => el.addEventListener("click", () => { p.hidden = true; el.dataset.o && openDeal(+el.dataset.o); }));
}

/* ------------------------------------------------------------------ router */
function setTitle(t, sub) { $("#page-title").textContent = t; $("#page-sub").textContent = sub || ""; document.title = t === "Overview" ? "HubFare" : `${t} · HubFare`; }
async function route() {
  const id = (location.hash.replace(/^#\/?/, "") || "overview").split("?")[0];
  renderNav(id);
  document.querySelectorAll(".mobile-nav a").forEach((a) =>
    a.classList.toggle("on", a.dataset.nav === id || (a.dataset.nav === "overview" && ["flights", "packages", "cruises"].includes(id))));
  closeDeal();
  $("#sidebar").classList.remove("open");
  const v = $("#view");
  try {
    if (id === "overview") await viewOverview(v);
    else if (id === "flights") await viewCategory(v, "flight");
    else if (id === "packages") await viewCategory(v, "package");
    else if (id === "cruises") await viewCategory(v, "cruise");
    else if (id === "saved") await viewSaved(v);
    else if (id === "alerts") await viewAlerts(v);
    else if (id === "settings") await viewSettings(v);
    else location.hash = "#/overview";
    renderNav(id);
  } catch (e) {
    v.innerHTML = `<div class="notice err">Could not load data: ${esc(e.message)}. Is the API running?</div>`;
  }
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
$("#drawer-backdrop").onclick = closeDeal;
document.addEventListener("keydown", (e) => e.key === "Escape" && closeDeal());
$("#menu-btn").onclick = () => $("#sidebar").classList.toggle("open");
$("#bell").onclick = async (e) => {
  e.stopPropagation();
  const p = $("#notif-panel");
  if (p.hidden) { await pollNotifications(); renderNotifPanel(); p.hidden = false; await api("/notifications/read", { method: "POST" }); setBell(0); }
  else p.hidden = true;
};
document.addEventListener("click", (e) => { if (!e.target.closest(".bell-wrap")) $("#notif-panel").hidden = true; });

(async function boot() {
  try {
    const o = await api("/overview");
    state.counts = Object.fromEntries(Object.entries(o.categories).map(([k, c]) => [k, c.active]));
    renderMonitoring(o.monitoring, o.my_airports);
    setBell(o.unread);
  } catch {}
  try { state.airports = (await api("/airports")).airports; } catch { state.airports = []; }
  await pollNotifications();
  route();
  setInterval(pollNotifications, 60000);
  setInterval(async () => { try { const h = await api("/health"); renderMonitoring(h.monitoring); } catch {} }, 60000);
})();
