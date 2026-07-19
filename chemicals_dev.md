# chemicals 当前数据规范

> 本文只记录已经确认的架构和当前实体状态，不以历史前端、旧 worker 或旧表结构推导产品方向。

## 1. 定位

`chemicals` 是项目自主维护的化合物事实入口。PubChem、DSSTox、PubChem worker 与 ORD/RDKit 都是它的数据或能力来源，不是与它长期并列的化合物真相库。

- PubChem 发布文件：提供大规模结构种子和外部标识。
- DSSTox：一次性提供 EPA 策展的名称、CAS 和结构校准信息。
- PubChem worker：按需回补离线文件未覆盖或超时的信息。
- RDKit：统一解析、标准化、派生属性和结构检索能力。
- ORD：反应事实和反应架构的来源；其化合物表达能力最终由 `chemicals` 承接。

项目最终只有两个自主领域根：`chemicals` 和 `reactions`。ORD 对 RDKit 化合物/反应检索表的耦合，将逐步转向这两个领域表。

## 2. 身份与结构原则

1. `chemistry.chemicals.id` 是项目自己的 `chemical_id`，承担跨来源的稳定身份；它已与所有外部来源编号解耦。
2. `pubchem_cid`、`dtxsid` 等只在各自来源命名空间内唯一；CAS、名称、SMILES 均不能单独充当绝对身份。
3. `smiles` 是 RDKit 标准化后的结构表达。它可以重建 Mol，但字符串本身不等于跨来源身份判断。
4. 多源合并必须区分“候选召回”和“身份确认”。CAS 可以召回候选，不能单独确认结构。
5. 外部 ID 按源文件实际基数存储：PubChem CID 下实际存在多值的标识使用数组；DSSTox 当前每条记录只有一个 DTXSID，使用标量。不要为了假设中的兼容性把所有字段数组化。

## 3. 当前实体：`chemistry.chemicals`

当前表包含 124,001,345 个 PubChem 种子记录和 109,890 个 ORD/RDKit 补充结构，共 124,111,235 行，并已采用自主主键。PubChem 只是来源，不决定 chemicals 的身份和覆盖范围。

### 结构与基础字段

```text
id                   integer primary key   -- 自主序列生成的 chemical_id
pubchem_cid          integer                -- 可空的 PubChem 来源 ID
pubchem_smiles       text                   -- 可空的 PubChem 原始结构
smiles               text                   -- RDKit 标准化结构
preferred_name       text
iupac_name            text
molecular_formula    text
average_mass         double precision
monoisotopic_mass    double precision
inchikey              text
dtxsid                text
mol                    public.mol            -- 可重建的 RDKit Mol
morgan_bfp             public.bfp            -- 相似检索位指纹
morgan_sfp             public.sfp            -- 相似/索引稀疏指纹
synonyms              jsonb                 -- 当前不导入原始噪声别名
created_at            timestamptz
updated_at            timestamptz
```

### PubChem 外部标识

```text
cas_numbers           text[]
nikkaji_numbers       text[]
chembl_ids            text[]
ec_numbers            text[]
unii_codes             text[]
chebi_ids              text[]
```

CAS 只保留这一份候选集合，不再增加 `preferred_casrn` 等重复字段。DSSTox CAS 用于候选匹配和校准；命中记录的 CAS 已存在于 `cas_numbers[]`，无需重复写入。

## 4. 已完成的 PubChem 导入

- `CID-SMILES.gz`：124,001,345 行已入库。
- RDKit 标准化成功 123,959,434 行，失败或空 41,911 行。
- `CID-Identifiers.tsv.gz`：已选取 CAS、Nikkaji、ChEMBL、EC、UNII、ChEBI 六类标识并完成校验导入。
- 标识数组使用一个多列部分 GIN 索引；六类单值查找均可命中该索引。

原始 `CID-Synonym-filtered.gz` 暂不导入。其内容混合名称、编号和来源 ID，不具备身份真相质量；未来只在明确的名称检索策略下接收经过筛选的有限别名。

## 5. DSSTox 导入规则

源文件：`DSSToxCCDdump.csv`，正确 CSV 记录数 1,246,399。文件包含字段：

```text
DTXSID, PREFERRED_NAME, CASRN, DTXCID, INCHIKEY, IUPAC_NAME,
SMILES, MOLECULAR_FORMULA, AVERAGE_MASS, MONOISOTOPIC_MASS,
QSAR_READY_SMILES, MS_READY_SMILES, IDENTIFIER
```

### 写入核心表的内容

- `DTXSID` → `dtxsid`
- `PREFERRED_NAME` → `preferred_name`
- `IUPAC_NAME` → `iupac_name`
- 标准化 chemicals 结构一次性计算并物化：`molecular_formula`、`average_mass`、`monoisotopic_mass`、`inchikey`

### 只用于匹配和质量校验

- `CASRN`：通过现有 `cas_numbers[]` 召回 PubChem 候选；不新增第二个 CAS 字段。
- `SMILES`、源 `INCHIKEY`：确认候选结构。
- 源分子式和质量：与 chemicals 结构计算值比较，形成质量统计，不覆盖一致的结构派生值。
- `DTXCID`：只在导入期间用于审计，不进入核心表。它是 DSSTox 的结构命名空间 ID，而 chemicals 自己承担结构表达；永久溯源仍使用校验过哈希的原文件。

### 不导入

- `QSAR_READY_SMILES`、`MS_READY_SMILES`：面向特定用途的派生结构，不是核心结构真相。
- `IDENTIFIER`：平均约 224 字节、最长约 90KB，混有名称、CAS、品牌和实验室编号；不直接作为 synonyms。

### 严格匹配门禁

1. 校验 CAS 格式与校验位，用 CAS GIN 索引召回候选。
2. 只接受 RDKit canonical SMILES 一致，或完整标准 InChIKey 一致的候选。
3. 强匹配必须唯一；多个候选或结构不一致全部跳过并报告。
4. 若多个 DTXSID 最终指向同一 chemical，不把 DTXSID 数组化，也不任意选择；整组保留为身份粒度冲突。
5. 无结构的混合物、聚合物和 UVCB 不强行绑定到某个 PubChem 结构；自主 `chemical_id` 允许它们在证据充分时独立存在。

## 6. 索引边界

当前必要索引：

- `id` 主键。
- `pubchem_cid` 非空记录的唯一部分 B-tree；当前线上迁移期间先用写入约束和低空间 BRIN 过渡，空间释放后补齐。
- 六类 PubChem 标识的多列部分 GIN。
- `dtxsid` 部分唯一 B-tree。
- `inchikey` 部分 B-tree。
- `preferred_name`、`iupac_name` 的部分 trigram GIN，用于用户名称检索。
- `smiles`、`mol`、`morgan_bfp`、`morgan_sfp` 各有一枚 `WHERE mol IS NOT NULL` 的部分索引；只覆盖 1,435,401 个 ORD 可检索结构，不给其余行制造空索引项。

第一版不为分子式和质量建立索引。只有出现明确的过滤/排序查询后，依据真实查询计划增加部分索引，避免给 1.24 亿行表预建无使用证据的索引。

## 7. 当前运行约束

- 根分区空间紧张，所有批量任务保留至少 5GiB 硬保护线。
- 禁止对 1.24 亿行表执行逐行 UPDATE 或无索引关联。
- 批量任务必须可恢复、小批提交，并在执行前检查实际执行计划。
- 使用普通 `VACUUM (ANALYZE)` 回收可复用空间；没有充足额外空间时禁止 `VACUUM FULL`。
- DSSTox 原始文件和当前审计暂存表保留；它们不是第二套领域真相，待用户确认审计结束后再单独清理。
- 旧 `pubchem_worker.py` 和旧 API 仍引用被淘汰的标量 CAS/状态字段，在适配新架构前保持停止。

## 8. RDKit Mol 迁移结果

- 旧 `rdkit.mols` 共 1,435,401 行；按历史 SMILES 精确匹配 1,325,509 行。
- 当前 RDKit 重新序列化后有 5,768 条表达变化，其中 2 条额外命中现有 chemical。
- 剩余 109,890 条结构一对一新增为自主 chemical；这些行的 `pubchem_cid` 与 `pubchem_smiles` 均为空。
- 1,435,401 个 chemical 均已具备 Mol、Morgan 位指纹和稀疏指纹；全量复核缺失为 0，Mol ID 与 chemical ID 均一对一。
- 原物理 `rdkit.mols`、兼容视图和旧 ID 桥均已删除，不再保存第二份结构真相或兼容身份。
- `ord.compound` 的 16,242,914 个结构引用和 `ord.product_compound` 的 2,605,008 个结构引用已直接使用 `chemical_id`，两个外键均已全量验证，删除策略为 `RESTRICT`。
- exact、子结构、相似度查询均已验证命中新索引；极宽子结构查询需在 API 层限制复杂度和结果规模。

旧 `rdkit.mols.id` 已完全退出实体架构。新功能必须直接使用 `chemicals.id`。

## 9. 反应域融合结果（2026-07-19）

- `chemistry.reactions` 已建立 2,428,291 个自主反应身份，并吸收 2,418,635 条 ORD reaction SMILES。
- `chemistry.reaction_chemicals` 已用 `chemical_id` 表达 13,023,629 个唯一的反应—化合物—角色关系；`occurrence_count` 完整保留原 14,149,027 次参与事实。
- `ord.mol_reaction` 已完全删除；检索直接使用 `reaction_chemicals`。
- `rdkit.reactions` 及其旧 ID 桥已完全删除。2,418,635 条有 reaction SMILES 的自主 reaction 已全部物化 RDKit reaction，转换失败为 0。
- `ord.reaction_map` 保留为 ORD 原始事实到自主 reaction 的来源映射，不是领域真相。

详细结构、校验数和边界见 `reactions_dev.md`。

## 10. 下一阶段

1. API 直接使用 `chemicals`、`reactions`、`reaction_chemicals`，不再提供 legacy Mol/Reaction ID 路径。
2. 依据自主表和 ORD 原始事实定义化合物查询、反应查询、用户提交与维护的最小接口。
3. PubChem worker 只承担按需回补；适配自主字段和来源唯一性约束前保持停止。
