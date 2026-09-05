# CB 链数据架构规范（2026-09-05 定案，零兼容收口）

> 本文是 CB 链的唯一架构文档。未来任何触及 chemical_cb / CB 解析 / CB 前端的工作，
> 先读本文。旧 schema 已全量迁移+旧解析器已剥除，代码里不存在双形态。

## 1. 采集边界

- **唯一采集目标页**: `ChemicalProductProperty_{CN,EN,JP,DE,KR}_CB{cb}.htm`（CPP 五语言页）
- **五语言是两套 DOM**（2026-09-05 真页实测，fixtures/cpp_*.html 是唯一依据）：
  - CN 页：物性在 ChemicalProperties 表（LabelID 配对），安全在 SafetyInformation 表
  - en 页：物性在 `table2` th/td 表，安全在 Risk and Safety h3 下 table2
  - de/ja/ko 页：物性混在头区 dl（46-48 对），安全在 `info_list` 表
  - 解析器三通道按此分发（parse_cpp.py 分区注释）；标签词表全部来自真页实测，禁自构模板验证
- **CAS 页（CAS_x_x.htm）职能只有一个**: 发现 cb_number。不解析内容，无兜底，无合并
- 队列任务带 cb_number 时直接寻址 CPP 页（CB 直连机制），零 CAS 请求
- ru 已剥离（代码 CB_LOCALES + 数据 DELETE 2156 行 + CHECK 约束收紧，0905）

## 2. entry canonical schema（chemistry.chemical_cb.entry jsonb）

六分区，全部白名单采集，白名单外不采（不存在 skip 补丁）：

```
identity: {                       # 头区 dl，页面原生身份字段
  cn, en: str                     # 中文名 / 英文名
  alias_cn, alias_en: [str]       # 别名（分号拆分）
  formula: str                    # 分子式
  mw: float                       # 分子量（float 解析失败即缺省，不存文本）
  mol_href: str                   # 站内 .mol 相对链接（只喂主表，不进本表消费）
}
props: [                          # ChemicalProperties 表，LabelID 配对
  { key, label, text,             # key=canonical英文键, label=页面原文标签, text=原文值
    v?, unit? }                   # 数值化：首数+单位（与 PB exp_props 同口径）
]                                 # smiles/inchi/inchikey 不数值化（文本即结构）
safety: { 原文标签: 原文值 }       # SafetyInformation 表 th/td，键值保原文
price: [ { updated, code, name, cas, package, price } ]  # ProductReagentPrice 固定六列
updown: {                         # 上下游 h3 区
  up, down: [ { name, cb_number? } ]   # cb_number 页面原生给出，必须保留
}
prose: [ { title, text } ]        # h3 标题白名单（用途/生产方法/化学性质等 19 个）
```

**不存在的键**（确认死数据/污染源，永不复活）：`basic / aliases / attributes /
reagent_prices / global_distribution / reagents / 更新日期 / FAQ`。
"更新日期"只在 price 行内（页面固定列），不作为独立字段。

## 3. canonical 键映射

- `caslib/parse_cpp.py::_PROP_KEY`：页面标签 → 英文键（178 实测键编制）。
  **未收录的长尾标签：key=原文 label，不强行归类**——宁要原文不要幻觉归类
- `::_IDENTITY_KEY`：头区标签 → identity 键
- `::_PROSE_TITLES`：prose 标题白名单
- 数值化 `::_parse_number_from_text`：`'162 °C (lit.)' → (162.0, '°C')`

规则变更 = 改这三张表 + 跑 `/tmp/cpp_real.html` 回归（tests/test_caslib.CppParseTests）。

## 4. 代码地图（唯一事实源）

| 职责 | 位置 |
|---|---|
| 解析器（五语言一套） | `caslib/parse_cpp.py::parse_cpp_page` |
| 页面判定/文本工具/供应商表 | `caslib/parse.py`（已收口，旧 entry 解析已删） |
| 抓取（含 CPP locale 直连） | `caslib/fetch.py::fetch_cas / fetch_cpp_locale` |
| worker 主链+语言链 | `worker/main.py`（zh-CN 与语言行同一解析路径） |
| 首访同步抓取 | `api/services/cb.py::sync_fetch_and_store` |
| 主表补缺/结构三件/CACHE_KEY v4 | `api/services/cb.py`（identity 直取，canonical 键） |
| 检索镜像摄入 | `api/services/name_index.py`（identity） |
| MCP 出口 | `api/mcp_server.py::get_chemical_externals` |
| 前端渲染 | `web/components/CasExternals.tsx`（六分区+形态守卫） |

`caslib/merge.py` 已删除（CAS 页合并是污染路径）。

## 5. 前端契约

- entry 无 `identity` 等新键的行（重抓过渡期）→ 形态守卫过滤 → CB 区空白但不报错
- 供应商区独立于 entry，照常渲染
- i18n casext 键集 = 六分区文案；数据原生内容不进语言包

## 6. 存量数据状态（2026-09-05 迁移后）

- 54,677 行全部 canonical 形态，旧字段残留 = 0
- 迁移来源：`~/ops/cb_entry_migrate.py`；回滚锚点：`chemistry.chemical_cb_premigrate_0905_bak`
- **迁移行 = canonical 壳 + 旧解析值**（props 配对大部分正确，但无 updown.cb_number，
  语言行无 identity）。干净终态靠重抓覆盖：zh-CN 全量入队 3rps，ON CONFLICT 覆盖
- 迁移期间 worker 在途 1 行（11708267）已确认被迁移覆盖，无漏网

## 7. 已知边界（防"惊喜"清单）

- props 数值化是**首数启发式**：`'270 to 275 °F'` v=270 unit 含 "to 275" 尾巴——
  text 原文始终在，v 只用于排序/比对场景
- 语言页标签本地化：未收录标签保原文 label，
  key 可能出现德文/日文——这是**设计**（保原文>幻觉归类），不是脏数据
- `not_found` 行不自然刷新（60 天窗只刷 ok 行）；要重刷需显式入队
- CPP 页 `<10KB` 一律 error 语义（拦截/降级页），不落数据层

## 8. 变更纪律

- 改 schema = 改本文 + 改解析器 + 改全部消费点 + CACHE_KEY bump + 前端守卫，一次过
- 禁止添加"兜底/合并/兼容"路径——历史证明每一条都是污染源
- 验证只用存量数据/样本页（/tmp/cpp_real.html）/worker 日志，禁直打源站
