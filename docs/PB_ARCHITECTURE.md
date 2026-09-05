# PB 链数据架构（PubChem，2026-09-05 体检定版）

> PB 链 2026-09-01 整记录化收口后运行稳定。本文记录体检结论与已知边界，
> 未做结构变更（体检发现的三个小毛病记录在案，按需再动）。

## 1. 采集与解析

- **唯一数据请求**: PUG View 整包 `GET /data/compound/{cid}/JSON`（gzip，
  实测 1.8MB→185KB）。resolve/properties/synonyms/逐heading 全部退役
- 解析 `worker/whole_record.py::parse_whole_record`: Section 树按 TOCHeading
  精确匹配递归。**缺 heading = 该化合物无数据，跳过不造空壳**
  （空置率高是"没数据不编"，不是坏）
- 值取法: Number[0] / StringWithMarkup[].String / DateISO8601[0]，带引用编号
- 错误形态（`worker/pubchem.py`）: 单趟制无重试; miss(404)=None /
  拒绝(302跳转|封禁页|4xx)=refused 终态 / 5xx|网络错=error 回队
- 速率: 自适应 3-5 rps + X-Throttling-Control 反馈; 头缺失=unknown 不回满速

## 2. 存储（chemistry.chemical_pubchem, 319,085 行）

- typed 数值列: xlogp/tpsa/complexity/hbd/hba/rotatable/heavy/charge（前端 COMPUTED 格直读）
- 分区 jsonb（EvidenceBlock 形态 `{entries: {path: [{value,unit?,references}]}}`）:
  physical_properties/ghs_classification/hazards/safety_measures/toxicity/
  regulatory/pharmacology/uses_and_manufacturing/identifier_evidence
- 结构化列: ghs_codes `{h_code[],p_code[],pictogram[],signal_word}` /
  external_ids / exp_props / exp_limits / reactivity / source_references
- 主表同步: Descriptor 叶子（IUPAC/InChI/InChIKey/SMILES/分子式）+ cas_numbers + synonyms

## 3. 前端映射（web/components/ChemicalKnowledge.tsx）

- COMPUTED 格 = typed 数值列直读，空值不渲染
- 证据区 = 8 个 EvidenceBlock 通用渲染: path 末段做标签 / 过滤 references /
  每区截 12 条 / 每值截 6 项 / 空块整块不渲染
- queued=补全中提示; 无 cid=不渲染不宣称失败

## 4. 已知边界（记录在案，未动）

1. **physical_properties 混入 Computed 分支**: PubChem 把 Computed Properties 挂在
   "Chemical and Physical Properties" 子树下，实测样本"实验性质"区出现
   Computed Properties > Exact Mass，与 COMPUTED 格内容重复。~~修法（若要做）~~
   **0905 已修**: whole_record.py 物理子树剔除 Computed 分支 + 存量 161,784 行剥净
   （bak: chemical_pubchem_physical_0905_bak）
2. **exp_props 前端呈现缺失（0905 定性修正）**: 非死列——数据是 PB 实验性质
   canonical 键+数值化（bp/density 带 v/unit），前端零引用是呈现欠账不是数据无值。
   数据源→数据架构→前端展现：前端未作明确改动不应作为后端结构决策依据。
   列保留，呈现属产品决策待做
3. **exp_props.unit 脏（0905 已清）**: 二轮清洗 1,130 修正/875 置null/137 年份v置null，
   终扫残留=0（bak: chemical_pubchem_expprops_clean2_0905_bak, 1,076 行）
   引文年份守卫已双链上线（caslib/parse_cpp.py + worker/whole_record.py，
   CitationGuardTests 回归）

## 5. 与 CB 链的关系

- CB 记录表（chemical_cb）与 PB 记录表（chemical_pubchem）分立，互不引用
- 主表 chemicals 是汇聚点: PB 供 Descriptor/同义词/CAS 集合，CB 供
  cb_number/中文名/供应商; 补缺方向 coalesce（PB 先占 CB 补缺，反之亦然按列定）
