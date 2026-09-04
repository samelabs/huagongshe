// 缓存面收口(2026-08-27): 只缓存不可变静态资源(带内容哈希的 /_next/static 与本站图标/manifest)。
// 用户态内容(HTML 导航/RSC 载荷)一律禁入缓存 —— 旧版把它们落进 SWR 分支,
// 登出后客户端路由回放缓存里登入态的旧 RSC, 造成用户信息残存(已修, 升版清污染)。
const CACHE_VERSION = 'hgs-pwa-v24';
const STATIC_CACHE = `${CACHE_VERSION}-static`;

// 仅不可变资源: /_next/static/* 构建产物带内容哈希, 图标/manifest 跨版本稳定
const STATIC_PATTERN = /^\/(_next\/static\/|icon-|logo|manifest\.webmanifest|favicon)/;

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // 升版即清旧: 含 v12 时代被用户态内容污染的全部缓存
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== STATIC_CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // API: 不缓存
  if (url.pathname.startsWith('/api/')) return;

  // 收口: 只有不可变静态资源进缓存(cache-first), 其余(导航 HTML/RSC)全走网络
  if (!STATIC_PATTERN.test(url.pathname)) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      });
    })
  );
});
