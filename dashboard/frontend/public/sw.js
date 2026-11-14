const CACHE = 'ryukomik-staff-shell-v16'
const SHELL = ['/', '/manifest.webmanifest?v=staff-20260804-2', '/icons/ryukomik-staff-20260804.png?v=staff-2']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))))
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) return
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/')))
    return
  }
  // Hashed assets (index-<hash>.js, OcrPage-<hash>.js, ...) are immutable: a new
  // deploy always ships new filenames, so a stale cached copy can never be
  // "correct". Serve the cache only when the network is unavailable, so a
  // freshly deployed bundle is picked up immediately instead of after a
  // manual hard refresh. Non-hashed files keep the network as the source of
  // truth too, which is what previously hid new releases behind cache-first.
  event.respondWith(fetch(request).then((response) => {
    if (response.ok && ['script', 'style', 'image', 'font'].includes(request.destination)) {
      const copy = response.clone()
      caches.open(CACHE).then((cache) => cache.put(request, copy))
    }
    return response
  }).catch(() => caches.match(request)))
})
