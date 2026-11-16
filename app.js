/* Deal Radar PWA — vanilla JS, no build step. Data: ./data/latest.json + ./data/history.json */
"use strict";

const STALE_HOURS = 30;
const CHART_SRC = "https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.min.js";
const CHART_SRI = "sha384-Emf5ZVIUiarAdhkgtqK+5/Z5qIvM6QoVrS+qAVtfyZVuD5lIHrac0me485+Antp0";
const CAT_NAME = { energy: "Energy", snack: "Protein snack", rtd: "RTD shake" };
const TIER_RANK = { STEAL: 0, HOT: 1, SOLID: 2, SKIP: 3, UNRATED: 4 };
const TIER_EMOJI = { STEAL: "🚨", HOT: "🔥", SOLID: "✅", SKIP: "❌", UNRATED: "❔" };
const $ = (sel) => document.querySelector(sel);

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};

const state = {
  latest: null, history: {}, cat: store.get("dr.cat", "all"), sort: store.get("dr.sort", "tier"),
  starredOnly: false, casesOnly: store.get("dr.cases", false), localOnly: store.get("dr.local", false),
  filter: store.get("dr.filter", "all"), starred: new Set(store.get("dr.starred", [])), open: new Set(),
  histProduct: null, histRange: store.get("dr.range", "30"), chart: null,
};

// ------------------------------------------------------------------ helpers
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function safeUrl(u) {
  try { const x = new URL(u); return x.protocol === "https:" || x.protocol === "http:" ? x.href : "#"; }
  catch { return "#"; }
}
const money = (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`);
const unitWord = (p) => (p.unit_label || "unit").split(" ")[0];
function tierOf(o) { return o.unverified ? "UNVERIFIED" : o.tier; }
function tierText(o) { return o.unverified ? "⚠️ UNVERIFIED" : o.tier; }

function hoursSince(iso) { return (Date.now() - new Date(iso).getTime()) / 36e5; }
function relTime(iso) {
  const d = new Date(iso), h = hoursSince(iso);
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (h < 20 && new Date().toDateString() === d.toDateString()) return `today ${time}`;
  return `${d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })} ${time}`;
}
function endsText(ends) {
  if (!ends) return "";
  const end = new Date(`${ends}T23:59:59`);
  const h = (end - Date.now()) / 36e5;
  if (h < 0) return "ended";
  if (h < 48) return `ends in ${Math.max(1, Math.round(h))}h`;
  return `ends ${end.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })}`;
}
function chips(o) {
  const c = [];
  if (o.is_case) c.push(`📦 case of ${o.pack_count}`);
  if (o.in_store_only) c.push("🏬 in-store only");
  if (o.membership_required) c.push("🔒 membership");
  if (Number(o.limit_per_customer)) c.push(`limit ${o.limit_per_customer}`);
  if (Number(o.min_qty) > 1) c.push(`min ${o.min_qty}`);
  if (Number(o.subscribe_save_pct)) c.push(`subscribe ${o.subscribe_save_pct}%`);
  return c;
}
function secondary(p, o) {
  if (p.category === "energy") return o.price_per_oz != null ? { label: "per oz", value: money(o.price_per_oz) } : null;
  return o.price_per_10g_protein != null ? { label: "per 10 g protein", value: money(o.price_per_10g_protein), badge: o.protein_value_badge } : null;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2200);
}
async function copyCode(code) {
  try { await navigator.clipboard.writeText(code); toast(`Code ${code} copied`); }
  catch { toast(`Code: ${code}`); }
}
const productById = (id) => state.latest?.products.find((p) => p.id === id);

// ------------------------------------------------------------------ data
async function getJSON(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

async function load() {
  try {
    const [latest, history] = await Promise.all([
      getJSON("./data/latest.json"),
      getJSON("./data/history.json").catch(() => ({})),
    ]);
    state.latest = latest; state.history = history || {};
    render();
  } catch (e) {
    banner(`Couldn't load deal data (${e.message}). Check your connection, then retry.`, true, true);
    $("#updated").textContent = "Not loaded";
    $("#heroes").innerHTML = emptyTag("No data yet", "Deals appear here after the first scan.");
  }
}

function banner(text, isError = false, retry = false) {
  const b = $("#banner");
  b.hidden = false;
  b.className = `banner${isError ? " error" : ""}`;
  b.innerHTML = esc(text) + (retry ? ' <button class="toggle" type="button" id="retry">Retry</button>' : "");
  if (retry) $("#retry").addEventListener("click", () => { b.hidden = true; load(); });
}

// ------------------------------------------------------------------ render
function render() {
  const L = state.latest;
  const products = Array.isArray(L?.products) ? L.products : [];
  $("#updated").textContent = L?.generated_at ? `Updated ${relTime(L.generated_at)}` : "No scan yet";
  const age = L?.generated_at ? hoursSince(L.generated_at) : Infinity;
  const why = L?.stale_reason ? ` Last run: ${L.stale_reason}` : "";
  if (!L?.generated_at) {
    banner(`No scan yet. Deals appear after the first daily scan.${why}`);
  } else if (L.stale || age > STALE_HOURS) {
    banner(`⚠️ Data is ${Math.round(age)} hours old.${why || " The next scan will refresh it."}`);
  } else {
    $("#banner").hidden = true;
  }
  renderHeroes(state.casesOnly || state.localOnly ? caseHeroes(products) : (L?.heroes || {}), products);
  renderDeals(products);
  renderTabs();
  renderRows(products);
  renderBoard(L?.protein_value_board || []);
  renderHistoryPicker(products);
  renderChart();
  const c = L?.counts;
  $("#foot-meta").textContent = c
    ? `${c.products_with_offers} of ${products.length} products have sourced offers. ${c.hot_plus} HOT or better today. Run: ${L.run_mode}, ${L.status}.`
    : "";
}

function emptyTag(title, text) {
  return `<article class="shelf-tag empty"><div class="tag-name">${esc(title)}</div><p>${esc(text)}</p></article>`;
}

function renderHeroes(heroes, products) {
  const html = ["energy", "snack", "rtd"].map((cat) => {
    const o = heroes[cat];
    if (!o) return emptyTag(`${CAT_NAME[cat]}: nothing yet`, state.casesOnly || state.localOnly ? "Nothing matches your filters in the last scan. Turn a filter off to see more." : "No sourced offer passed validation in the last scan.");
    const p = productById(o.product_id) || { unit_label: "unit", category: cat, display_name: o.product_id };
    const sec = secondary(p, o);
    const ch = chips(o);
    const ends = endsText(o.ends);
    const units = o.units_in_cart > 1 ? `${o.units_in_cart} ${esc(unitWord(p))}s` : `1 ${esc(unitWord(p))}`;
    const rec = o.is_record ? '<span class="record">🏆 New all-time low</span>' : "";
    const vsRef = p.category !== "energy" && o.pct_vs_ref != null ? ` (${Math.round(100 - o.pct_vs_ref)}% under usual price)` : "";
    return `<article class="shelf-tag t-${esc(o.tier)}" aria-label="${esc(CAT_NAME[cat])} top deal">
      <div class="tag-top"><span class="tag-tier">${esc(tierText(o))}</span><span class="tag-cat">${esc(CAT_NAME[cat])}</span></div>
      <div class="tag-name">${esc(p.display_name)}</div>
      ${o.flavor ? `<div class="tag-flavor">${esc(o.flavor)}</div>` : ""}
      <div class="tag-price"><span class="big">${money(o.unit_price)}</span><span class="per">/${esc(unitWord(p))}</span>
        ${sec ? `<span class="unit-box">${esc(sec.label)}<b>${sec.value} ${esc(sec.badge || "")}</b></span>` : ""}</div>
      ${rec}
      <div class="tag-where">${esc(o.retailer_name)}<span class="total"> — ${money(o.effective_pack_total)} for ${units}${esc(vsRef)}</span></div>
      ${ch.length ? `<ul class="chips">${ch.map((c) => `<li class="chip">${esc(c)}</li>`).join("")}</ul>` : ""}
      ${ends ? `<div class="tag-ends">${esc(ends)}</div>` : ""}
      <div class="tag-actions">
        <a class="btn" href="${esc(safeUrl(o.source_url))}" target="_blank" rel="noopener noreferrer">${esc(openLabel(o))}</a>
        ${retailerOf(o).physical ? `<a class="btn ghost" href="${esc(mapsUrl(retailerOf(o).name))}" target="_blank" rel="noopener noreferrer">📍 Nearest</a>` : ""}
        ${o.code ? `<button class="btn ghost" type="button" data-code="${esc(o.code)}">Copy code ${esc(o.code)}</button>` : ""}
      </div>
    </article>`;
  });
  $("#heroes").innerHTML = html.join("");
  $("#hero-dots").innerHTML = "<span class=\"on\"></span><span></span><span></span>";
}

// ------------------------------------------------------------------ deal feed (the easy view)
function retailerOf(o) {
  const r = state.latest?.retailers?.[o.retailer_key];
  return r || { name: o.retailer_name || "Store", physical: false, membership: !!o.membership_required, stock_search: "" };
}
function hostOf(u) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return "source"; } }
function openLabel(o) {
  return o.source_kind === "retailer" ? `Open at ${retailerOf(o).name}` : "Open deal post";
}
function mapsUrl(name) { return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(name + " near me")}`; }
function stockUrl(p, o) {
  const r = retailerOf(o);
  if (!r.physical || !r.stock_search) return null;
  if (o.source_kind === "retailer" && o.source_url) return o.source_url;  // product page: pick your store to see stock
  return r.stock_search.replace("{q}", encodeURIComponent(p.display_name));
}
function whereText(o) {
  const r = retailerOf(o);
  const at = o.local_store ? ` (${o.local_store})` : " near you";
  if (o.fulfillment === "pickup") return `📍 Order online, pick up at ${r.name}${at}`;
  if (o.fulfillment === "in_store") {
    if (r.name === "Costco") return `🏬 In store at Costco${at} (warehouse stock isn't listed online)`;
    return `🏬 In store at ${r.name}${at}`;
  }
  return "🚚 Ships to you (online only)";
}
const PROMO_BADGE = { bogo_50: "🎁 BOGO 50% (add 2)", bogo_free: "🎁 BOGO free (add 2)", pct_off: "🏷️ Sale", fixed_unit_price: "🏷️ Promo price", multi_buy: "🏷️ Multi-buy" };
function fulfillBadge(o) {
  return o.fulfillment === "pickup" ? '<span class="badge local">📍 Local pickup</span>'
    : o.fulfillment === "in_store" ? '<span class="badge local">🏬 In store</span>'
    : '<span class="badge">🚚 Ships</span>';
}
function cmpRank(cat, a, b) { return cmpArr(offerRank(cat, a), offerRank(cat, b)); }
function bestDealFor(p) {
  const pool = (p.offers || []).filter(passesView);
  pool.sort((a, b) => cmpArr(offerRank(p.category, a), offerRank(p.category, b)));
  return pool[0] || null;
}

function dealCard(p, o) {
  const r = retailerOf(o);
  const unit = unitWord(p);
  const ends = endsText(o.ends);
  const sec = secondary(p, o);
  const save = o.pct_vs_ref != null && o.pct_vs_ref < 100 ? `${Math.round(100 - o.pct_vs_ref)}% under usual` : "";
  const notes = [];
  if (o.membership_required) notes.push(`🔒 ${r.name} membership`);
  if (Number(o.limit_per_customer)) notes.push(`Limit ${o.limit_per_customer}`);
  if (Number(o.min_qty) > 1) notes.push(`Buy ${o.min_qty} to get this price`);
  if (Number(o.subscribe_save_pct)) notes.push(`Price includes Subscribe/Auto-Delivery ${o.subscribe_save_pct}%`);
  const stock = stockUrl(p, o);
  const units = `${o.units_in_cart} ${unit}${o.units_in_cart > 1 ? "s" : ""}`;
  return `<li class="deal t-${esc(o.tier)}">
    <a class="deal-main" href="${esc(safeUrl(o.source_url))}" target="_blank" rel="noopener noreferrer">
      <span class="deal-tags">${["SKIP", "UNRATED"].includes(o.tier) ? "" : `<span class="tier t-${esc(o.tier)}">${esc(TIER_EMOJI[o.tier] || "")} ${esc(o.tier)}</span>`}${fulfillBadge(o)}${o.is_case ? `<span class="badge">📦 Case of ${esc(o.pack_count)}</span>` : ""}${PROMO_BADGE[o.promo_type] ? `<span class="badge promo">${PROMO_BADGE[o.promo_type]}</span>` : ""}${o.is_record ? '<span class="badge">🏆 Record low</span>' : ""}${ends ? `<span class="badge ends">${esc(ends)}</span>` : ""}</span>
      <span class="deal-name">${esc(p.display_name)}</span>
      ${o.flavor ? `<span class="deal-flavor">${esc(o.flavor)}</span>` : ""}
      <span class="deal-price"><b>${money(o.unit_price)}</b><span class="per">/${esc(unit)}</span></span>
      <span class="deal-line">${money(o.effective_pack_total)} for ${esc(units)} at <strong>${esc(r.name)}</strong>${save ? `, ${esc(save)}` : ""}</span>
      ${sec ? `<span class="deal-line">${esc(sec.value)} ${esc(sec.label)} ${esc(sec.badge || "")}</span>` : ""}
      <span class="deal-line">${esc(whereText(o))}</span>
      ${o.stock_note ? `<span class="deal-stock${GONE_RE.test(o.stock_note) ? " oos" : ""}">${GONE_RE.test(o.stock_note) ? "⚠️" : "✅"} ${esc(o.stock_note)}</span>` : ""}
      ${notes.length ? `<span class="deal-notes">${notes.map((n) => `<span>${esc(n)}</span>`).join("")}</span>` : ""}
      <span class="deal-open">${esc(openLabel(o))}</span>
    </a>
    ${(r.physical || stock || o.code) ? `<div class="deal-actions">
      ${r.physical ? `<a class="act" href="${esc(mapsUrl(r.name))}" target="_blank" rel="noopener noreferrer">📍 Nearest ${esc(r.name)}</a>` : ""}
      ${stock ? `<a class="act" href="${esc(safeUrl(stock))}" target="_blank" rel="noopener noreferrer">Check stock at my store</a>` : ""}
      ${o.code ? `<button class="act" type="button" data-code="${esc(o.code)}">Copy code ${esc(o.code)}</button>` : ""}
    </div>` : ""}
  </li>`;
}

function regularCard(p, o) {
  const unit = unitWord(p);
  const usual = p.ref_unit_price != null ? `usual ${money(p.ref_unit_price)}/${esc(unit)}` : "";
  if (!o) return `<li class="deal quiet"><div class="deal-main"><span class="deal-name">${esc(p.display_name)}</span><span class="deal-line">No sourced offer in the last scan${usual ? `, ${usual}` : ""}.</span></div></li>`;
  return `<li class="deal quiet"><a class="deal-main" href="${esc(safeUrl(o.source_url))}" target="_blank" rel="noopener noreferrer">
      <span class="deal-name">${esc(p.display_name)}</span>
      <span class="deal-price"><b>${money(o.unit_price)}</b><span class="per">/${esc(unit)}</span></span>
      <span class="deal-line">Best today at ${esc(retailerOf(o).name)}${usual ? `, ${usual}` : ""}. Not a deal yet.</span>
    </a></li>`;
}

function renderDeals(products) {
  document.querySelectorAll(".filters [data-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === state.filter)));
  const list = products.filter((p) => state.filter === "all" || p.category === state.filter).map((p) => ({ p, o: bestDealFor(p) }));
  const deals = list.filter((x) => x.o && ["STEAL", "HOT", "SOLID"].includes(x.o.tier));
  deals.sort((a, b) => (TIER_RANK[a.o.tier] - TIER_RANK[b.o.tier]) || ((isLocal(a.o) ? 0 : 1) - (isLocal(b.o) ? 0 : 1))
    || ((a.o.pct_vs_ref ?? 999) - (b.o.pct_vs_ref ?? 999)) || (a.o.unit_price - b.o.unit_price));
  const rest = list.filter((x) => !deals.includes(x));
  // every live promo (BOGO, sale), even when it doesn't reach a tier; in-stock and local first
  const shown = new Set(deals.map((x) => x.o));
  const promos = products.filter((p) => state.filter === "all" || p.category === state.filter)
    .flatMap((p) => (p.offers || []).filter((o) => PROMO_BADGE[o.promo_type] && passesView(o) && !shown.has(o)).map((o) => ({ p, o })));
  promos.sort((a, b) => cmpArr(offerRank(a.p.category, a.o), offerRank(b.p.category, b.o)));
  $("#promos").hidden = promos.length === 0;
  $("#promo-list").innerHTML = promos.map(({ p, o }) => dealCard(p, o)).join("");
  const word = `${state.localOnly ? "local " : ""}${state.casesOnly ? "case " : ""}deal`;
  $("#deal-count").textContent = products.length ? `${deals.length} ${word}${deals.length === 1 ? "" : "s"}` : "";
  $("#deal-list").innerHTML = deals.length ? deals.map(({ p, o }) => dealCard(p, o)).join("")
    : `<li class="empty-row">${products.length ? `No ${word}s here in the last scan.${state.casesOnly || state.localOnly ? " Turn a filter off to see more." : ""}` : "Deals appear after the first scan."}</li>`;
  $("#regular-summary").textContent = `No deal today: ${rest.length} product${rest.length === 1 ? "" : "s"} at regular price`;
  $("#regular").hidden = rest.length === 0;
  $("#regular-list").innerHTML = rest.map(({ p, o }) => regularCard(p, o)).join("");
}

function renderTabs() {
  document.querySelectorAll(".tabs [role=tab]").forEach((b) => {
    const on = b.dataset.cat === state.cat;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    if (on) $("#rows-panel").setAttribute("aria-labelledby", b.id);
  });
  $("#sort").value = state.sort;
  $("#starred").setAttribute("aria-pressed", String(state.starredOnly));
  $("#cases").setAttribute("aria-pressed", String(state.casesOnly));
  $("#local").setAttribute("aria-pressed", String(state.localOnly));
}

function isEasy(o) { return !o.in_store_only && !o.membership_required && !(Number(o.min_qty) > 1); }
function passes(o) { return (state.sort !== "easy" || isEasy(o)) && (!state.casesOnly || o.is_case); }

function isLocal(o) { return o.fulfillment === "in_store" || o.fulfillment === "pickup"; }
const GONE_RE = /out of stock|unavailable|discontinued|sold out/i;
function offerRank(cat, o) {
  const g = GONE_RE.test(o.stock_note || "") ? 1 : 0;  // store check says you can't get it: last
  const t = TIER_RANK[o.tier] ?? 4;
  const l = isLocal(o) ? 0 : 1;  // local pickup / in store first within a tier
  return cat === "energy" ? [g, t, l, o.unit_price ?? 9e9, 0] : [g, t, l, o.pct_vs_ref ?? 999, o.price_per_10g_protein ?? 9e9];
}
function cmpArr(x, y) { for (let i = 0; i < x.length; i++) { if (x[i] !== y[i]) return x[i] - y[i]; } return 0; }
function passesView(o) { return !o.unverified && (!state.casesOnly || o.is_case) && (!state.localOnly || isLocal(o)); }

function caseHeroes(products) {
  const out = {};
  for (const cat of ["energy", "snack", "rtd"]) {
    const pool = products.filter((p) => p.category === cat).flatMap((p) => (p.offers || []).filter(passesView));
    pool.sort((a, b) => cmpArr(offerRank(cat, a), offerRank(cat, b)));
    out[cat] = pool[0] || null;
  }
  return out;
}

function bestFor(p) {
  const offers = (p.offers || []).filter(passes);
  const verified = offers.filter((o) => !o.unverified);
  return verified[0] || offers[0] || null;
}

function sortKey(p, best) {
  const none = [9, 9e9];
  if (!best) return none;
  const t = best.unverified ? 5 : TIER_RANK[best.tier] ?? 4;
  switch (state.sort) {
    case "unit": return [best.unit_price ?? 9e9, 0];
    case "protein": return [best.price_per_10g_protein ?? 9e9, best.unit_price];
    case "pct": return [best.pct_vs_ref ?? 9e9, best.unit_price];
    case "easy":
    case "tier":
    default:
      return [t, p.category === "energy" ? best.unit_price : (best.pct_vs_ref ?? 999)];
  }
}

function renderRows(products) {
  let list = products.filter((p) => state.cat === "all" || p.category === state.cat);
  if (state.starredOnly) list = list.filter((p) => state.starred.has(p.id));
  const withBest = list.map((p) => ({ p, best: bestFor(p) }));
  withBest.sort((a, b) => {
    const ka = sortKey(a.p, a.best), kb = sortKey(b.p, b.best);
    return ka[0] - kb[0] || ka[1] - kb[1] || a.p.display_name.localeCompare(b.p.display_name);
  });
  if (!withBest.length) {
    $("#rows").innerHTML = `<li class="empty-row">${state.starredOnly ? "No starred products in this category. Tap ☆ on a product to star it." : "No products in this category."}</li>`;
    return;
  }
  $("#rows").innerHTML = withBest.map(({ p, best }) => rowHtml(p, best)).join("");
}

function rowHtml(p, best) {
  const id = `d-${p.id}`;
  const open = state.open.has(p.id);
  const starred = state.starred.has(p.id);
  const atl = p.all_time_low;
  const record = atl ? `Record ${money(atl.unit_price)} at ${esc(atl.retailer)}, ${esc(atl.date)}` : "No record yet";
  let price = `<span class="row-price"><span class="per">no sourced offer</span></span>`;
  let meta = `<span class="row-meta">${p.ref_unit_price != null ? `Usual price ${money(p.ref_unit_price)}/${esc(unitWord(p))}` : "Usual price not set yet"}</span>`;
  let tier = "";
  if (best) {
    const sec = secondary(p, best);
    price = `<span class="row-price"><b>${money(best.unit_price)}</b><span class="per">/${esc(unitWord(p))}</span></span>`;
    meta = `<span class="row-meta">${esc(best.retailer_name)}${sec ? `, ${sec.value} ${esc(sec.label)} ${esc(sec.badge || "")}` : ""}${best.is_record ? " 🏆" : ""}</span>`;
    tier = `<span class="tier t-${esc(tierOf(best))}">${esc(tierText(best))}</span>`;
  }
  const easyNote = !best && (p.offers || []).length
    ? (state.casesOnly ? " (no case offer today; single-unit offers only)" : state.sort === "easy" ? " (only in-store, membership or multi-buy offers today)" : "")
    : "";
  return `<li class="row">
    <button class="row-main" type="button" aria-expanded="${open}" aria-controls="${id}" data-toggle="${esc(p.id)}">
      <span class="row-name">${esc(p.display_name)}</span>${price}
      ${meta}<span class="row-side">${tier}</span>
      <span class="row-record">${record}${esc(easyNote)}</span>
    </button>
    <button class="star" type="button" aria-pressed="${starred}" aria-label="${starred ? "Unstar" : "Star"} ${esc(p.display_name)}" data-star="${esc(p.id)}">${starred ? "★" : "☆"}</button>
    <div class="row-detail" id="${id}" ${open ? "" : "hidden"}>${open ? detailHtml(p) : ""}</div>
  </li>`;
}

function detailHtml(p) {
  const offers = p.offers || [];
  if (!offers.length) {
    return `<p class="sub">No sourced offer in the last scan.${p.ref_unit_price != null ? ` Usual price ${money(p.ref_unit_price)}/${esc(unitWord(p))}.` : ""}${p.protein_g ? ` ${p.protein_g} g protein per ${esc(unitWord(p))}.` : ""}</p>`;
  }
  const items = offers.map((o) => {
    const sec = secondary(p, o);
    const ch = chips(o);
    const ends = endsText(o.ends);
    return `<div class="offer">
      <span>${esc(o.retailer_name)} <span class="tier t-${esc(tierOf(o))}">${esc(tierText(o))}</span></span>
      <span class="o-price">${money(o.unit_price)}/${esc(unitWord(p))}</span>
      <span class="o-meta">${money(o.effective_pack_total)} for ${o.units_in_cart} ${esc(unitWord(p))}${o.units_in_cart > 1 ? "s" : ""}${sec ? `, ${sec.value} ${esc(sec.label)}` : ""}${o.pct_vs_ref != null ? `, ${Math.round(o.pct_vs_ref)}% of usual` : ""}${ends ? `, ${esc(ends)}` : ""}${o.evidence_date ? `. Seen ${esc(o.evidence_date)}` : ""}</span>
      ${ch.length ? `<ul class="chips">${ch.map((c) => `<li class="chip">${esc(c)}</li>`).join("")}</ul>` : ""}
      ${o.unverified ? '<span class="o-meta unverified-note">⚠️ Too good to confirm with a second source. Check before you go.</span>' : ""}
      <div class="o-actions">
        <a class="btn" href="${esc(safeUrl(o.source_url))}" target="_blank" rel="noopener noreferrer">Buy</a>
        ${o.code ? `<button class="btn ghost" type="button" data-code="${esc(o.code)}">Copy code ${esc(o.code)}</button>` : ""}
      </div>
    </div>`;
  }).join("");
  const best = offers.find((o) => o.playbook);
  const playbook = best?.playbook?.length
    ? `<h3 class="visually-hidden">How to get this price</h3><ol class="playbook">${best.playbook.map((s) => `<li>${esc(s)}</li>`).join("")}</ol>`
    : "";
  return items + playbook;
}

function renderBoard(rows) {
  if (!rows.length) {
    $("#board").innerHTML = `<li class="empty-row">Appears once snacks and shakes have sourced offers.</li>`;
    return;
  }
  const max = Math.max(...rows.map((r) => r.price_per_10g_protein));
  $("#board").innerHTML = rows.map((r) => `<li>
      <span class="b-name">${esc(r.display_name)}</span>
      <span class="b-val">${money(r.price_per_10g_protein)} ${esc(r.protein_value_badge || "")}</span>
      <span class="bar" aria-hidden="true"><span style="width:${Math.max(4, (r.price_per_10g_protein / max) * 100).toFixed(1)}%"></span></span>
      <span class="b-meta">${money(r.unit_price)} at ${esc(r.retailer_name)}, <span class="tier t-${esc(r.tier)}">${esc(r.tier)}</span></span>
    </li>`).join("");
}

// ------------------------------------------------------------------ history chart
function renderHistoryPicker(products) {
  const sel = $("#hist-product");
  if (!products.length) { sel.innerHTML = ""; return; }
  const withHist = products.filter((p) => (state.history[p.id] || []).length);
  const pool = withHist.length ? withHist : products;
  if (!state.histProduct || !pool.some((p) => p.id === state.histProduct)) {
    const starred = pool.find((p) => state.starred.has(p.id));
    state.histProduct = (starred || pool.find((p) => p.id === state.latest?.heroes?.energy?.product_id) || pool[0]).id;
  }
  sel.innerHTML = pool.map((p) => `<option value="${esc(p.id)}">${esc(p.display_name)}</option>`).join("");
  sel.value = state.histProduct;
  document.querySelectorAll(".seg [data-range]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.range === state.histRange)));
}

function renderChart() {
  const note = $("#hist-note");
  const p = productById(state.histProduct);
  if (!p) { note.textContent = ""; return; }
  let rows = state.history[p.id] || [];
  if (state.histRange !== "all") {
    const cutoff = new Date(Date.now() - Number(state.histRange) * 864e5).toISOString().slice(0, 10);
    rows = rows.filter((r) => r[0] >= cutoff);
  }
  const unit = unitWord(p);
  if (rows.length < 2) note.textContent = "History builds up with each daily scan.";
  else note.textContent = `${rows.length} days. Dashed line is the all-time low.`;
  if (typeof window.Chart === "undefined") {
    if (chartLoad.failed) note.textContent = "Chart unavailable offline. " + note.textContent;
    return;
  }
  const css = getComputedStyle(document.documentElement);
  const color = (v) => css.getPropertyValue(v).trim();
  const record = p.all_time_low?.unit_price;
  const data = {
    labels: rows.map((r) => r[0]),
    datasets: [
      { label: `Best $/${unit}`, data: rows.map((r) => r[1]), borderColor: color("--text"), backgroundColor: color("--text"),
        pointRadius: rows.length > 40 ? 0 : 3, tension: 0, borderWidth: 2 },
      ...(record != null ? [{ label: "All-time low", data: rows.map(() => record), borderColor: color("--hot"),
        borderDash: [6, 5], pointRadius: 0, borderWidth: 1.5 }] : []),
    ],
  };
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const options = {
    responsive: true, maintainAspectRatio: false, animation: reduce ? false : { duration: 250 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: color("--muted"), boxWidth: 14 } },
      tooltip: { callbacks: { label: (ctx) => {
        const r = rows[ctx.dataIndex];
        return ctx.datasetIndex === 0 ? ` $${Number(ctx.parsed.y).toFixed(2)}/${unit} ${r && r[3] ? "at " + r[3] : ""}` : ` record $${Number(ctx.parsed.y).toFixed(2)}`;
      } } },
    },
    scales: {
      x: { ticks: { color: color("--muted"), maxTicksLimit: 6 }, grid: { color: color("--rail") } },
      y: { ticks: { color: color("--muted"), callback: (v) => `$${Number(v).toFixed(2)}` }, grid: { color: color("--rail") } },
    },
  };
  $("#chart").setAttribute("aria-label", `Daily best price for ${p.display_name}, ${rows.length} days`);
  if (state.chart) { state.chart.data = data; state.chart.options = options; state.chart.update(); }
  else state.chart = new window.Chart($("#chart"), { type: "line", data, options });
}

// Chart.js (~210 KB) loads only when the history section approaches the viewport.
const chartLoad = { started: false, failed: false };
function loadChartLib() {
  if (chartLoad.started) return;
  chartLoad.started = true;
  const s = document.createElement("script");
  s.src = CHART_SRC; s.integrity = CHART_SRI; s.crossOrigin = "anonymous"; s.async = true;
  s.onload = () => renderChart();
  s.onerror = () => { chartLoad.failed = true; renderChart(); };
  document.head.appendChild(s);
}
if ("IntersectionObserver" in window) {
  const io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { loadChartLib(); io.disconnect(); }
  }, { rootMargin: "400px" });
  io.observe(document.getElementById("history"));
} else { loadChartLib(); }

document.getElementById("more")?.addEventListener("toggle", (e) => { if (e.target.open) loadChartLib(); });

// ------------------------------------------------------------------ events
function bind() {
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-code],[data-toggle],[data-star],[data-cat],[data-range],[data-filter]");
    if (!t) return;
    if (t.dataset.filter) {
      state.filter = t.dataset.filter; store.set("dr.filter", state.filter);
      renderDeals(state.latest?.products || []);
      return;
    }
    if (t.dataset.code) { copyCode(t.dataset.code); return; }
    if (t.dataset.star) {
      const id = t.dataset.star;
      state.starred.has(id) ? state.starred.delete(id) : state.starred.add(id);
      store.set("dr.starred", [...state.starred]);
      renderRows(state.latest?.products || []);
      return;
    }
    if (t.dataset.toggle) {
      const id = t.dataset.toggle;
      state.open.has(id) ? state.open.delete(id) : state.open.add(id);
      const li = t.closest(".row");
      const p = productById(id);
      const detail = li.querySelector(".row-detail");
      const open = state.open.has(id);
      t.setAttribute("aria-expanded", String(open));
      detail.hidden = !open;
      detail.innerHTML = open ? detailHtml(p) : "";
      return;
    }
    if (t.dataset.cat) {
      state.cat = t.dataset.cat; store.set("dr.cat", state.cat);
      renderTabs(); renderRows(state.latest?.products || []);
      return;
    }
    if (t.dataset.range) {
      state.histRange = t.dataset.range; store.set("dr.range", state.histRange);
      renderHistoryPicker(state.latest?.products || []); renderChart();
    }
  });
  $(".tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const tabs = [...document.querySelectorAll(".tabs [role=tab]")];
    const i = tabs.findIndex((b) => b.dataset.cat === state.cat);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    next.focus(); next.click();
  });
  $("#sort").addEventListener("change", (e) => {
    state.sort = e.target.value; store.set("dr.sort", state.sort);
    renderRows(state.latest?.products || []);
  });
  $("#local").addEventListener("click", () => {
    state.localOnly = !state.localOnly; store.set("dr.local", state.localOnly);
    render();
  });
  $("#cases").addEventListener("click", () => {
    state.casesOnly = !state.casesOnly; store.set("dr.cases", state.casesOnly);
    render();
  });
  $("#starred").addEventListener("click", () => {
    state.starredOnly = !state.starredOnly;
    renderTabs(); renderRows(state.latest?.products || []);
  });
  $("#hist-product").addEventListener("change", (e) => { state.histProduct = e.target.value; renderChart(); });
  const heroes = $("#heroes");
  heroes.addEventListener("scroll", () => {
    const i = Math.round(heroes.scrollLeft / (heroes.scrollWidth / 3));
    [...$("#hero-dots").children].forEach((d, k) => d.classList.toggle("on", k === i));
  }, { passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.latest?.generated_at && hoursSince(state.latest.generated_at) > 1) load();
  });
}

if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost")) {
  // a new version took over (after a deploy): reload once so the whole app is the new version
  const hadController = !!navigator.serviceWorker.controller;
  let reloaded = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadController || reloaded) return;
    reloaded = true;
    location.reload();
  });
  window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch(() => {}));
}
bind();
load();
