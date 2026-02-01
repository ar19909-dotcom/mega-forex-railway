// MEGA FOREX v9.2.4 PRO - Service Worker
const CACHE_NAME = 'mega-forex-v9.2.4';
const OFFLINE_URL = '/offline.html';

// Assets to cache for offline use
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png',
  'https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js',
  'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
  console.log('[SW] Installing MEGA FOREX PWA...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Caching static assets');
        return cache.addAll(STATIC_ASSETS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event - clean old caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating MEGA FOREX PWA...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch event - network first for API, cache first for assets
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  
  // API requests - network first, don't cache
  if (url.pathname.startsWith('/api') || 
      url.pathname.startsWith('/signals') || 
      url.pathname.startsWith('/rates') ||
      url.pathname.startsWith('/news') ||
      url.pathname.startsWith('/calendar') ||
      url.pathname.startsWith('/positioning') ||
      url.pathname.startsWith('/backtest') ||
      url.pathname.startsWith('/audit') ||
      url.pathname.startsWith('/journal') ||
      url.pathname.startsWith('/performance')) {
    event.respondWith(
      fetch(event.request)
        .catch(() => {
          return new Response(
            JSON.stringify({ 
              success: false, 
              error: 'Offline - Please check your connection',
              offline: true 
            }),
            { 
              headers: { 'Content-Type': 'application/json' },
              status: 503
            }
          );
        })
    );
    return;
  }
  
  // Static assets - cache first, then network
  event.respondWith(
    caches.match(event.request)
      .then((cachedResponse) => {
        if (cachedResponse) {
          // Return cached version, but fetch update in background
          fetch(event.request).then((response) => {
            if (response && response.status === 200) {
              caches.open(CACHE_NAME).then((cache) => {
                cache.put(event.request, response);
              });
            }
          }).catch(() => {});
          return cachedResponse;
        }
        
        // Not in cache, fetch from network
        return fetch(event.request)
          .then((response) => {
            // Cache successful responses
            if (response && response.status === 200) {
              const responseClone = response.clone();
              caches.open(CACHE_NAME).then((cache) => {
                cache.put(event.request, responseClone);
              });
            }
            return response;
          })
          .catch(() => {
            // Return offline page for navigation requests
            if (event.request.mode === 'navigate') {
              return caches.match(OFFLINE_URL);
            }
          });
      })
  );
});

// Background sync for journal entries
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-journal') {
    event.waitUntil(syncJournal());
  }
});

async function syncJournal() {
  // Get pending journal entries from IndexedDB and sync
  console.log('[SW] Syncing journal entries...');
}

// Push notifications for high-score signals
self.addEventListener('push', (event) => {
  if (event.data) {
    const data = event.data.json();
    const options = {
      body: data.body,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      vibrate: [100, 50, 100],
      data: {
        url: data.url || '/'
      },
      actions: [
        { action: 'view', title: 'View Signal' },
        { action: 'dismiss', title: 'Dismiss' }
      ]
    };
    
    event.waitUntil(
      self.registration.showNotification(data.title, options)
    );
  }
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  
  if (event.action === 'view') {
    event.waitUntil(
      clients.openWindow(event.notification.data.url)
    );
  }
});
