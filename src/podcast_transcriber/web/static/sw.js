/* podcast-transcriber — PWA-lite service worker.
 * Caches ONLY the app shell (index, css, htmx, icons, manifest) for offline
 * start.  Dynamic pages and HTMX fragments (/jobs/*, /search, ...) are NEVER
 * intercepted or cached: they must always hit the network so progress polling
 * and job state stay fresh.
 *
 * Cache version bump forces previously-installed workers to reinstall and
 * drop their old (over-broad) caches on activate.
 */
const CACHE = "pt-shell-v3";
const SHELL = [
  "/",
  "/static/style.css",
  "/static/htmx.min.js",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/manifest.webmanifest",
];

/* Pure decision function (unit-testable): return the caching strategy for a
 * same-origin GET pathname, or null when the request must go straight to the
 * network — never intercepted, never cached.
 *
 *   "network-first" -> "/" : fresh copy when online, cached shell when offline
 *   "cache-first"   -> immutable shell assets
 *   null            -> everything else (dynamic pages + HTMX fragments)
 */
function ptCacheStrategy(pathname) {
  if (pathname === "/") return "network-first";
  if (pathname === "/manifest.webmanifest") return "cache-first";
  if (pathname.startsWith("/static/")) return "cache-first";
  return null;
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;

  const strategy = ptCacheStrategy(url.pathname);
  if (strategy === null) {
    // Dynamic pages + HTMX fragments: network default, never cached.  Without
    // this guard, a cached /jobs/<id>/status fragment would freeze progress
    // polling forever.
    return;
  }

  if (strategy === "network-first") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Only cache OK responses: with auth enabled, an unauthenticated
          // fetch of "/" returns 302 -> /login, and that redirect page must
          // never become the offline shell.
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Shell assets: cache-first, refreshed in the background.
  event.respondWith(
    caches.match(request).then((cached) => {
      const refresh = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached);
      return cached || refresh;
    })
  );
});
