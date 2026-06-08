const CACHE_NAME = "nse-ai-cache-v7";
const ASSETS = [
  "./",
  "./index.html",
  "./news.html",
  "./stocks.html",
  "./login.html",
  "./register.html",
  "./css/style.css",
  "./js/api.js",
  "./js/app.js",
  "./js/auth.js",
  "./js/chart.js",
  "./manifest.json"
];

// Install Event
self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log("Caching PWA shell assets");
      return cache.addAll(ASSETS);
    })
  );
});

// Activate Event
self.addEventListener("activate", (e) => {
  e.waitUntil(
    Promise.all([
      caches.keys().then((keys) => {
        return Promise.all(
          keys.map((key) => {
            if (key !== CACHE_NAME) {
              console.log("Clearing old PWA cache", key);
              return caches.delete(key);
            }
          })
        );
      }),
      self.clients.claim()
    ])
  );
});

// Fetch Event (Network first, fall back to cache)
self.addEventListener("fetch", (e) => {
  // Avoid caching API routes
  if (e.request.url.includes("/api/")) {
    return;
  }
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        // Cache clone of successful request
        const resClone = res.clone();
        caches.open(CACHE_NAME).then((cache) => {
          cache.put(e.request, resClone);
        });
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
