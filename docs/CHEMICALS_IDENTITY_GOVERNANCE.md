# chemicals 身份裁定机制规范（Identity Resolution & Reconciliation Spec）

> 状态：**规范冻结版**。本文是行为契约，代码实现以本规范为准；实现与规范冲突时修实现，不改规范。
> 术语：**resolve** 解决"新数据应该去哪里"；**reconcile** 解决"原来分叉的数据，在证据变强以后怎样收敛"。

## 〇、总原则

**宁可暂时一物多行，不允许两物误合一行。重复可以事后收敛，错误合并会污染所有下游数据。**

三个安全阀，缺一不可：

- **AMBIGUOUS 不猜**——证据不足时不选择任何行写入
- **CONFLICT 不吞**——强键冲突时不覆盖、不静默合并
- **MERGE 可追溯**——每次合并落审计凭证，可回答"当时为什么判定"

## 一、系统现状（背景，实测可复核）

化工社（huagongshe）：化学反应/化合物数据平台。核心主表 `chemistry.chemicals`：

- **1.24 亿行**，主体是 PubChem 全量目录导入（有 `pubchem_cid`，大部分行 mol/inchikey/cas 为空）
- 热区行（~140 万）由多条采集链持续补全：PubChem 链（结构/属性）、ChemicalBook 链（市场数据/供应商/上下游）、ORD/DSSTox（学术反应数据）
- 子表：`chemical_pubchem`（PB 详情）、`chemical_cb`（CB 详情）、`name_index`（检索名）、`chemical_supplier_listing`（供应商）等，以 `chemical_id` 外键挂主表

### 身份键覆盖实态

| 键 | 覆盖 | 定位 | 证明同一实体 | 触发自动合并 |
|---|---|---|---|---|
| pubchem_cid | 1.24 亿（近全覆盖） | 是 | 强 | 是 |
| inchikey | 140 万（热区行） | 是 | 跨源结构候选/归一结构判据（不单独授权 destructive merge） | 否 |
| cas_numbers | ~130 万 | 是 | 否 | 否 |
| cb_number | 2.2 万 | 否 | 否 | 否 |

## 二、设计动因

多条入口各自建行、各用一种键查重（SMILES 建行查 inchikey，CAS 占位建行只查 cas_numbers），而主表大部分行在建行时还没有回填强键可比对；回补拿到强键时若盲写任务携带的行 id、不重新定位，同一化合物就会裂成多行，结构数据与市场数据劈在不同行。本规范把定位（resolve）与收敛（reconcile）统一成一套机制，所有入口共用。

## 三、机制规范（行为契约）

### 3.1 候选定位序位

**cid → inchikey → cas**（逐级查候选行，任一级有候选即进入裁定，不跳级）。

- **cb_number 是源标识（source identifier），不参与身份裁定**——它可以辅助找候选，永不决定 chemical identity
- inchikey 定位限定结构行（mol 非空），与既有 SMILES 建行口径一致

### 3.2 五状态模型（resolve_chemical 的返回契约）

```
resolve_chemical(identity_evidence)
→ { status, chemical_id?, candidates?, evidence, reason }
```

| 状态 | 含义 | 调用方义务 |
|---|---|---|
| EXACT | 强键精确命中（如 cid 命中且无冲突信号） | 写入 chemical_id |
| EQUIVALENT | 证据可确定等价（如 ik 匹配且无 cid 冲突） | 写入 chemical_id |
| AMBIGUOUS | 有多个候选，证据不足 | **不建行、不写任何行的身份字段**；外部数据入 staging/queue，待结构判据或源站重定向后 re-resolve |
| CONFLICT | 强键互相冲突（如新数据 ik=B 而命中行 ik=A；或两侧不同非空 cid） | 不覆盖不合并；字段版本由权威 enrichment（PubChem）决定，记录 conflict |
| NEW | 无任何候选 | INSERT 占位行，进门键随行落，advisory 锁键=已知最强键 |

**契约要点：resolve_chemical 不承诺"一定选出一行"。** 返回不了确定行是合法且预期的结果。

### 3.3 裁定规则

- **EXACT**：cid 命中即 EXACT；但若命中行已有非空 ik 而新数据给出不同 ik → 降为 CONFLICT（禁止 coalesce 默默吞掉）
- **EQUIVALENT**：ik 命中且不触发 cid 冲突约束。**硬约束：ik 不能凌驾于两个已存在且不同的非空 CID**——主数据粒度保留 PubChem entity granularity，两行各有不同非空 cid 而共享 ik 时，不得因 ik 相同自动吞并，进 CONFLICT 复核
- **AMBIGUOUS**：cas 多命中且无结构判据（ik/cid）时**禁止用"最热行"选择写入目标**。热度分只用于 survivor selection（3.4），永不用于 identity judgement
- **NEW**：全 miss 才建行

### 3.4 survivor selection 与 identity judgement 分离

- **identity judgement**（是否同一实体）：只由 3.2/3.3 的证据规则决定
- **survivor selection**（合并时保留哪一行）：**仅在已证明等价之后**生效，可用热度分（cb/preferred_name/cid 齐全度、结构行优先）

### 3.5 merge gate（can_merge 硬闸）

任何 absorb 合并必须先过独立函数 `can_merge(source, target)`：

**判定优先级（先判先赢）**：CID 一致性先于 IK 一致性判定——两侧 CID
一致（行上值，或行空侧由入站 `evidence_cid` 补齐后一致）即视为
entity proof，直接放行；此后的 IK 差异**不参与判定**，只在
identity_merge_log 的两侧快照里留痕。反向不成立：IK 一致不能补 CID
证据的缺（见下）。

**自动允许**：
- 两行存在一致的非空 CID（行上值，或行空侧由入站 `evidence_cid` 补齐后一致）——entity proof 唯一来源

**禁止自动合并**：
- CID A ≠ CID B（两侧非空，含 evidence_cid 与行上 CID 冲突）——即使 CAS 相同
- IK A ≠ IK B（两侧非空）——仅在两侧 CID 未能构成 entity proof（任一侧 CID 为空）时才到达此判定
- **仅 same InChIKey 而无 CID entity proof**：返回 blocked，reason=`same_inchikey_without_entity_proof`（双方无证据冲突，只是证据不足，不是 CONFLICT）。Standard InChI 对部分互变异构归一，同 IK 可对应多个 PubChem entity（实测 151 组同 IK + 不同非空 CID），因此 IK 不单独授权 destructive merge
- CAS 相同：永远只是 candidate evidence，不构成 merge evidence
- CB 相同：同理
- `evidence_ik` 仅用于候选定位/结构一致性辅助，单独不得授权合并

**candidate equivalence ≠ entity equivalence**（总则）

### 3.6 absorb 前置条件（全部存在才允许跑批量合并）

1. **chemical_id 引用表注册机制**：代码集中声明 `CHEMICAL_REFERENCE_TABLES`；测试从 PostgreSQL FK 元数据反查所有 FK→chemistry.chemicals(id) 的表，断言全部在 registry 内。非正式 FK 的引用（如 ord.compound）显式列入。禁止靠记忆维护"目前一共 6 张"
2. **identity_merge_log 落表**（任何批量 absorb 前必须存在，上线阻断项）：merge_id / source_id / target_id / reason / evidence / source_keys_before / target_keys_before / merged_at / trigger/job_id；批量规模下两侧主表字段 snapshot 存 JSONB
3. **chemical_identity_redirect 表**（old_chemical_id / canonical_chemical_id / merge_log_id / created_at）：DELETE 主行可以，身份历史不删。异步 worker 持旧 id 执行时经 `canonicalize_id(old)` → 新 id，不报错、不重建、不丢数据。merge_log 管审计，redirect 管运行时兼容，职责不同
4. **name_index 改指去重**：占位行与目标行同名条目合并去重，不留重复行

### 3.7 写入策略

**一期为 non-destructive enrichment**：默认只补空（coalesce），非空冲突记录而不覆盖。字段级 source priority / provenance 治理不属于本阶段——这是阶段性策略，**不是永久字段治理原则**。

### 3.8 并发模型（设计选择）

**最终一致性（eventual identity consistency），不做即时全局唯一**。SMILES 锁 ik、CAS 锁 cas，毫秒级双建窗口存在；不为此引入全局锁/分布式锁/identity claim 表。要求的是：不会无限分叉 + 获得强身份信息后确定性收敛。允许短时重复，不允许无证据误合。

## 四、实现现状与差距

**已实现**：

- `resolve_chemical()` 五状态 resolver（EXACT / EQUIVALENT / AMBIGUOUS / CONFLICT / NEW），advisory 锁
- 无 hottest-row 身份猜测（AMBIGUOUS 不猜、CONFLICT 不吞）
- `can_merge()` 独立硬闸（唯一 entity proof = 一致非空 CID）
- `absorb()` 强制过 `can_merge()`，不过闸抛 `MergeBlockedError`（fail-closed）
- 引用表 registry `CHEMICAL_REFERENCE_TABLES` + per-table merge strategy（REKEY_MANY / MERGE_ONE_TO_ONE / DEDUPE_REKEY）+ PG FK 元数据覆盖断言
- `maintenance.identity_merge_log`（JSONB snapshot 审计）
- `maintenance.chemical_identity_redirect` + `canonicalize_id()` 运行时旧 id 兼容
- name_index 改指去重（collision-aware rekey）
- 三入口接入（cb.py / workapi.py / reactions.py）

**数据库实际 schema**：`maintenance.identity_merge_log`、`maintenance.chemical_identity_redirect`（均位于 maintenance schema，非 chemistry schema）。

**与规范的差距**：无已知实现性差距。

## 五、不变式（机制前提）

- cid 是源内区分键、ik 是跨源判据、cas 是弱键(1→N)、cb 是印记不是键
- 一 CAS→N CID 合法共享 cb 号；主词条选择权在源站（CAS 页重定向），本地不选主
- 结构变更须拍板后执行；大表操作必须 statement_timeout 放宽+断点续跑

## 六、流程总图

```
                外部数据
                    │
                    ▼
             normalize keys
                    │
                    ▼
           resolve candidates
         CID → IK → CAS → source id
                    │
       ┌────────────┼─────────────┐
       ▼            ▼             ▼
    EXACT       AMBIGUOUS       NEW
       │            │             │
       │            │             ▼
       │            │      INSERT placeholder
       │            │      strongest-key lock
       │            │
       │       staging / wait
       │            │
       ▼            ▼
      enrichment → re-resolve
                    │
            target changed?
                    │ yes
                    ▼
               can_merge()
               │        │
             SAFE    CONFLICT
               │        │
               ▼        ▼
            absorb   log/hold
               │
               ├── child refs migrate (registry)
               ├── name dedupe
               ├── key union
               ├── merge_log (JSONB snapshot)
               ├── redirect (old → canonical)
               └── old row delete
```
