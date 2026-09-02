# P3 用户触发 CB 即时拉 — 细化规划(2026-09-02)

## 口径(用户裁定)
- **P3 提为最高优先**: 输入 CAS 不存在 → 即时 CB 拉取建行, 用户等待即成本, 必须最快
- **拉取 = CPP-CN 当前语言正向**: 路径A(有号直跳CPP)已是; 路径B要 CAS 页先提号 — 提号是
  CAS 页唯一不可替代职能, entry 数据**以 CPP 为正向, 不再用 CAS 页兜底**
- **语言页按界面语言优先, 其余静默后台拉**

## 现状链路(实查)
- worker 路径B: CAS页提号 → CPP-CN(0901定案"一发定乾坤"); entry = parse_cpp_entry 优先,
  **parse_entry(CAS页)兜底** — 兜底在 worker:192 与 cb.py:577(同步路径)两处
- 页面数据对照实测(67-64-1/50-00-0 两条): CPP 页 props 是 CAS 页真子集,
  **CAS 页独有: 外观性状/外观性质/溶解性/电导率/Dielectric constant + 中文名称/EINECS/MDL/更新日期 + reagents**
  → CAS 兜底不是纯落伍信息, 携带 5 个物性字段+2个标识字段; 直接砍兜底会丢这些字段

## 方案

### ① CAS 页职责收口(修订用户假设, 需拍板)
CAS 页保留两个职能: 提号(不可替代) + **物性补充**(props 合并而非整体兜底):
```
entry = parse_cpp_entry(cpp)            # 正向: CPP 全量
merge(entry, parse_entry(cas), 策略)     # 补充: 只补 CPP 缺的 key
                                         # (外观性状/溶解性/EINECS/MDL/更新日期...)
```
- 不是"CPP 失败才用 CAS"(旧兜底), 是**两页都解析、CPP 为主、CAS 补缺**
- 语义变点: CPP 解析空且 CAS 有内容 → 旧=用CAS entry, 新=仍判 not_found(CB 主数据缺)
  — 这符合"cpp 为正向"
- worker:188-195 与 cb.py:574-577 两处同步改
- parse_entry 的 not_found 前置判定在 parse_cpp 链上不触发(只取字段, 不判态)

### ② P3 即时拉链(搜索 CAS miss)
现状: enqueue_cas_search_fetch 已建占位行+入列(priority=80 登录/50 匿名),
前端显示 fetchPending 静态文案。
改造(快路径, 用户等待压缩):
1. **同步拉首屏**(3s 预算): 搜索请求内直接 sync_fetch_and_store(已有函数,
   cb.py:555) — 路径B CAS提号+CPP 全程 ~1.5s(实测单页 0.6s), 命中即本次响应
   带回 entry, 前端直接跳转 chemical 页, 零轮询
2. 同步拉失败/超时 → 降级入列(现状路径), 前端轮询(P1 组件)
3. **语言页**: zh-CN ok 落库后, 界面语言是 zh-CN 即完成; 界面语言非 zh 的
   (i18n locale)→ 同步再拉一发对应 CPP 语言页(预算+1.5s); 其余语言照旧
   workapi 派发 priority=30 后台静默拉
4. 匿名 loopback 桶 30/min 限速不变, 同步拉消耗同一桶(防爬虫打穿)

### ③ 上线依赖
- P0(SSR 带 cookie)先行 — 否则 80 分拿到也压在匿名 50 分大部队后面
- P1(详情页轮询)作降级兜底
- 顺序: P0 → P3(①+②) → P1 → P2(身份直达)

### 改动面
- worker/main.py: ok 分支 entry 组装(~10行)
- api/services/cb.py: sync 路径同构(~10行) + 搜索 miss 接同步拉(~15行)
- api/routes.py: cas_search_state/enqueue 分支接同步拉(~10行)
- caslib/parse.py: 无改动(merge 在 worker/service 层做)
- 前端: fetchPending 文案 → 命中即跳转(收 P3 时一并)

### 风险
- 搜索响应时间: CAS miss 时 +3s 上限(预算钳制, 旧路径超时也是 503)
- merge 冲突: 同 key 两页值不同 → CPP 值胜(正向原则), 只补 CPP 缺失 key, 无覆盖
