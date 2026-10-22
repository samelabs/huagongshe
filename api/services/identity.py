"""chemicals 身份机制 (规范冻结版)。

规范: docs/CHEMICALS_IDENTITY_GOVERNANCE.md — 实现与规范冲突时修实现。

核心契约:
- resolve_chemical(identity_evidence) → ResolveResult{status, chemical_id?,
  candidates?, evidence, reason}。五状态: EXACT / EQUIVALENT / AMBIGUOUS /
  CONFLICT / NEW。**不承诺"一定选出一行"** — AMBIGUOUS/CONFLICT 是合法返回。
- 候选定位序位: cid → inchikey(mol非空) → cas。cb_number 是源标识,
  永不参与身份(不定位、不裁_equiv、不建 merge 证据)。
- 硬原则: AMBIGUOUS 不猜(禁止无证据 hottest-row 选择写入目标),
  CONFLICT 不吞(强键冲突不覆盖不合并), NEW 才建行。
- can_merge(): 独立硬闸 。destructive merge 唯一
  entity proof = 一致非空 CID: 同 CID 可并; 不同非空 CID 禁止;
  不同非空 IK 禁止; 仅同 IK 而无 CID entity proof 禁止
  (same_inchikey_without_entity_proof); CAS/CB 单独永不构成 merge 证据;
  evidence_ik 仅辅助定位/结构一致性记录, 不单独放行。
- absorb(): 公开入口, 内部强制过 can_merge(), 不过闸抛 MergeBlockedError;
  真正执行删除的是 _absorb_verified(), 不对外导出 — 调用方无法绕闸。
- survivor selection 与 identity judgement 分离: 热度分只在已证明等价后
  用于选保留行(_survivor_pick), 永不用于归属。
- absorb 前置基建(规范3.6): 引用表注册 CHEMICAL_REFERENCE_TABLES(测试用
  PG FK 元数据断言全覆盖)、identity_merge_log(JSONB snapshot)、
  chemical_identity_redirect(旧id→canonical, canonicalize_id 查询)、
  name_index 改指去重。

消费者: 被动触发(搜索/详情), sqlite导入(未启动), 后续一切入表。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 引用表注册 (规范3.6.1): 所有含 chemical_id 指向 chemistry.chemicals 的表。
# 硬 FK 的表由测试从 PG 元数据反查断言全覆盖(见 tests/test_identity.py);
# 本清单必须与库内实际 FK 集一致, 漏一张测试即失败。
# canary 熔断后升级为带 merge strategy 的 registry (非纯表名清单):
# REKEY_MANY — 1:N 引用, 直接 UPDATE chemical_id = survivor
# MERGE_ONE_TO_ONE — chemical_id 为 PK/UNIQUE 前缀的 1:1 子表,
# 两侧都有行时先 coalesce 补 survivor 空值再 DELETE old 行
# (canary cid2273 撞 chemical_pubchem_pkey 实证)
# DEDUPE_REKEY — 复合 PK 含 chemical_id 且行有独立语义(name_index),
# 先删键重合行再改指
# 策略完整性由测试锁定: 每张 FK 表必须有策略, 且 1:1 表与 PG 约束实查一致。
ReferenceStrategy = tuple[str, str, dict]  # (schema, table, cfg)
CHEMICAL_REFERENCE_TABLES: tuple[ReferenceStrategy, ...] = (
    ("chemistry", "chemical_pubchem",
     {"strategy": "MERGE_ONE_TO_ONE", "merge_cols": (
        "record_title", "record_description", "xlogp",
        "topological_polar_surface_area", "complexity",
        "hbond_donor_count", "hbond_acceptor_count",
        "rotatable_bond_count", "heavy_atom_count", "formal_charge",
        "computed_properties", "physical_properties", "ghs_classification",
        "hazards", "safety_measures", "toxicity", "regulatory",
        "pharmacology", "uses_and_manufacturing", "identifier_evidence",
        "source_references", "pubchem_created_on", "pubchem_modified_on",
        "external_ids", "ghs_codes", "reactivity"),
      # JSONB 载荷列默认值 '{}'(upsert_details 的 obj() 空包
      # 形态)视为"空"—— survivor '{}' 时吸收对方非空证据, 不再被空对象挡住。
      "jsonb_merge_cols": (
        "computed_properties", "physical_properties", "ghs_classification",
        "hazards", "safety_measures", "toxicity", "regulatory",
        "pharmacology", "uses_and_manufacturing", "identifier_evidence",
        "source_references", "external_ids", "ghs_codes", "reactivity")}),
    ("chemistry", "chemical_cb",
     {"strategy": "MERGE_ONE_TO_ONE", "key_extra": "locale",
      # source grain: collision 键收窄 — cb_number 进比对(同 cb+locale 才
      # 合并; 不同 cb 各自保留), 但 payload 补空白名单不含 cb_number(身份列)。
      "key_extra2": "cb_number", "merge_cols": (
        "cas_number", "entry", "last_status"),
      "jsonb_merge_cols": ("entry",)}),
    ("chemistry", "name_index",
     {"strategy": "DEDUPE_REKEY", "dedupe_key": ("source", "kind", "normalized"),
      "merge_cols": ()}),
    ("chemistry", "chemical_supplier_listing",
     {"strategy": "DEDUPE_REKEY", "dedupe_key": ("cbsid",),
      "merge_cols": ("purity", "pack_price", "remark")}),
    ("chemistry", "reaction_chemicals",
     {"strategy": "DEDUPE_REKEY", "dedupe_key": ("reaction_id", "role"),
      "merge_cols": ("occurrence_count", "amount_value", "amount_unit",
                     "equivalents", "concentration_value", "concentration_unit",
                     "yield_percent")}),
    ("community", "chemical_follows",
     {"strategy": "DEDUPE_REKEY", "dedupe_key": ("user_id",), "merge_cols": ()}),
    ("community", "note_chemicals",
     {"strategy": "DEDUPE_REKEY", "dedupe_key": ("note_id",), "merge_cols": ()}),
    ("community", "notifications", {"strategy": "REKEY_MANY"}),
    ("maintenance", "cas_jobs",
     # 活动任务 dedupe_key 前缀带 chemical_id — 改指时同步
     # rekey, 否则 survivor 侧新入列撞不上旧前缀 → 同任务双活。前缀清单
     # 与 cb._dedupe_key / enrichment.enqueue_job 的格式约定同源维护。
     {"strategy": "REKEY_MANY", "rekey_dedupe_prefixes": ("cas",)}),
    ("maintenance", "pubchem_jobs",
     {"strategy": "REKEY_MANY", "rekey_dedupe_prefixes": ("cid",)}),
    ("ord", "compound", {"strategy": "REKEY_MANY"}),
    ("ord", "product_compound", {"strategy": "REKEY_MANY"}),
)

# 1:1 子表允许 coalesce 的业务列(显式白名单; PK/chemical_id/created_at/
# updated_at/fetched_at 等身份审计列绝不合并)。JSONB 只做顶层 survivor-null
# 才整体采用, 不做深度 merge; 两侧非空不同 → 保留 survivor。
# 收口: jsonb_merge_cols 里的列 '{}'(空对象)也视为空 —
# upsert_details 对缺席段落写 '{}', 老语义下 survivor 的空包会挡住对方的
# 非空证据, 对方整行删除后证据直接蒸发。
ONE_TO_ONE_MERGE_COLUMNS: dict[tuple[str, str], tuple[str, ...]] = {
    (sch, tbl): tuple(cfg.get("merge_cols", ()))
    for sch, tbl, cfg in CHEMICAL_REFERENCE_TABLES
    if cfg["strategy"] == "MERGE_ONE_TO_ONE"
}

# ---------------------------------------------------------------------------
# absorb 主表核心字段迁移清单。
# 空值语义按列类型: 标量 NULL 为空; 数组 NULL/空数组为空; synonyms '{}'
# 为空。双侧非空且不同 → survivor 保留 + merge_log.evidence.core_conflicts
# 留痕(CORE_TRACE_COLUMNS)。mol/指纹是可再生的结构载体, 只补空不留痕。
# ---------------------------------------------------------------------------
_CORE_SCALAR_COLUMNS = (
    "pubchem_cid", "inchikey", "pubchem_smiles", "smiles", "iupac_name",
    "molecular_formula", "average_mass", "monoisotopic_mass", "dtxsid",
)
_CORE_ARRAY_COLUMNS = (
    "nikkaji_numbers", "chembl_ids", "ec_numbers", "unii_codes", "chebi_ids",
)
_CORE_JSONB_COLUMNS = ("synonyms",)
_CORE_RAW_COALESCE_COLUMNS = ("mol", "morgan_bfp", "morgan_sfp")
CORE_TRACE_COLUMNS = _CORE_SCALAR_COLUMNS + _CORE_ARRAY_COLUMNS + _CORE_JSONB_COLUMNS


def _core_value_empty(col: str, value: Any) -> bool:
    if value is None:
        return True
    if col in _CORE_ARRAY_COLUMNS:
        return len(value) == 0
    if col in _CORE_JSONB_COLUMNS:
        return not value  # {} / 空列表
    return False


def _core_conflicts(surv_snap: dict, absorbed_snap: dict) -> dict[str, dict]:
    """双侧核心字段均非空且不同 → {col: {survivor, absorbed}} 留痕材料。"""
    out: dict[str, dict] = {}
    for col in CORE_TRACE_COLUMNS:
        s, a = surv_snap.get(col), absorbed_snap.get(col)
        if _core_value_empty(col, s) or _core_value_empty(col, a):
            continue
        if s != a:
            out[col] = {"survivor": s, "absorbed": a}
    return out


def reference_tables() -> tuple[tuple[str, str], ...]:
    """兼容视图: (schema, table) 序列 — 供测试/工具遍历。"""
    return tuple((s, t) for s, t, _ in CHEMICAL_REFERENCE_TABLES)


def reference_table_strategies() -> dict[tuple[str, str], str]:
    """(schema, table) -> strategy。约束-策略一致性测试用。"""
    return {(s, t): cfg["strategy"] for s, t, cfg in CHEMICAL_REFERENCE_TABLES}


def reference_dedupe_keys() -> dict[tuple[str, str], tuple[str, ...]]:
    """(schema, table) -> dedupe_key 列。约束-策略一致性测试用。"""
    return {(s, t): tuple(cfg.get("dedupe_key", ()))
            for s, t, cfg in CHEMICAL_REFERENCE_TABLES}


class MergeBlockedError(RuntimeError):
    """can_merge() 未通过仍尝试 absorb — 规范禁止的路径。"""


@dataclass
class ResolveResult:
    status: str                    # EXACT / EQUIVALENT / AMBIGUOUS / CONFLICT / NEW
    chemical_id: int | None = None
    candidates: list[int] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


def _lock_key(*keys: str | None) -> str:
    """advisory 锁键 = 已知最强键(定位序位序取第一个非空)。"""
    for k in keys:
        if k:
            return k
    raise ValueError("resolve_chemical: 无任何身份键")


# ---------------------------------------------------------------------------
# can_merge: merge gate (规范3.5) — absorb 唯一放行依据
# ---------------------------------------------------------------------------

async def can_merge(db: Any, *, source_id: int, target_id: int,
                    evidence_ik: str | None = None,
                    evidence_cid: int | None = None) -> tuple[bool, str]:
    """硬闸判定 。返回 (可否合并, reason)。

    entity proof 唯一来源 = 两行(或行+入站证据)存在一致的非空 pubchem_cid。
    Standard InChIKey 对互变异构归一, 同 IK 可对应多个 PubChem entity
    (实测 151 组: same IK + 不同非空 CID), 因此 IK 不再单独授权合并:

    ALLOW: 两行相同非空 CID (行上值, 或行空侧由 evidence_cid 补齐后一致)。
    BLOCK: 两行不同非空 CID (cid-conflict, 含 evidence_cid 与行上 CID 冲突)。
    BLOCK: 不同非空 IK (ik-conflict)。
    BLOCK: 仅 same IK 无 CID entity proof — reason=same_inchikey_without_entity_proof
           (双方无证据冲突, 只是 merge evidence 不足; 不是 CONFLICT)。
    CAS/CB 相同永不构成证据 (不查不判)。

    evidence_ik: 仅候选定位/结构一致性辅助, 本闸内不作为放行依据
    (保留参数为调用面兼容 + 记录到 reason 供审计)。
    """
    if source_id == target_id:
        return True, "same-row"
    rows = (await db.execute(text("""
        SELECT id, pubchem_cid, inchikey FROM chemistry.chemicals
        WHERE id IN (:s, :t)
    """), {"s": source_id, "t": target_id})).mappings().all()
    by_id = {r["id"]: r for r in rows}
    if len(by_id) != 2:
        return False, f"row-missing: found {len(by_id)}/2"
    src, tgt = by_id.get(source_id), by_id.get(target_id)

    # CID 冲突检查先行 (行上值与 evidence_cid 一并纳入, 冲突即 BLOCK)
    src_cid = src["pubchem_cid"] if src["pubchem_cid"] is not None else evidence_cid
    tgt_cid = tgt["pubchem_cid"]
    if src_cid is not None and tgt_cid is not None:
        if src_cid != tgt_cid:
            return False, f"cid-conflict: {src_cid} != {tgt_cid}"
        return True, f"same-cid:{src_cid}"

    # IK 冲突检查 (不同非空 IK 一定是不同结构)
    src_ik = src["inchikey"] if src["inchikey"] is not None else evidence_ik
    if src_ik is not None and tgt["inchikey"] is not None and src_ik != tgt["inchikey"]:
        return False, f"ik-conflict: {src_ik} != {tgt['inchikey']}"

    # 到此处: 无 CID entity proof。仅 same IK 不足以授权 destructive merge。
    if src_ik is not None and tgt["inchikey"] is not None and src_ik == tgt["inchikey"]:
        return False, "same_inchikey_without_entity_proof"
    return False, "no-strong-evidence"


# ---------------------------------------------------------------------------
# resolve: 定位 +(规范3.1–3.3)
# ---------------------------------------------------------------------------

async def _row_keys(db: Any, row_id: int) -> dict[str, Any]:
    r = (await db.execute(text("""
        SELECT pubchem_cid, inchikey FROM chemistry.chemicals WHERE id = :id
    """), {"id": row_id})).mappings().first()
    return dict(r) if r else {}


async def resolve_chemical(
    db: Any, *,
    cid: int | None = None,
    inchikey: str | None = None,
    cas: str | None = None,
    create: bool = True,
) -> ResolveResult:
    """定位//建行单一入口 (规范3.2 五状态契约)。

    EXACT cid 命中(且无冲突信号); ik 命中且行 cid 与输入 cid 一致
    EQUIVALENT ik 命中(结构行)且不触发 cid 冲突约束
    AMBIGUOUS cas 多候选且无结构判据 — 不建行、不写任何行
    CONFLICT 强键冲突(cid vs cid / cid vs ik / ik vs ik)
    NEW 全 miss 且 create=True → INSERT 占位行
    """
    lock = _lock_key(str(cid) if cid else None, inchikey, cas)
    await db.execute(text(
        "SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"
    ), {"k": f"chem:{lock}"})

    # --- 定位序位 1: pubchem_cid ---
    if cid:
        rows = (await db.execute(text("""
            SELECT id, inchikey, (mol IS NOT NULL) AS has_mol
            FROM chemistry.chemicals WHERE pubchem_cid = :cid
        """), {"cid": cid})).mappings().all()
        if rows:
            # 3.3: 新数据明确给出 ik 而命中行已带不同非空 ik → CONFLICT
            if inchikey and any(
                r["inchikey"] is not None and r["inchikey"] != inchikey for r in rows
            ):
                return ResolveResult(
                    "CONFLICT", candidates=[int(r["id"]) for r in rows],
                    evidence={"cid": cid, "input_ik": inchikey},
                    reason="input-ik-conflicts-with-cid-row-ik")
            # 3.4 分离: 已证明等价(cid 同)后才用 survivor 分 — 结构行优先
            picked = sorted(rows, key=lambda r: (not r["has_mol"], r["id"]))[0]
            return ResolveResult(
                "EXACT", chemical_id=int(picked["id"]),
                candidates=[int(r["id"]) for r in rows],
                evidence={"cid": cid}, reason="cid-hit")

    # --- 定位序位 2: inchikey (结构行; cb 不参与) ---
    if inchikey:
        rows = (await db.execute(text("""
            SELECT id, pubchem_cid FROM chemistry.chemicals
            WHERE inchikey = :ik AND mol IS NOT NULL
        """), {"ik": inchikey})).mappings().all()
        if rows:
            # 3.3 硬约束: ik 不得凌驾于两个已存在且不同的非空 CID。
            # 补分支: ≥2 行同 IK 且同挂另一个 CID(≠输入 cid)同样
            # 是强键互斥 — 旧判法只在 len(rows)==1 时核对输入 cid, 多行
            # 同挂时会静默 EQUIVALENT, 产生无告警的分叉。
            cids = {r["pubchem_cid"] for r in rows if r["pubchem_cid"] is not None}
            conflict = (
                len(cids) > 1
                or (cid is not None and any(c != cid for c in cids))
            )
            if conflict:
                return ResolveResult(
                    "CONFLICT", candidates=[int(r["id"]) for r in rows],
                    evidence={"ik": inchikey, "input_cid": cid, "row_cids": sorted(map(str, cids))},
                    reason="ik-cannot-override-distinct-nonnull-cids")
            picked = min(int(r["id"]) for r in rows)
            return ResolveResult(
                "EQUIVALENT", chemical_id=picked,
                candidates=[int(r["id"]) for r in rows],
                evidence={"ik": inchikey}, reason="ik-structural-hit")

    # --- 定位序位 3: cas (弱键; 只找候选, 单行=EQUIVALENT, 多行需判据) ---
    if cas:
        rows = [int(r) for r in (await db.execute(text("""
            SELECT id FROM chemistry.chemicals
            WHERE cas_numbers @> ARRAY[:cas] ORDER BY id
        """), {"cas": cas})).scalars()]
        if rows:
            if len(rows) == 1:
                # 单候选命中必须核对强键互斥 — 输入 cid/ik 与行上
                # 非空 cid/ik 相斥即 CONFLICT(此前 cas-unique-hit 直接
                # EQUIVALENT, 强键冲突被弱键吞掉)。强键一致或缺席 → 原行为。
                r = (await db.execute(text("""
                    SELECT pubchem_cid, inchikey FROM chemistry.chemicals
                    WHERE id = :id
                """), {"id": rows[0]})).mappings().first()
                if r is not None:
                    if (cid is not None and r["pubchem_cid"] is not None
                            and r["pubchem_cid"] != cid):
                        return ResolveResult(
                            "CONFLICT", candidates=rows,
                            evidence={"cas": cas, "input_cid": cid,
                                      "row_cid": r["pubchem_cid"]},
                            reason="cas-unique-cid-conflict")
                    if (inchikey is not None and r["inchikey"] is not None
                            and r["inchikey"] != inchikey):
                        return ResolveResult(
                            "CONFLICT", candidates=rows,
                            evidence={"cas": cas, "input_ik": inchikey,
                                      "row_ik": r["inchikey"]},
                            reason="cas-unique-ik-conflict")
                return ResolveResult(
                    "EQUIVALENT", chemical_id=rows[0], candidates=rows,
                    evidence={"cas": cas}, reason="cas-unique-hit")
            # 多候选: 唯一合法判据 = 输入 ik 命中其中一行(结构行)
            if inchikey:
                hit = (await db.execute(text("""
                    SELECT id FROM chemistry.chemicals
                    WHERE id = ANY(:ids) AND inchikey = :ik AND mol IS NOT NULL
                    ORDER BY id LIMIT 1
                """), {"ids": rows, "ik": inchikey})).scalar()
                if hit is not None:
                    return ResolveResult(
                        "EQUIVALENT", chemical_id=int(hit), candidates=rows,
                        evidence={"cas": cas, "ik": inchikey},
                        reason="cas-multi-ik-adjudicated")
            # 3.3: 无结构判据 → AMBIGUOUS。禁止 hottest-row 写入(规范3.3)。
            # 调用方义务: 数据进 staging/queue 等结构判据后 re-resolve。
            return ResolveResult(
                "AMBIGUOUS", candidates=rows,
                evidence={"cas": cas, "has_ik": bool(inchikey)},
                reason="cas-multi-no-structural-evidence")

    # --- 全 miss: NEW ---
    if not create:
        return ResolveResult("NEW", evidence={"cid": cid, "ik": inchikey, "cas": cas},
                             reason="no-candidates-create-disabled")
    cols: list[str] = ["created_at", "updated_at"]
    vals: list[str] = ["now()", "now()"]
    params: dict[str, Any] = {}
    for name, key, val in (("cas_numbers", "cas",
                            [cas] if cas is not None else None),
                           ("pubchem_cid", "cid", cid),
                           ("inchikey", "ik", inchikey)):
        if val is not None:
            cols.append(name)
            vals.append(f":{key}")
            params[key] = val
    sql = (f"INSERT INTO chemistry.chemicals ({','.join(cols)})"
           f" VALUES ({','.join(vals)}) RETURNING id")
    new_id = (await db.execute(text(sql), params)).scalar()
    return ResolveResult("NEW", chemical_id=int(new_id),
                         evidence={"cid": cid, "ik": inchikey, "cas": cas},
                         reason="no-candidates-inserted")


# ---------------------------------------------------------------------------
# absorb: 公开入口强制过闸; 破坏性动作在 _absorb_verified 内部
# ---------------------------------------------------------------------------

_SNAPSHOT_COLS = ("id", "pubchem_cid", "inchikey", "cas_numbers", "cb_number",
                  "preferred_name", "molecular_formula", "molecular_weight", "mol")


async def _snapshot(db: Any, row_id: int) -> dict[str, Any]:
    r = (await db.execute(text(
        "SELECT to_jsonb(c) FROM chemistry.chemicals c WHERE c.id = :id"
    ), {"id": row_id})).scalar()
    return dict(r) if r else {}


def _survivor_pick(source_keys: dict, target_keys: dict,
                   source_id: int, target_id: int) -> tuple[int, int]:
    """3.4: 已证明等价后选保留行。结构行(mol非空)优先, 次之 cid 齐全, 再 id 小。

    返回 (survivor_id, absorbed_id)。注意 mol 不在 keys 时视为无结构。
    """
    def score(k: dict, rid: int) -> tuple:
        return (bool(k.get("mol")), k.get("pubchem_cid") is not None,
                k.get("cb_number") is not None, -rid)
    if score(source_keys, source_id) >= score(target_keys, target_id):
        return source_id, target_id
    return target_id, source_id


async def absorb(db: Any, *, source_id: int, target_id: int,
                 reason: str, trigger: str | None = None,
                 evidence_ik: str | None = None,
                 evidence_cid: int | None = None) -> int:
    """合并两行(等价已由 can_merge 证明 — 本函数内部强制再过闸)。

    规范3.6 前置: merge_log 落表(含两侧 before snapshot)、redirect 落表、
    引用表全量改指(registry)、name_index 去重。返回 survivor_id。
    抛 MergeBlockedError 当 gate 未过 — 调用方无绕闸路径
    (destructive 实现在 _absorb_verified, 模块内不导出)。
    """
    ok, gate_reason = await can_merge(
        db, source_id=source_id, target_id=target_id,
        evidence_ik=evidence_ik, evidence_cid=evidence_cid)
    if not ok:
        raise MergeBlockedError(
            f"absorb blocked by merge gate: {gate_reason} "
            f"(source={source_id}, target={target_id})")

    # 完整 snapshot (含 mol) 用于 survivor 分与 merge_log before 记录
    # merge_log 口径: source=被吸收行, target=survivor — 与 _absorb_verified 一致
    s_full, t_full = await _snapshot(db, source_id), await _snapshot(db, target_id)
    survivor_id, absorbed_id = _survivor_pick(s_full, t_full, source_id, target_id)
    src_snap = s_full if absorbed_id == source_id else t_full
    tgt_snap = t_full if absorbed_id == source_id else s_full

    await _absorb_verified(
        db, survivor_id=survivor_id, absorbed_id=absorbed_id,
        reason=f"{reason} | gate={gate_reason}", trigger=trigger,
        src_snap=src_snap, tgt_snap=tgt_snap)
    return survivor_id


async def _coalesce_payload(db: Any, *, tbl: str, surv: int, ph: int,
                            key_extra: str | None, key_cols: tuple[str, ...],
                            merge_cols: tuple[str, ...],
                            key_extra2: str | None = None,
                            jsonb_cols: tuple[str, ...] = ()) -> None:
    """同键 survivor 行 ← old 行补空(白名单列, 绝不覆盖非空)。内部共用。

    jsonb_cols 中的列, '{}'(空对象)与 NULL 同视为空 —
    否则 upsert_details 写下的空包会挡住对方的非空证据。"""
    if key_extra:
        km = f'AND {tbl}."{key_extra}" = a."{key_extra}"'
        # source grain: 第二碰撞键(chemical_cb.cb_number) — NULL 安全比对
        if key_extra2:
            km += (f' AND {tbl}."{key_extra2}" IS NOT DISTINCT FROM'
                   f' a."{key_extra2}"')
    elif key_cols:
        km = "AND " + " AND ".join(
            f'{tbl}."{k}" = a."{k}"' for k in key_cols)
    else:
        km = ""
    q = lambda c: f'"{c}"'  # noqa: E731  列名统一加引号(含点/大写安全)

    def set_expr(c: str) -> str:
        if c in jsonb_cols:
            return (f"{q(c)} = CASE WHEN {tbl}.{q(c)} IS NOT NULL"
                    f" AND {tbl}.{q(c)} <> '{{}}'::jsonb"
                    f" THEN {tbl}.{q(c)} ELSE a.{q(c)} END")
        return f"{q(c)} = coalesce({tbl}.{q(c)}, a.{q(c)})"

    sets = ", ".join(set_expr(c) for c in merge_cols)
    set_updated = ", updated_at = now()" if "updated_at" in merge_cols else ""
    await db.execute(text(f"""
        UPDATE {tbl}
        SET {sets}{set_updated}
        FROM {tbl} a
        WHERE a.chemical_id = :ph AND {tbl}.chemical_id = :surv {km}
    """), {"surv": surv, "ph": ph})  # noqa: S608


async def _dedupe_conflicts(db: Any, *, tbl: str, surv: int, ph: int,
                            key_cols: tuple[str, ...],
                            merge_cols: tuple[str, ...]) -> list[dict]:
    """同键双侧 payload 均非空且不同 → 冲突事实留痕材料。

    coalesce 只补空, survivor 非空值原样保留 — 被吸收方 differing 值随行
    删除前必须记录, 不允许无痕蒸发。返回 [{"keys", "column",
    "survivor", "absorbed"}](值经 JSON 序列化归一)。"""
    out: list[dict] = []
    km = " AND ".join(f"a.{k} = b.{k}" for k in key_cols)
    for col in merge_cols:
        rows = (await db.execute(text(f"""
            SELECT a.{col} AS absorbed, b.{col} AS survivor
                   {', ' + ', '.join('a.' + k for k in key_cols)
                    if key_cols else ''}
            FROM {tbl} a JOIN {tbl} b
              ON b.chemical_id = :surv AND a.chemical_id = :ph AND {km}
            WHERE a.{col} IS NOT NULL AND b.{col} IS NOT NULL
              AND a.{col} IS DISTINCT FROM b.{col}
        """), {"surv": surv, "ph": ph})).mappings().all()  # noqa: S608
        for r in rows:
            out.append({
                "keys": {k: (json.dumps(r[k], default=str)
                             if isinstance(r[k], (dict, list)) else r[k])
                         for k in key_cols},
                "column": col,
                "survivor": json.dumps(r["survivor"], default=str)
                if isinstance(r["survivor"], (dict, list)) else r["survivor"],
                "absorbed": json.dumps(r["absorbed"], default=str)
                if isinstance(r["absorbed"], (dict, list)) else r["absorbed"],
            })
    return out


async def _merge_one_to_one(db: Any, *, schema: str, table: str,
                            survivor_id: int, absorbed_id: int,
                            cfg: dict) -> None:
    """1:1/唯一键子表迁移 (仅 _absorb_verified 内部调用)。

    键: chemical_pubchem=chemical_id; chemical_cb=(chemical_id,locale)。
    - 情况A old 行键与 survivor 不冲突(cb 不同locale/survivor无行) → 直接改指
    - 情况C 同键两侧都有 → 白名单业务列 coalesce 补 survivor 空值,
      补值成功后才 DELETE old 行; 绝不覆盖 survivor 非空值。
    身份/审计列(chemical_id/created_at/updated_at/fetched_at/locale)不合并。
    """
    key_extra = cfg.get("key_extra")
    tbl = f"{schema}.{table}"
    merge_cols = cfg.get("merge_cols")
    if merge_cols is None:
        # fail-closed: 策略声明 1:1 但无字段白名单 = 配置错误
        raise RuntimeError(
            f"MERGE_ONE_TO_ONE table {tbl} lacks merge_cols"
            " whitelist — refusing to migrate")
    if merge_cols:
        # C1: 同键两侧都有 → 补 survivor 空值(jsonb 空对象同视为空)
        await _coalesce_payload(db, tbl=tbl, surv=survivor_id, ph=absorbed_id,
                                key_extra=key_extra, key_cols=(),
                                merge_cols=tuple(merge_cols),
                                key_extra2=cfg.get("key_extra2"),
                                jsonb_cols=tuple(cfg.get("jsonb_merge_cols", ())))
        # C2: 只删"同键 survivor 行存在"的 old 行(即真正被并掉内容的行)。
        # survivor 无同键行 → 不删, 走下方情况A改指。
        if key_extra:
            km2 = ""
            if cfg.get("key_extra2"):
                k2 = cfg["key_extra2"]
                # NULL 安全: legacy NULL-grain 行与 NULL-grain 行互撞也属同键
                km2 = (f" AND a.{k2} IS NOT DISTINCT FROM b.{k2}")
            await db.execute(text(f"""
                DELETE FROM {tbl} a
                USING {tbl} b
                WHERE a.chemical_id = :ph AND b.chemical_id = :surv
                  AND a.{key_extra} = b.{key_extra}{km2}
            """), {"surv": survivor_id, "ph": absorbed_id})  # noqa: S608
        else:
            await db.execute(text(f"""
                DELETE FROM {tbl} a
                WHERE a.chemical_id = :ph
                  AND EXISTS (SELECT 1 FROM {tbl} b
                              WHERE b.chemical_id = :surv)
            """), {"surv": survivor_id, "ph": absorbed_id})  # noqa: S608
    # A: 剩余 old 行(survivor 无同键行) → 改指
    await db.execute(text(f"""
        UPDATE {tbl} SET chemical_id = :surv WHERE chemical_id = :ph
    """), {"surv": survivor_id, "ph": absorbed_id})  # noqa: S608


async def _dedupe_rekey(db: Any, *, schema: str, table: str,
                        survivor_id: int, absorbed_id: int,
                        cfg: dict) -> None:
    """复合键含 chemical_id 的表迁移 (仅 _absorb_verified 内部调用)。

    碰撞键 dedupe_key = PK 去掉 chemical_id 的列 (如 reaction_chemicals
    为 (reaction_id, role), name_index 为 (source,kind,normalized))。
    同 dedupe_key 双侧有行时统一 UPDATE 会撞 PK, 因此分三步:
    1. 白名单 payload 列先补 survivor 空值(old 独有信息不静默丢)
    2. 删 old 侧同键行(survivor 行已承载合并内容)
    3. 剩余 old 行(键不冲突)改指
    """
    tbl = f"{schema}.{table}"
    key_cols = cfg.get("dedupe_key")
    if not key_cols:
        raise RuntimeError(
            f"DEDUPE_REKEY table {tbl} lacks dedupe_key — refusing to migrate")
    merge_cols = tuple(cfg.get("merge_cols", ()))
    km = " AND ".join(f"a.{k} = b.{k}" for k in key_cols)
    conflicts: list[dict] = []
    if merge_cols:
        # 冲突事实先留痕(补空会保留 survivor 值, differing 值
        # 随 old 行删除蒸发 — 删前记录进 merge_log evidence)
        conflicts = await _dedupe_conflicts(
            db, tbl=tbl, surv=survivor_id, ph=absorbed_id,
            key_cols=tuple(key_cols), merge_cols=merge_cols)
        # payload 补空: 同键 survivor 行 ← old 行 (白名单列)
        await _coalesce_payload(db, tbl=tbl, surv=survivor_id, ph=absorbed_id,
                                key_extra=None, key_cols=tuple(key_cols),
                                merge_cols=merge_cols)
    # 删 old 侧同键行(此时 survivor 行已含 old 的可保留信息)
    await db.execute(text(f"""
        DELETE FROM {tbl} a
        USING {tbl} b
        WHERE a.chemical_id = :ph AND b.chemical_id = :surv AND {km}
    """), {"surv": survivor_id, "ph": absorbed_id})  # noqa: S608
    # 剩余 old 行改指
    await db.execute(text(f"""
        UPDATE {tbl} SET chemical_id = :surv WHERE chemical_id = :ph
    """), {"surv": survivor_id, "ph": absorbed_id})  # noqa: S608
    return conflicts


async def _absorb_verified(db: Any, *, survivor_id: int, absorbed_id: int,
                           reason: str, trigger: str | None,
                           src_snap: dict, tgt_snap: dict) -> int:
    """破坏性合并本体(仅 absorb 内部调用, 规范3.5/3.6)。

    顺序: merge_log 落表 → 键并集/核心字段并入 survivor → 引用全量改指
    (含去重与活动任务 dedupe_key rekey) → redirect 落表 → absorbed 行
    DELETE。同事务。
    """
    # 主表核心字段冲突留痕(双侧非空且不同 → survivor
    # 保留, differing 值记入 evidence, 不随行删除无痕蒸发)
    core_conflicts = _core_conflicts(tgt_snap, src_snap)
    evidence: dict[str, Any] = {"gate": reason}
    if core_conflicts:
        evidence["core_conflicts"] = core_conflicts

    # 1. merge_log (规范3.6.2) — 任何批量 absorb 的上线阻断项
    merge_id = (await db.execute(text("""
        INSERT INTO maintenance.identity_merge_log
            (source_id, target_id, reason, evidence,
             source_keys_before, target_keys_before, trigger)
        VALUES (:s, :t, :reason, :evidence, :ssnap, :tsnap, :trig)
        RETURNING merge_id
    """), {"s": absorbed_id, "t": survivor_id, "reason": reason,
           "evidence": json.dumps(evidence, default=str, ensure_ascii=False),
           "ssnap": json.dumps(src_snap, default=str, ensure_ascii=False),
           "tsnap": json.dumps(tgt_snap, default=str, ensure_ascii=False),
           "trig": trigger})).scalar()

    # 2. 键并集 + 核心字段并入 survivor。
    # cas 并集去重; 其余核心字段补空语义: 标量
    # coalesce, 数组 NULL/空才算空, synonyms '{}' 算空; 双侧非空 →
    # survivor 保留(冲突已在 evidence.core_conflicts 留痕)。
    def scalar(c: str) -> str:
        return f"{c} = coalesce(t.{c}, p.{c})"

    def array(c: str) -> str:
        return (f"{c} = CASE WHEN cardinality(t.{c}) > 0"
                f" THEN t.{c} ELSE p.{c} END")

    def jsonb_empty(c: str) -> str:
        return (f"{c} = CASE WHEN t.{c} IS NOT NULL AND t.{c} <> '{{}}'::jsonb"
                f" THEN t.{c} ELSE p.{c} END")

    core_sets = [scalar(c) for c in _CORE_SCALAR_COLUMNS if c != "dtxsid"]
    core_sets += [array(c) for c in _CORE_ARRAY_COLUMNS]
    core_sets += [jsonb_empty(c) for c in _CORE_JSONB_COLUMNS]
    core_sets += [scalar(c) for c in _CORE_RAW_COALESCE_COLUMNS]
    # dtxsid 全局唯一(chemicals_dtxsid_uidx): survivor 为空、被吸收方有值时
    # 直接 UPDATE 会让两行短暂同值撞索引 — 先把旧行值摘下(快照已有), 旧行
    # 置 NULL 后经参数迁移。双侧都有值(冲突)时不迁移, 无撞索引问题。
    migrate_dtxsid = (
        src_snap.get("dtxsid") is not None
        and tgt_snap.get("dtxsid") is None)
    if migrate_dtxsid:
        await db.execute(text(
            "UPDATE chemistry.chemicals SET dtxsid = NULL WHERE id = :ph"
        ), {"ph": absorbed_id})
    core_sets.append("dtxsid = coalesce(t.dtxsid, :p_dtxsid)")
    await db.execute(text(f"""
        UPDATE chemistry.chemicals t SET
            cas_numbers = (
                SELECT array_agg(DISTINCT x ORDER BY x) FROM (
                    SELECT unnest(t.cas_numbers) AS x
                    UNION SELECT unnest(p.cas_numbers)) s
                WHERE x IS NOT NULL),
            cb_number = coalesce(t.cb_number, p.cb_number),
            preferred_name = coalesce(t.preferred_name, p.preferred_name),
            {', '.join(core_sets)},
            updated_at = now()
        FROM chemistry.chemicals p
        WHERE t.id = :target AND p.id = :ph
    """), {"target": survivor_id, "ph": absorbed_id,
           "p_dtxsid": src_snap.get("dtxsid") if migrate_dtxsid else None})

    # 3. 引用表按 registry cfg 声明的 strategy 迁移 (规范3.6.1);
    # 碰撞键/补值白名单全部来自 cfg, 本函数不猜表结构。
    payload_conflicts: dict[str, list[dict]] = {}
    for schema, tbl, cfg in CHEMICAL_REFERENCE_TABLES:
        strategy = cfg["strategy"]
        if strategy == "MERGE_ONE_TO_ONE":
            # 1:1 子表: 同键双侧 → coalesce 补空后删 old;
            # old 独有键行改指。键定义在 cfg (chemical_id 或 chemical_id+key_extra)。
            await _merge_one_to_one(
                db, schema=schema, table=tbl,
                survivor_id=survivor_id, absorbed_id=absorbed_id,
                cfg=cfg)
        elif strategy == "DEDUPE_REKEY":
            # 复合键含 chemical_id (如 reaction_chemicals):
            # 同 dedupe_key 双侧有行 → 先按白名单补 survivor 空值(payload
            # 不静默丢, 冲突留痕), 再删 old 同键行, 剩余 old 行改指。
            conflicts = await _dedupe_rekey(
                db, schema=schema, table=tbl,
                survivor_id=survivor_id, absorbed_id=absorbed_id,
                cfg=cfg)
            if conflicts:
                payload_conflicts[f"{schema}.{tbl}"] = conflicts
        elif strategy == "REKEY_MANY":
            prefixes = cfg.get("rekey_dedupe_prefixes")
            if prefixes:
                await _rekey_many_with_dedupe(
                    db, schema=schema, table=tbl,
                    survivor_id=survivor_id, absorbed_id=absorbed_id,
                    prefixes=tuple(prefixes))
            else:
                await db.execute(text(f"""
                    UPDATE {schema}.{tbl} SET chemical_id = :target
                    WHERE chemical_id = :ph
                """), {"target": survivor_id, "ph": absorbed_id})  # noqa: S608
        else:
            raise RuntimeError(
                f"unknown reference strategy {strategy!r} for "
                f"{schema}.{tbl} — refusing to migrate")

    # 3b. 引用表 payload 冲突留痕(写回 merge_log evidence)
    if payload_conflicts:
        await db.execute(text("""
            UPDATE maintenance.identity_merge_log
            SET evidence = evidence
                || CAST(:conflicts AS jsonb)
            WHERE merge_id = :mid
        """), {"conflicts": json.dumps(
                    {"payload_conflicts": payload_conflicts},
                    default=str, ensure_ascii=False),
               "mid": merge_id})

    # 4. redirect (规范3.6.3) — 身份历史不删, canonicalize_id 可查
    await db.execute(text("""
        INSERT INTO maintenance.chemical_identity_redirect
            (old_chemical_id, canonical_chemical_id, merge_log_id)
        VALUES (:old, :canon, :mid)
    """), {"old": absorbed_id, "canon": survivor_id, "mid": merge_id})

    # 5. absorbed 行 DELETE
    await db.execute(text(
        "DELETE FROM chemistry.chemicals WHERE id = :ph"
    ), {"ph": absorbed_id})
    logger.info("absorb: %s -> %s (merge_id=%s)", absorbed_id, survivor_id, merge_id)
    return int(merge_id)


async def _rekey_many_with_dedupe(db: Any, *, schema: str, table: str,
                                  survivor_id: int, absorbed_id: int,
                                  prefixes: tuple[str, ...]) -> None:
    """任务表(带 dedupe_key)的 REKEY_MANY。

    dedupe_key 前缀携带 chemical_id(cas:{id}:… / cid:{id}:…) — 只改
    chemical_id 不改 key 的话, survivor 侧新入列撞不上旧前缀, 同任务双活。
    三步:
    1. rekey 后会撞 survivor 既有活跃键的 old 行 → 删除(survivor 活跃行
       已承载同一任务, 重复行无意义);
    2. 其余带前缀 old 行 rekey + 改指;
    3. 无前缀行(如 cas:new:*)只改指。
    active 活跃窗与 cas_jobs/pubchem_jobs 的 partial unique index 口径
    一致(status ∈ queued/leased/error; 两表 CHECK 亦只有这三态)。"""
    tbl = f"{schema}.{table}"
    pref = "|".join(prefixes)
    old_p, new_p = f"^({pref}):{absorbed_id}:", f"\\1:{survivor_id}:"
    await db.execute(text(f"""
        DELETE FROM {tbl} a
        WHERE a.chemical_id = :ph
          AND EXISTS (SELECT 1 FROM {tbl} b
                      WHERE b.id <> a.id
                        AND b.status IN ('queued','leased','error')
                        AND b.dedupe_key = regexp_replace(
                            a.dedupe_key, :old_p, :new_p))
    """), {"ph": absorbed_id, "old_p": old_p, "new_p": new_p})  # noqa: S608
    await db.execute(text(f"""
        UPDATE {tbl}
        SET chemical_id = :surv, updated_at = now(),
            dedupe_key = regexp_replace(dedupe_key, :old_p, :new_p)
        WHERE chemical_id = :ph AND dedupe_key ~ :old_p
    """), {"surv": survivor_id, "ph": absorbed_id,
           "old_p": old_p, "new_p": new_p})  # noqa: S608
    await db.execute(text(f"""
        UPDATE {tbl} SET chemical_id = :surv WHERE chemical_id = :ph
    """), {"surv": survivor_id, "ph": absorbed_id})  # noqa: S608


async def canonicalize_id(db: Any, chemical_id: int) -> int:
    """旧 id → canonical id (规范3.6.3)。无 redirect 记录时返回原 id。

    链式跟随 (a→b→c), 环保护上限 16 跳。
    """
    cur = chemical_id
    seen = {cur}
    for depth in range(16):
        nxt = (await db.execute(text("""
            SELECT canonical_chemical_id
            FROM maintenance.chemical_identity_redirect
            WHERE old_chemical_id = :cur
            ORDER BY merge_log_id DESC LIMIT 1
        """), {"cur": cur})).scalar()
        if nxt is None:
            return cur
        if nxt in seen:
            # fail closed: 环绝不把 stale id 送回调用方继续写
            logger.error("redirect_cycle_detected from=%s at_depth=%s",
                         chemical_id, depth)
            raise RuntimeError(
                f"redirect cycle detected from chemical_id={chemical_id}")
        seen.add(int(nxt))
        cur = int(nxt)
    logger.error("redirect_chain_too_deep from=%s", chemical_id)
    raise RuntimeError(f"redirect chain too deep from {chemical_id}")
