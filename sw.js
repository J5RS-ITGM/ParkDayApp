// Park Day — offline-first service worker
const CACHE = "park-day-v23";
const ASSETS = ["./", "./index.html", "./manifest.json", "./icon.svg", "./icon-512.png", "./apple-touch-icon.png"];

// ---- Web Push: ride wait alerts ----
self.addEventListener("push", e => {
  let d = {};
  try { d = e.data.json(); } catch (err) {}
  e.waitUntil(self.registration.showNotification(d.title || "Park Day", {
    body: d.body || "",
    icon: "icon-512.png",
    badge: "icon-512.png",
    data: { url: d.url || "./" },
    tag: "parkday-wait",
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) { if ("focus" in c) return c.focus(); }
    return clients.openWindow(e.notification.data?.url || "./");
  }));
});

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  // Family-sync API: never cache, network only (app handles offline itself)
  if (url.pathname.includes("/api/")) return;
  // Live wait times: network-first, fall back silently
  if (url.hostname === "api.themeparks.wiki" || url.hostname === "api.open-meteo.com") {
    e.respondWith(fetch(e.request).catch(() => new Response("{}", { headers: { "Content-Type": "application/json" } })));
    return;
  }
  // App shell: cache-first so it works with zero signal in the parks
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
      if (e.request.method === "GET" && res.ok && url.origin === location.origin) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return res;
    }))
  );
});
