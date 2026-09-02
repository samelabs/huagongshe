# CB not 剥离方案(2026-09-02 准备稿, 未上线)

## 语义定案(用户口径)
- not_found 不再写任何记录: job complete 静默出列, 数据层零写入
- 收录与否的表达 = 记录表本身: chemical_cb 无行/主表 cb_number IS NULL 即"没收录"
- 现存 not 行(负缓存锚)全量删除

## Phase 1 — 数据表剥离(SQL, 手工执行)

```sql
-- 41,530 行负缓存锚(zh 22,633 + en 3,473 + ja 4,017 + de 2,982 + ko 2,951 + ru 2,593 + 语言not含今天新落)
DELETE FROM chemistry.chemical_cb WHERE last_status='not_found';
-- 411 行历史 error 残留(error 不落数据层的定案前产物, cb_decide 会防御性重问, 一并清)
DELETE FROM chemistry.chemical_cb WHERE last_status='error';
-- ru 死循环 job 行(13446-18-9, 后缀已摘永远重试)
DELETE FROM maintenance.cas_jobs WHERE request_context->>'locale'='ru';
```

剥离后 chemical_cb 仅存 ok 行(~66k): zh 35,221 + en 5,122 + ko 2,905 + de 2,874 + ja 1,839 + ru 2,156(废语言的历史 ok, 无消费方, 留)。

## Phase 2 — 代码剥离(diff 已备, 不上线)

### ① cb.py persist_cb_result(:86-99) — 写入点归零
```python
# 现行:
if status == "not_found":
    await db.execute(text("""
        INSERT INTO chemistry.chemical_cb ... VALUES (...,NULL,:status,now(),...)
        ON CONFLICT (chemical_id, locale) DO NOTHING
    """), {...})
    return
# 改为(整支删除, 换一行):
if status == "not_found":
    # 0902 剥离: not 零写入 — 静默出列, 收录与否由记录表本身缺行表达
    return
```

### ② cb.py cb_decide(:476-487) — 判定分支收敛
```python
# 删: status == "not_found" 分支(serve_negative/enqueue_requery 两态)
# 删: _cb_window_days 里 not_found_requery_days 键(ok_refresh_days 保留)
# 留: row None → enqueue_first; ok → serve_fresh/enqueue_refresh
# 未知状态 → enqueue_first(防御, 兼容剥离过渡期残留行)
```
五态收敛为四态: serve_fresh / enqueue_first / enqueue_refresh / skip。

### ③ workapi.py lease 终态拦截(:283-310) — 整段删
`intercepted` CTE(负缓存命中 DELETE 出表)整体删除 — 锚行没了, 拦截永远不命中,
留着是死代码 + 曾静默删修复任务的案发现场。候选集直通分发。

### ④ ensure_externals serve_negative 支(cb.py:644-646) — 删
row 在但 not 的出空分支随 ② 消失; 无行 → absent(调用方决定), ok → fresh。

### ⑤ 不动的部分(明确列出)
- worker/main.py: 三态直译不变 — fetch 层仍需区分 ok/not_found/error(判定逻辑是
  抓取语义, 不是记录语义); not_found 载荷照发, 服务端 ① 处静默。
- caslib 判定链(page_identity/字节分界): 不动。
- schemas status pattern ^(ok|not_found|error)$: 不动(fetch 层仍产三态)。
- name_index ingest: entry=None 清空分支成为死路(not 不再进 upsert), 不删不害。

## 剥离后的重复追问语义(唯一决策点)
锚删了, "问过但没收录"与"从没问过"在数据上不可区分(cb_decide 均判 enqueue_first)。
后果: 用户搜索/详情访问一个 CB 未收录 CAS → 每次访问都会重新入列重抓一遍
(dedupe 活跃窗只挡在途, 完成后下次访问再入列)。rps 限速兜底, 但这是对上游的
重复无效请求。
- 默认按你的口径接受: 访问驱动、rps 限速、零状态 = 最简机制
- 若不接受, 备选: cb_decide 里 主表行在 AND cid IS NULL AND cb_number IS NULL
  (CB 占位行从没拿到号 = 问过没收录) → 出空不重问; PB 行(cid 在)仍首问。
  一行判定, 不写任何新记录。要哪个口径, 你定。

## 执行顺序(上线时)
SQL(Phase 1) → 立即重启 api+worker(Phase 2) — 中间窗口老代码会把无行当首问
重新入列, 分钟级窗口内搜索流量小, 可接受; 顺序不能反(新代码+旧 not 行 →
防御分支把 2.2 万 zh not 全部重问)。
