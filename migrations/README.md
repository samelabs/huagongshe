# Migrations 契约（唯一权威文档）

## Fresh database（空库 bootstrap）

```
0000_baseline.sql
→ 0001_bootstrap_reference_data.sql
→ baseline 之后的 forward migrations（YYYYMMDD_NN_description.sql 按序）
```

## Existing production（cutover 时点）

- baseline + bootstrap reference data 视为**已满足**（production schema 即 baseline 来源）
- **不执行** `history/`
- 只执行 cutover 之后的 forward migrations

## history/

- **审计档案**：2026-09-10 cutover 前的全部 SQL（原 `/migrations` dated 33 个 + 原 `/api/migrations` 4 个加日期归档）
- **永远不参与 bootstrap / deploy**；不允许任何 runner 扫描此目录
- 内容冻结：只作历史记录，不修改、不重放

## 事实声明

- baseline cutover date：**2026-09-10**
- baseline target commit：**data-chain-v2 @ `e27dee0236934ab2b4d8b0a9b44477c371eea776`**
- baseline 是 **schema state**，不代表 application 已部署
- fresh restore 必须是**空 DB**（baseline 非幂等，不可重复执行）
- PostgreSQL host 需预装可用 extensions：**rdkit / pg_trgm / tsm_system_rows**（baseline 内 `CREATE EXTENSION IF NOT EXISTS`）
- baseline 不含 owner/ACL/业务数据/test_sentinel

## 命名规则（cutover 后）

```
YYYYMMDD_01_description.sql
YYYYMMDD_02_description.sql
```

即使当天只有一个 migration 也使用 `_01` 序号，消除同日字母序歧义。
