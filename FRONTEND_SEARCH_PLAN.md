# 前端搜索优化 — 执行方案(2026-09-02 定稿, 未动代码)

总目标: 搜索体验三态分流 — 身份唯一直达 / CAS miss 秒回 / 关键词列表。
执行序 P0 → P3 → P1 → P2, 每步独立可上可回退, 互不阻塞。

---

## P0 — SSR 透传用户凭证(修 80 分失效 bug)

**问题**: 详情页/搜索页 SSR 调 API 不带 cookie → 登录用户被 API 视为匿名 →
PB/CB 任务 priority=50, 压在 3.4 万后台回补后面(987 实测等 5h)。
机制早已存在(routes.py:129 priority=80 if actor), 纯前端没送凭证。

**改动**(2 个文件, ~10 行):
- `web/app/(site)/chemical/[id]/page.tsx`: 已有 `const hasSession = (await cookies()).has("hgs_session")`
  — 补: cookie 在时构造 `sessionHeaders = new Headers({"cookie": "hgs_session=..."})`
  传入三个 apiGet(chemical/reactions/externals)
  ⚠️ Next.js cookies() 只给值不给完整 Set-Cookie; 取 `(await cookies()).get("hgs_session")?.value`
  ⚠️ apiGet 带 headers 时禁缓存(lib/api.ts:20 防误用) — 本来这些请求就没 revalidate, 兼容
- `web/app/(site)/search/page.tsx`: exact 模式也带 sessionHeaders(现在只结构检索带, :26)
- 登录墙语义不变: 匿名照旧 50 分; 只是登录用户终于拿到 80

**验证**: 登录态访问缺 PB 数据的详情页 → 日志/DB 里该 job priority=80;
  队列非空时插队时延 < 10s(lease 批 10 × 1s/条最坏)。

**风险**: 无逻辑风险, 纯透传。缓存: 带 cookie 的请求 next fetch 层禁缓存, 每次实打实
  — 详情页 QPS 低, 可接受。

---

## P3 — CAS miss 同步拉 + CAS 页职责收口(用户等待压到最低)

### 3a. CAS 页职责收口(cpp 正向)
**现状**: worker:188-195 entry = CPP 优先, CAS 页 parse_entry 整体兜底;
供应商 CAS 页兜底(worker:200-201, cb.py 同步路径 574-577 同构)。
**实测**: CPP props ⊂ CAS props(CAS 独有: 外观性状/外观性质/溶解性/电导率/
Dielectric constant + EINECS/MDL/更新日期 + reagents); CPP 独有(别名全表/
全球分布/价格/100家供应商)。CAS 供应商数据不准(用户裁定弃)。

**改动**(worker/main.py + api/services/cb.py 各 ~10 行):
```
entry = parse_cpp_entry(cpp_html)                    # 正向
if entry and cas_html:
    cas_e = parse_entry(cas_html)                     # 只为补缺
    if cas_e:
        merge: props/basic 字段级只补 CPP 缺的 key(CPP 值恒胜)
        + reagents 块(CAS 独有)
语义变点: CPP 解析空 + CAS 有内容 → 仍判 not_found(CB 主数据缺, 不用 CAS 顶)
suppliers: 只走 CPP 源, CAS 供应商兜底两处删(数据不准)
mol: 双源提取保持(已是)
```
fetch 层零改动(路径A/B/判定不动)。

### 3b. 搜索 CAS miss 同步拉首屏
**现状**: enqueue_cas_search_fetch 建占位行+入列, 前端 fetchPending 静态文案。
**改动**(api/routes.py ~15 行 + 前端 ~10 行):
1. 搜索 miss 且 q 为 CAS 格式: 先 `sync_fetch_and_store`(已有, cb.py:555,
   3s 预算, 路径B实测全程 ~1.5s) — 线程池跑不阻塞事件循环
2. 命中(ok): 本次响应直接带 `cas_fetch_chemical_id`(占位行 id) +
   `cas_fetch_status:"ok"` → 前端立即 router.push(/chemical/{id}), 零轮询
3. 未命中/超时: 降级现有入列路径(80 分), 响应带 `cas_fetch_pending` —
   前端照旧跳占位行详情页, 轮询兜底(P1 落地前显示现有文案)
4. 界面语言 ≠ zh: 命中后同步再拉一发对应 CPP 语言页(预算+1.5s, 仅登录用户,
   匿名不拉防爬虫); 其余语言照旧 workapi 派发 priority=30 静默后台
5. 限速: 同步拉消耗匿名 loopback 30/min 同桶(现有限速器覆盖, 不新开机制)
**注意**: sync 路径只服务 loopback(SSR); 公网 API 直调不触发同步拉(维持 T0 内部通道语义)。
搜索 SSR 本身经 BFF = loopback → 天然满足。

**验证**: 匿名+登录各搜一个库外 CAS → 响应时间 < 3.5s, 命中即带 chemical_id;
爬虫模拟 40 CAS/min → 第 31 个起 fetchPending 不同步拉。

---

## P1 — 详情页轮询(PB/CB 完成后无感刷新)

**现状**: ChemicalKnowledge 的"正在同步"是静态文案, 零轮询, 数据到了必须手动刷新。

**改动**(新客户端组件 ~40 行 + 挂载 ~5 行):
- `<DetailRefresher enrichment={...} externalsState={...} chemicalId={id} />`
  客户端组件: enrichment.status==='queued' 或 externals 无数据且 job 在途 →
  每 4s `router.refresh()`(Next 原生, 重走 SSR 拿新数据, 不写两套取数逻辑)
- 终止条件: status 变 current / externals 到数据 / 90s 超时停(留现有文案)
- 只在 SSR 判定"在途"时渲染, 静态页零开销
**验证**: 搜库外 CAS 跳详情页 → 3-8s 内页面自动出 CB 数据, 无手动刷新。

---

## P2 — 身份键唯一命中直达(统一规则, 前后端同口径)

**改动**(api/services/search.py 判定单点 + routes.py ~8 行 + 前端 ~8 行):
- run_search_query 后: q 是身份键(CAS 精确/InChIKey/canonical SMILES/pubchem cid/hcid)
  且 chemicals 恰 1 行且无 reactions → 响应附 `redirect_chemical_id`
- 前端 search page: 有该字段 → router.push(/chemical/{id})(列表渲染跳过)
- API 同理: 字段在响应里, 调用方自决跳转 — 统一规则"唯一命中即该是详情"
- 多命中/关键词/部分匹配 → 照旧列表, 不动
**边界**: canonical SMILES 归一后比对(已有 canonicalize_smiles); hcid/hrid 走
  现有 id 解析; 不新增索引(身份查询全部命中现有 GIN/主键)

---

## 上线顺序与依赖
P0 独立(先行, 半小时级) → P3a(独立) → P3b(依赖 P0 的 80 分兜底路径) →
P1(独立, 但配合 P3b 的占位跳转才有意义) → P2(独立)。
每步: diff 报批 → 部署 → 观察 → 下一步。P3a 与 P3b 可合并一次上线。

## 不动清单(明确)
- 判定链(caslib 三态/page_identity/字节分界): 零改动
- 队列/租约/闸门/rps: 零改动(lease 批量 10 维持 — 80 分已解决插队, 不必回调 2)
- not 剥离后语义: 不回头加负缓存
- 表结构: 零变更
