// Service worker for the Arian laundry PWA (served at /serviceworker.js by django-pwa).
// Pages are always fetched from the network so order status, wallet balance and CSRF
// tokens are never stale; the offline page is shown only when the network is down.
// Keep this file ASCII-only: django-pwa reads it with the platform default encoding.

var CACHE_NAME = 'arian-pwa-v2';
var OFFLINE_URL = '/offline/';
var PRECACHE_URLS = [
    OFFLINE_URL,
    '/static/icon.png',
    '/static/pwa/icon-192.png',
    '/static/pwa/icon-180.png'
];

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(function (cache) { return cache.addAll(PRECACHE_URLS); })
            .then(function () { return self.skipWaiting(); })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys()
            .then(function (names) {
                return Promise.all(names
                    .filter(function (name) {
                        return (name.indexOf('arian-pwa-') === 0 || name.indexOf('django-pwa-') === 0)
                            && name !== CACHE_NAME;
                    })
                    .map(function (name) { return caches.delete(name); }));
            })
            .then(function () { return self.clients.claim(); })
    );
});

self.addEventListener('fetch', function (event) {
    var request = event.request;
    if (request.method !== 'GET') return;

    var url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    // Pages: network only, offline page as fallback.
    if (request.mode === 'navigate') {
        event.respondWith(
            fetch(request).catch(function () { return caches.match(OFFLINE_URL); })
        );
        return;
    }

    // Static files: serve from cache, refresh it in the background.
    if (url.pathname.indexOf('/static/') === 0) {
        event.respondWith(
            caches.open(CACHE_NAME).then(function (cache) {
                return cache.match(request).then(function (cached) {
                    var network = fetch(request).then(function (response) {
                        if (response.ok) cache.put(request, response.clone());
                        return response;
                    });
                    if (cached) {
                        network.catch(function () {});
                        return cached;
                    }
                    return network;
                });
            })
        );
    }
});
