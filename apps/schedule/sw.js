/* オフラインでも予定を確認できるよう、画面と共通部品を端末内に控える。 */
var CACHE = "schedule-v3";
var ASSETS = [
  "./", "./index.html", "./manifest.webmanifest", "./icon-180.png", "./icon-192.png", "./icon-512.png",
  "../shared/schedulemove.js", "../shared/scheduleview.js", "../shared/receiptscan.js", "../shared/receipt.js",
  "../shared/meeting.js", "../shared/planner.js", "../shared/scanrouter.js", "../shared/calendarread.js",
  "../shared/calendarwrite.js", "../shared/contacts.js", "../shared/suggest.js", "../shared/todos.js",
  "../shared/scheduletable.js", "../shared/documentreader.js", "../shared/history.js",
  "../shared/secretary.js", "../shared/aichat.js", "../shared/ondeviceai.js",
  "../shared/ics.js", "../shared/native.js", "../shared/watch.js",
  "../shared/character.js", "../shared/deeplink.js"
];

self.addEventListener("install", function (event) {
  event.waitUntil(caches.open(CACHE).then(function (cache) { return cache.addAll(ASSETS); }).then(function () {
    return self.skipWaiting();
  }));
});

self.addEventListener("activate", function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (key) { return key !== CACHE; }).map(function (key) {
      return caches.delete(key);
    }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener("fetch", function (event) {
  var request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;
  event.respondWith(caches.match(request).then(function (cached) {
    var network = fetch(request).then(function (response) {
      if (response && response.ok) {
        var copy = response.clone();
        caches.open(CACHE).then(function (cache) { cache.put(request, copy); });
      }
      return response;
    }).catch(function () { return cached; });
    return cached || network;
  }));
});
