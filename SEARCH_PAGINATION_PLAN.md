# 搜索结果翻页改造方案

## 现状

| 层 | 限制 | 实测性能 |
|---|---|---|
| 前端 `page_size=20` 硬编码 | 写死20 | — |
| API `/search` page_size | 默认20, 上限le=50 | — |
| API `/search` limit截断 | `min(page_size, 30)` | — |
| 子结构/相似搜索 limit | 默认20, 上限le=50 | — |
| 前端子结构/相似 | `?limit=20` | — |

**实测数据（非推测）：**
- exact 名称搜索 tinib：8ms，命中159条
- exact OFFSET翻页到第3页(OFFSET 100)：64ms
- nilotinib 子结构搜索：762ms，命中182条
- nilotinib 子结构 OFFSET翻页到第3页：< 1s
- 极端case（苯环子结构）：count超时（>8s），需防护

## 改造目标

用户和AI都能看到全部结果，翻页廉价，结构搜索不被滥用。

## 改造方案

### 1. API `/search` — 统一搜索接口

**改动：**
```python
# 路由签名
page: int = Query(1, ge=1, le=20)        # 新增page参数, 最多翻20页
page_size: int = Query(30, ge=1, le=100)  # 默认30, 上限100
```

**查询逻辑：**
- 删除 `limit = min(page_size, 30)` 截断
- 改为 `limit = page_size`, `offset = (page - 1) * page_size`
- 增加 `total` 字段：单独跑一次 `SELECT count(*)`，加 `statement_timeout=3s` 超时保护
  - count 成功 → 返回 total（用户看到"找到159个"）
  - count 超时 → total = null（不显示总数，不阻塞结果返回）

**返回结构：**
```json
{
  "query": "tinib",
  "mode": "exact",
  "page": 1,
  "page_size": 30,
  "total": 159,
  "chemicals": [...],
  "reactions": [...]
}
```

**缓存策略：**
- exact 模式：不缓存（已有逻辑）
- 子结构/相似模式：缓存 key 加入 page 和 page_size
  ```python
  cache_key = f"v2:unified-search:{mode}:{page}:{page_size}:{query}"
  ```
- TTL 300s（5分钟）

**count 超时防护：**
```python
try:
    await db.execute(text("SET LOCAL statement_timeout = '3s'"))
    total = await db.execute(text("SELECT count(*) FROM ... WHERE ..."))
    total = total.scalar()
except Exception:
    total = None  # count超时不阻塞主结果
```

### 2. API `/chemicals/{id}/substructure` 和 `/similarity`

**改动：**
```python
page: int = Query(1, ge=1, le=20)
limit: int = Query(30, ge=1, le=100)  # 改名→page_size保持一致，或保留limit加page
```

增加 page/offset 支持，增加 total 返回。
复用 `/search` 的 count 超时防护。

### 3. 前端 `app/search/page.tsx`

**改动：**
- `page_size=20` → `page_size=30`
- 读取 URL 参数 `page`，传给 API
- 显示 "找到 {total} 个 · 显示第 {offset+1}-{offset+len} 个"
- 底部「加载更多」按钮（非无限滚动）
  - 点击 → `router.push('/search?q=tinib&page=2')`
  - 最后一页 → 隐藏按钮
  - total=null → 显示「更多结果」替代「加载更多」

### 4. 前端 `SearchResponse` 类型

```typescript
export type SearchResponse = {
  query: string;
  mode: string;
  canonical_smiles: string | null;
  page: number;
  page_size: number;
  total: number | null;      // null = count超时
  chemicals: Chemical[];
  reactions: ReactionLookup[];
};
```

### 5. AI Agent 接口

`api/agent.py` 中搜索工具描述更新：
```
"input": "q 必填；mode 为 exact、substructure 或 similarity；page_size 最大 100；page 最大 20；返回 total 总数",
```

AI 拿到 total 后可自主决定翻页。单次 page_size=100 可覆盖大多数查询。

### 6. i18n 文案

```typescript
showingResults: (start, end, total) => `显示第 ${start}-${end} 个` + (total ? `，共 ${total} 个` : ''),
loadMore: '加载更多',
noMoreResults: '已显示全部结果',
```

## 性能保障

| 场景 | 耗时 | 防护 |
|---|---|---|
| exact 名称搜索 | 8ms | 无需特殊防护 |
| exact OFFSET翻页 | 64ms | page上限20 |
| 子结构搜索 | ~800ms | 缓存5min + statement_timeout=8s |
| 子结构OFFSET翻页 | <1s | 缓存命中<50ms |
| count查询 | 3s超时 | 超时则total=null，不阻塞 |
| 极端case(苯环) | count超时 | total=null + LIMIT截断，不返回错误 |

## 不做的事

- ❌ 无限滚动（SSR不友好，移动端体验差）
- ❌ 随机跳页（OFFSET大值性能差）
- ❌ 游标分页（复杂度高，当前性能不需要）
- ❌ 前端二次筛选（不在本次范围）

## 改动范围

| 文件 | 改动 |
|---|---|
| `api/routes.py` | search/substructure/similarity 3个接口加page参数+total+count防护 |
| `api/agent.py` | 搜索工具描述更新 |
| `web/lib/api.ts` | SearchResponse类型加page/total字段 |
| `web/app/search/page.tsx` | page_size=30+加载更多+总数显示 |
| `web/lib/i18n.ts` | showingResults/loadMore文案 |
