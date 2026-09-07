/*
 * オフラインでも起動できるようにするための Service Worker。
 * 方針は他のアプリと同じ stale-while-revalidate（まずキャッシュを返し、裏で最新版を取りに行く）。
 *
 * 注意：中継サーバーへの通信（/send・/inbox・/ack）は別のドメインへの通信なので、
 * ここでは一切扱わない（下の origin の判定で素通りする）。暗号文をキャッシュに残さないため。
 */
var CACHE = "messenger-v1";
var ASSETS = [
  "./", "./index.html", "./crypto.js", "./store.js", "./net.js",
  "../shared/native.js", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png", "./icon-180.png"
];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(ASSETS); }).then(function () {
    return self.skipWaiting();
  }));
});

self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; })
      .map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== self.location.origin) return;
  e.respondWith(caches.match(req).then(function (cached) {
    var network = fetch(req).then(function (res) {
      if (res && res.ok) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () { return cached; });
    return cached || network;
  }));
});
