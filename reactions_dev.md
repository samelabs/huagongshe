# reactions 当前数据规范

> 本文只记录已经落库并完成校验的反应领域结构。ORD 是反应事实和上下文来源，RDKit 是表达与检索能力来源；二者都不再充当项目自主反应身份。

## 1. 领域边界

项目的两个自主领域根是：

- `chemistry.chemicals`：化合物身份、结构、基础信息和结构检索。
- `chemistry.reactions`：反应身份和反应表达。

`ord.*` 保留原始反应事实、条件、输入、产物、测量、来源等完整上下文。`chemistry.reaction_chemicals` 是 chemicals 与 reactions 之间用于检索和角色表达的稳定关系，不替代 ORD 的详细事实表。

## 2. 自主反应表

```text
chemistry.reactions
  id                bigint primary key   -- 项目自主 reaction_id
  reaction_smiles   text                 -- 从 ORD 吸收的反应表达
  reaction          public.reaction      -- 已物化的 RDKit reaction，可空
  created_at        timestamptz
  updated_at        timestamptz
```

规则：

1. `id` 由项目序列产生，不以 ORD ID 或 RDKit ID 充当主键。
2. reaction SMILES 不设唯一约束；相同表达可以对应不同来源、条件和结果的反应事实。
3. RDKit reaction 是可重建的检索表达，不是反应身份。
4. 用户提交和后续来源可以直接获得自主 reaction ID，不要求存在 ORD 记录。

当前共有 2,428,291 行，其中 2,418,635 行具备 reaction SMILES；这些行已全部物化当前 RDKit reaction，转换失败为 0。其余 9,656 行的源 ORD 本来没有 reaction SMILES。

## 3. 反应—化合物关系

```text
chemistry.reaction_chemicals
  reaction_id       bigint  FK -> chemistry.reactions.id
  chemical_id       integer FK -> chemistry.chemicals.id
  role              text
  occurrence_count  integer CHECK (> 0)

  PK (reaction_id, chemical_id, role)
```

当前共有 13,023,629 个唯一关系，`occurrence_count` 合计 14,149,027，与原 `ord.mol_reaction` 逐行事实完全一致。649,941 组关系存在重复出现，共折叠 1,125,398 行；次数没有丢失。

角色事实合计：

```text
REACTANT             7,966,431
PRODUCT              2,605,008
SOLVENT              2,822,043
CATALYST               460,949
REAGENT                241,346
INTERNAL_STANDARD       50,364
UNKNOWN                  2,116
WORKUP                     770
```

索引：

- 主键 `(reaction_id, chemical_id, role)` 支持由反应读取参与化合物。
- `(chemical_id, reaction_id)` 支持由化合物检索反应。
- 两个外键均已全量验证，删除策略为 `RESTRICT`。

## 4. ORD 来源映射与 RDKit 解耦

- `ord.reaction_map`：2,428,291 个 ORD reaction ID 到自主 reaction ID 的一一来源映射。
- `ord.compound`、`ord.product_compound` 已直接引用 `chemical_id`。
- `ord.mol_reaction`、`rdkit.mols`、`rdkit.reactions`、Mol ID 桥和 RDKit reaction ID 桥均已删除。
- `ord.reaction.rdkit_reaction_id` 已删除；ORD 对旧 RDKit reaction 表不再存在外键或字段耦合。

新代码直接使用自主 `chemical_id`、`reaction_id`。ORD reaction ID 只通过来源映射用于回读原始条件和事实。

## 5. RDKit 全量物化结果

对 10,000 条 reaction SMILES 的抽样转换结果：

- 成功：10,000
- 失败：0
- SMILES 平均约 406 字节
- RDKit reaction 平均约 1,699 字节，最大样本约 6,130 字节

清理旧构建缓存、已导入 PubChem 文件、DSSTox 暂存表和 `compound_identifier` 后完成了全量物化：

- 物化成功：2,418,635
- 失败：0
- `chemistry.reactions` 总大小约 6.0GB，其中全量部分 GiST 索引约 2.15GB。
- reaction 包含检索已验证命中 `reactions_reaction_gist_idx`；选择性样例冷查询约 59ms。

## 6. 当前运行约束

- 线上 API 已直接使用 `chemistry` 核心表；历史 ORD/RDKit 中间服务不再运行。
- 所有大任务保留至少 5GiB 根分区硬保护线。
- 不对 ORD 千万级表做原位全量 UPDATE；采用新表构建、校验、切换。
- `compound_identifier` 已按确认删除；其删除前类型统计和结构备份见 `cleanup_manifest_20260719.md`。
- DSSTox 原始 CSV、匹配表和残余审计继续保留。
- `migrate_ord_reactions.py`、`migrate_ord_occurrences_to_chemicals.py`、`materialize_rdkit_reactions.py` 保存阶段状态，可审计全部迁移。

## 7. 下一步

1. API 直接查询 `chemicals`、`reactions` 和 `reaction_chemicals`。
2. 以 ORD 字段和约束反向设计用户提交、校验、维护的最小交互，不把 ORD 原始表直接暴露给用户。
3. 适配完成前继续保持旧服务和 PubChem worker 停止。
