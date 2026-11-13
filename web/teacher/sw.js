// Service worker: HANYA meng-cache app shell. Tidak pernah meng-cache API (/api/*, /healthz, origin lain).
const CACHE = "absensi-guru-shell-v3";
const SHELL = [
  "./", "index.html", "app.js", "scanner.js", "styles.css", "config.js", "manifest.webmanifest",
  "shared/api.js", "shared/format.js", "shared/fx.js", "shared/base.css",
  "icons/icon-192.png", "icons/icon-512.png", "icons/maskable-512.png", "icons/apple-touch-icon.png",
  "vendor/qr-scanner/qr-scanner.min.js", "vendor/qr-scanner/qr-scanner-worker.min.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  // Origin lain (API di Render) atau path API: biarkan langsung ke jaringan, jangan disentuh.
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.includes("/api/")) return;
  // Network-first agar deploy baru langsung terpakai; cache hanya cadangan saat offline.
  e.respondWith((async () => {
    try {
      const res = await fetch(req);
      if (res.ok && res.type === "basic") {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return res;
    } catch {
      const hit = await caches.match(req, { ignoreSearch: true });
      if (hit) return hit;
      if (req.mode === "navigate") return (await caches.match("index.html")) || Response.error();
      return Response.error();
    }
  })());
});
