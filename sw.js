/* Deal Radar service worker: app shell = stale-while-revalidate, data = network-first with
   offline fallback to the last cached copy. Bump VERSION when shell files change. */
const VERSION = "dr-2026-11-16b";
const SHELL = [
  "./", "./index.html", "./styles.css", "./app.js", "./manifest.json",
  "./fonts/archivo-wdth.woff2", "./icons/icon-192.png", "./icons/icon-512.png",
  "./icons/apple-touch-icon.png", "./icons/favicon-32.png",
];
const CHART = "https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.min.js";

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const cache = await caches.open(VERSION);
    await cache.addAll(SHELL);
    try { await cache.add(new Request(CHART, { mode: "cors" })); } catch { /* chart is optional offline */ }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== VERSION) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === location.origin && url.pathname.includes("/data/") && url.pathname.endsWith(".json")) {
    e.respondWith(networkFirst(req));
    return;
  }
  if (url.origin === location.origin || req.url === CHART) {
    e.respondWith(staleWhileRevalidate(req, e));
  }
});

async function networkFirst(req) {
  const cache = await caches.open(VERSION);
  const key = new URL(req.url).pathname;  // ignore query strings / cache-busters
  try {
    const res = await fetch(req, { cache: "no-store" });
    if (res.ok) await cache.put(key, res.clone());
    return res;
  } catch {
    const hit = await cache.match(key);
    return hit || new Response(JSON.stringify({ error: "offline" }), { status: 503, headers: { "Content-Type": "application/json" } });
  }
}

async function staleWhileRevalidate(req, event) {
  const cache = await caches.open(VERSION);
  const hit = await cache.match(req, { ignoreSearch: true });
  const update = fetch(req).then((res) => {
    if (res.ok) cache.put(req, res.clone());
    return res;
  }).catch(() => null);
  if (hit) { event.waitUntil(update); return hit; }
  const res = await update;
  if (res) return res;
  if (req.mode === "navigate") return (await cache.match("./index.html")) || Response.error();
  return Response.error();
}
