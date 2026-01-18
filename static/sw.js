const CACHE_NAME = 'mega-forex-v8.2';

const ASSETS_TO_CACHE = [
  '/',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(ASSETS_TO_CACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) => {
      return Promise.all(
        names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  if (event.request.url.includes('/signals') || 
      event.request.url.includes('/rates') ||
      event.request.url.includes('/news')) return;
  
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        if (response.status === 200) {
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
```

5. Click **"Commit changes"** → **"Commit changes"**

---

### **Step 4: Upload Icons (PNG files)**

1. Go to repo main page
2. Click on **`static`** folder
3. Click **"Add file"** → **"Upload files"**
4. Download these 2 icon files I provided above:
   - `icon-192.png`
   - `icon-512.png`
5. **Drag and drop** both PNG files into GitHub
6. Click **"Commit changes"**

---

### **Step 5: Verify Files**

Your repo structure should now look like:
```
mega-forex-pwa/
├── app.py              ← Updated
├── templates/
│   └── index.html
├── static/             ← New folder
│   ├── manifest.json   ← New
│   ├── sw.js           ← New
│   ├── icon-192.png    ← New
│   └── icon-512.png    ← New
├── requirements.txt
├── Procfile
└── render.yaml
