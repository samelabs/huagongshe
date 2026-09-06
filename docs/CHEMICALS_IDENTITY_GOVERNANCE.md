# chemicals 身份裁定机制规范（Identity Resolution & Reconciliation Spec）

> 状态：**规范冻结版**。本文是行为契约，代码实现以本规范为准；实现与规范冲突时修实现，不改规范。
> 评审背景：初版方案经外部评审（codex）给出"有条件通过"，本文已吸收全部评审意见并冻结规则。
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

## 二、现状问题（历史成因）

| 入口 | 查重键 | 结果 |
|---|---|---|
| SMILES 建行（`api/reactions.py`） | inchikey+advisory 锁 | PB 全量行大多 mol 为空 → 撞不上 → 建新行；锁引入前历史缝遗留 41 组重复 |
| CAS 占位建行（`api/services/cb.py:531`） | 仅 cas_numbers | 不查 inchikey/cid → 388 组双行 |
| 历史迁移自治行（07-19 RDKit 吸收） | 无键（孤儿结构直接 INSERT） | 0902 PB 回补 cid 后撞全量行 → 2,866 组 cid 双行 |

**共性根因**：建行时行上没有已回填的强键可比对；回补拿到强键时盲写 job 携带的行 id，不重定位。表现为：同一化合物裂成多行，结构数据与市场数据劈在不同行。

**实测数据（生产库）**：

- 2,866 组 cid 双行：逐组字段比对，名差异 2,476 组为单侧空、220 组为同物异写；分子量差>0.5 的 0 组；inchikey 差异全部为低行空——未发现实质数据冲突。本质是 catalog 行与自治富化行的 identity convergence，非疑似重复
- 2,866 组被引用面：reaction_chemicals 3,035（双侧）、ord.compound 同量级、chemical_cb 27、supplier_listing 1,062 在低侧——双侧均有引用，只能合并不能删
- 388 组 cas 双行 + 41 组 SMILES 重复
- sqlite 导入预演（采样 8,000）：cas 命中单行 50.3% / 多行 5.1% / miss 44.5%。预备导入 89.6 万 cas，5.1% 多行 ≈ 4.6 万——**这些不是需要"聪明选择"的 4.6 万次，而是机制应明确识别出的 4.6 万个 AMBIGUOUS**

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

### 3.5 merge gate（can_merge 硬闸，0906 终审收紧版）

任何 absorb 合并必须先过独立函数 `can_merge(source, target)`：

**自动允许**：
- 两行存在一致的非空 CID（行上值，或行空侧由入站 `evidence_cid` 补齐后一致）——entity proof 唯一来源

**禁止自动合并**：
- CID A ≠ CID B（两侧非空，含 evidence_cid 与行上 CID 冲突）——即使 CAS 相同
- IK A ≠ IK B（两侧非空）
- **仅 same InChIKey 而无 CID entity proof**：返回 blocked，reason=`same_inchikey_without_entity_proof`（双方无证据冲突，只是证据不足，不是 CONFLICT）。Standard InChI 对部分互变异构归一，同 IK 可对应多个 PubChem entity（实测 151 组同 IK + 不同非空 CID），因此 IK 不单独授权 destructive merge
- CAS 相同：永远只是 candidate evidence，不构成 merge evidence
- CB 相同：同理
- `evidence_ik` 仅用于候选定位/结构一致性辅助，单独不得授权合并

**candidate equivalence ≠ entity equivalence**（0906 终审新增总则）

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

**已实现**（工作区暂存 +370/−29，**不作为正式机制版本 commit**——正式提交在 AMBIGUOUS 分支与 can_merge 闸加入之后，避免 git 历史出现"统一 resolver 已上线但会静默猜测/冲突吞并"的中间版本）：

- `resolve_chemical()` 定位/建行 + advisory 锁
- `absorb_placeholder()` 键并集+子表改指+DELETE
- 三入口接入（cb.py / workapi.py / reactions.py）

**与规范的差距（即代码改造清单）**：

| # | 项 | 对应规范 |
|---|---|---|
| A | 删除 `_pick_from_multi` 的无证据 hottest-row 裁定 | 3.3 |
| B | 引入 AMBIGUOUS / CONFLICT 返回路径 | 3.2 |
| C | `can_merge()` 独立硬闸 | 3.5 |
| D | `absorb()` 必须先过 `can_merge()` | 3.5 |
| E | `chemical_identity_redirect` 表 + canonicalize_id | 3.6.3 |
| F | `identity_merge_log` 表（含 JSONB snapshot） | 3.6.2 |
| G | 引用表 registry + PG FK 元数据覆盖测试 | 3.6.1 |
| H | name_index 改指去重 | 3.6.4 |
| I | 2,866 组 can_merge dry-run（输出 SAFE/CONFLICT 分布，要求 SAFE≈2866/CONFLICT=0 才开自动） | 3.5 |
| J | 41 组历史 SMILES 重复 reconciliation（RDKit 重算 ik → 过 merge gate） | 3.1 |

## 五、执行计划（冻结顺序）

1. **resolver 上线，关闭 destructive absorb**——先停止无序建行；absorb 删除面在 merge 基建完成前禁用
2. **merge 基础设施**：引用表注册+FK 断言测试、name_index 去重、identity_merge_log、chemical_identity_redirect
3. **2,866 组 can_merge dry-run**：输出 SAFE/CONFLICT，不直接执行
4. **SAFE 组断点 absorb**（逐组断点跑，凭证落 merge_log，redirect 生效）
5. **41 组 SMILES 历史重复**走同一 reconciliation
6. **sqlite 89.6 万导入**：单 CAS 多命中一律 AMBIGUOUS，不允许 hottest-row guessing；AMBIGUOUS 数据入队等结构判据
7. **388 组 CAS 双行**：不专项强行消重，不按 CAS 批量合并；后续任一侧获得 CID entity proof（IK 仅辅助）时进入统一 reconciliation，符合 merge gate 的自动吸收，其余保持并存
8. **歧义 review**：量级起来后加，非首发阻断项

## 六、不变式（既往裁定，作为机制前提）

- cid 是源内区分键、ik 是跨源判据、cas 是弱键(1→N)、cb 是印记不是键（0830 裁定）
- 一 CAS→N CID 合法共享 cb 号；主词条选择权在源站（CAS 页重定向），本地不选主
- 结构变更须拍板后执行；大表操作必须 statement_timeout 放宽+断点续跑

## 七、流程总图

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
