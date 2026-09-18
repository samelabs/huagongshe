"""workapi 内部队列服务层 — 自 api/workapi.py 下沉, 逻辑零改动(批次3d)。

包含: lease_hash/verified_lease(租约校验), as_json_object/sync_chemical_core/
reject_completed_job/upsert_details(PB 完成写库),
verified_cas_lease(CB 租约校验)。
外部引用者: api/workapi.py 各端点。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

from ..schemas.workapi import LeaseProof
from ..services.name_index import ingest_from_synonyms
import logging

from ..pubchem_core import chemical_core_values, number_or_none, validate_synonyms

logger = logging.getLogger(__name__)


class LeaseConflictError(Exception):
    """租约校验失败的 transport-neutral 表达(E5 transport neutrality)。

    只承载语义: ``kind`` + ``detail``。HTTP status/detail 由 adapter 独占映射
    (api/workapi.py ``_lease_conflict_http``) — 本 service 不 import 任何
    transport 框架, 因此非 HTTP 调用方(MCP/脚本/测试)可直接捕获本类型。
    """

    kind = "lease_conflict"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class PayloadInvalidError(Exception):
    """CAS complete 载荷语义无效的 transport-neutral 表达(E6 job 状态机归口)。

    只承载语义: ``kind`` + ``detail``。HTTP status(既有 422)/detail 由 adapter
    独占映射(api/workapi.py ``_payload_invalid_http``) — 本 service 不 import
    任何 transport 框架。
    """

    kind = "payload_invalid"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def lease_hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


# ── P0-2 completion receipt(0912 trusted plane): 幂等 ack + 最小成功归因 ──
# 与业务写入 + job terminal 同一事务提交; 只存协议事实, 无 payload/明文 token。

RECEIPT_INSERT = text("""
    INSERT INTO maintenance.workapi_completion_receipts
        (family, job_id, worker_id, lease_token_hash, scope, terminal_status, chemical_id)
    VALUES (:family, :job_id, :worker_id, :lease_hash, :scope, :status, :chemical_id)
    ON CONFLICT (family, job_id) DO NOTHING
""")


async def record_completion_receipt(
    db: Any, *, family: str, job_id: int, worker_id: str,
    lease_token: str, scope: str, terminal_status: str,
    chemical_id: int | None,
) -> None:
    """complete 主事务内调用(与 DELETE job 同 commit)。幂等插入。"""
    await db.execute(RECEIPT_INSERT, {
        "family": family, "job_id": job_id, "worker_id": worker_id,
        "lease_hash": lease_hash(lease_token), "scope": scope,
        "status": terminal_status, "chemical_id": chemical_id,
    })


async def find_completion_receipt(
    db: Any, *, family: str, job_id: int, worker_id: str, lease_token: str,
) -> bool:
    """active lease 已不存在时的重试判定:
    family+job_id+worker_id+lease_token_hash 全一致 → True(幂等 ack)。"""
    row = (await db.execute(text("""
        SELECT 1 FROM maintenance.workapi_completion_receipts
        WHERE family=:family AND job_id=:job_id
          AND worker_id=:worker_id AND lease_token_hash=:lease_hash
        LIMIT 1
    """), {
        "family": family, "job_id": job_id, "worker_id": worker_id,
        "lease_hash": lease_hash(lease_token),
    })).fetchone()
    return row is not None


async def verified_lease(db: Any, proof: LeaseProof, worker_id: str, *, lock: bool = True):
    suffix = " FOR UPDATE" if lock else ""
    row = (await db.execute(text(f"""
        SELECT id,chemical_id,query_value
        FROM maintenance.pubchem_jobs
        WHERE id=:job_id AND status='leased' AND lease_owner=:worker_id
          AND lease_token_hash=:lease_hash AND lease_expires_at>now(){suffix}
    """), {
        "job_id": proof.job_id,
        "worker_id": worker_id,
        "lease_hash": lease_hash(proof.lease_token),
    })).fetchone()
    if not row:
        raise LeaseConflictError("lease is missing, expired, or owned by another worker")
    return row

def as_json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def sync_chemical_core(
    db: Any,
    chemical_id: int,
    properties: dict[str, Any],
    *,
    record_title: Any = None,
    synonyms: list[str] | None = None,
    cas_numbers: list[str] | None = None,
    main_table_ids: dict[str, list[str]] | None = None,
    identity_grant: dict[str, Any] | None = None,
) -> None:
    """Synchronize trusted PubChem core fields without changing identity/structure.

    0909 §2 写前裁定收口: 强身份字段(pubchem_cid/inchikey)不再从 incoming
    properties 直取 — 调用方(complete_job)必须先完成 identity 裁定, 把
    **已裁定可落**的身份值经 identity_grant 传入; 本函数只按"补空不覆盖"
    语义写入。identity_grant 缺省(兼容旧调用面)时 cid/ik 一律不写。

    cas_numbers(0901 裁定): cb_number 为空才写(并集补空), 有 CB 印记归 CB 链。
    main_table_ids: nikkaji/chembl/ec/unii/chebi/dtxsid 主表已有列补空(0901 方案§四)。
    """
    values = chemical_core_values(properties, record_title=record_title)
    # §2 职责分离: identity 字段只来自裁定通道(grant), incoming payload 不再直写
    values["pubchem_cid"] = (identity_grant or {}).get("pubchem_cid")
    values["inchikey"] = (identity_grant or {}).get("inchikey")
    id_arrays = {
        "nikkaji_numbers": (main_table_ids or {}).get("nikkaji_numbers"),
        "chembl_ids": (main_table_ids or {}).get("chembl_ids"),
        "ec_numbers": (main_table_ids or {}).get("ec_numbers"),
        "unii_codes": (main_table_ids or {}).get("unii_codes"),
        "chebi_ids": (main_table_ids or {}).get("chebi_ids"),
    }
    id_sets = {k: sorted(set(v)) for k, v in id_arrays.items() if v}
    dtxsid_values = sorted(set((main_table_ids or {}).get("dtxsid") or []))
    dtxsid_in = dtxsid_values[0] if dtxsid_values else None

    validated = None
    if synonyms is not None:
        try:
            validated = validate_synonyms(synonyms)
        except ValueError:
            logger.warning("synonyms rejected (limit/invariant): chemical_id=%s count=%s",
                           chemical_id, len(synonyms) if isinstance(synonyms, list) else "?")
    if validated is not None:
        validated = json.dumps(validated, ensure_ascii=False, separators=(",", ":"))
    await db.execute(text("""
        WITH incoming AS (
            SELECT CAST(:preferred_name AS text) AS preferred_name,
                   CAST(:iupac_name AS text) AS iupac_name,
                   CAST(:molecular_formula AS text) AS molecular_formula,
                   CAST(:average_mass AS double precision) AS average_mass,
                   CAST(:monoisotopic_mass AS double precision) AS monoisotopic_mass,
                   CAST(:inchikey AS text) AS inchikey,
                   CAST(:pubchem_cid AS integer) AS pubchem_cid,
                   CAST(:pubchem_smiles AS text) AS pubchem_smiles,
                   CAST(:sync_synonyms AS boolean) AS sync_synonyms,
                   CAST(:synonyms AS jsonb) AS synonyms,
                   CAST(:cas_in AS text[]) AS cas_in,
                   CAST(:nikkaji_in AS text[]) AS nikkaji_in,
                   CAST(:chembl_in AS text[]) AS chembl_in,
                   CAST(:ec_in AS text[]) AS ec_in,
                   CAST(:unii_in AS text[]) AS unii_in,
                   CAST(:chebi_in AS text[]) AS chebi_in,
                   CAST(:dtxsid_in AS text) AS dtxsid_in
        )
        UPDATE chemistry.chemicals
        SET preferred_name=coalesce(incoming.preferred_name,chemistry.chemicals.preferred_name),
            iupac_name=coalesce(incoming.iupac_name,chemistry.chemicals.iupac_name),
            molecular_formula=coalesce(incoming.molecular_formula,chemistry.chemicals.molecular_formula),
            average_mass=coalesce(incoming.average_mass,chemistry.chemicals.average_mass),
            monoisotopic_mass=coalesce(incoming.monoisotopic_mass,chemistry.chemicals.monoisotopic_mass),
            -- §2 强身份: 只补空(existing-first), 非空冲突永不覆盖
            inchikey=coalesce(chemistry.chemicals.inchikey, incoming.inchikey),
            pubchem_cid=coalesce(chemistry.chemicals.pubchem_cid, incoming.pubchem_cid),
            pubchem_smiles=coalesce(incoming.pubchem_smiles,chemistry.chemicals.pubchem_smiles),
            synonyms=CASE WHEN incoming.sync_synonyms
                THEN incoming.synonyms ELSE chemistry.chemicals.synonyms END,
            cas_numbers=CASE
                WHEN chemistry.chemicals.cb_number IS NULL
                 AND cardinality(incoming.cas_in) > 0
                THEN coalesce(chemistry.chemicals.cas_numbers, ARRAY[]::text[])
                     || (SELECT array_agg(DISTINCT c) FROM unnest(incoming.cas_in) c
                         WHERE NOT coalesce(chemistry.chemicals.cas_numbers, ARRAY[]::text[]) @> ARRAY[c])
                ELSE chemistry.chemicals.cas_numbers END,
            nikkaji_numbers=CASE WHEN cardinality(incoming.nikkaji_in) > 0
                THEN coalesce(chemistry.chemicals.nikkaji_numbers, incoming.nikkaji_in)
                ELSE chemistry.chemicals.nikkaji_numbers END,
            chembl_ids=CASE WHEN cardinality(incoming.chembl_in) > 0
                THEN coalesce(chemistry.chemicals.chembl_ids, incoming.chembl_in)
                ELSE chemistry.chemicals.chembl_ids END,
            ec_numbers=CASE WHEN cardinality(incoming.ec_in) > 0
                THEN coalesce(chemistry.chemicals.ec_numbers, incoming.ec_in)
                ELSE chemistry.chemicals.ec_numbers END,
            unii_codes=CASE WHEN cardinality(incoming.unii_in) > 0
                THEN coalesce(chemistry.chemicals.unii_codes, incoming.unii_in)
                ELSE chemistry.chemicals.unii_codes END,
            chebi_ids=CASE WHEN cardinality(incoming.chebi_in) > 0
                THEN coalesce(chemistry.chemicals.chebi_ids, incoming.chebi_in)
                ELSE chemistry.chemicals.chebi_ids END,
            dtxsid=CASE WHEN incoming.dtxsid_in IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM chemistry.chemicals c2
                     WHERE c2.dtxsid=incoming.dtxsid_in AND c2.id<>:chemical_id)
                THEN coalesce(chemistry.chemicals.dtxsid, incoming.dtxsid_in)
                ELSE chemistry.chemicals.dtxsid END,
            updated_at=now()
        FROM incoming
        WHERE chemistry.chemicals.id=:chemical_id AND (
            (incoming.preferred_name IS NOT NULL AND chemistry.chemicals.preferred_name IS DISTINCT FROM incoming.preferred_name) OR
            (incoming.iupac_name IS NOT NULL AND chemistry.chemicals.iupac_name IS DISTINCT FROM incoming.iupac_name) OR
            (incoming.molecular_formula IS NOT NULL AND chemistry.chemicals.molecular_formula IS DISTINCT FROM incoming.molecular_formula) OR
            (incoming.average_mass IS NOT NULL AND chemistry.chemicals.average_mass IS DISTINCT FROM incoming.average_mass) OR
            (incoming.monoisotopic_mass IS NOT NULL AND chemistry.chemicals.monoisotopic_mass IS DISTINCT FROM incoming.monoisotopic_mass) OR
            (incoming.inchikey IS NOT NULL AND chemistry.chemicals.inchikey IS DISTINCT FROM incoming.inchikey) OR
            (incoming.pubchem_cid IS NOT NULL AND chemistry.chemicals.pubchem_cid IS DISTINCT FROM incoming.pubchem_cid) OR
            (incoming.pubchem_smiles IS NOT NULL AND chemistry.chemicals.pubchem_smiles IS DISTINCT FROM incoming.pubchem_smiles) OR
            (incoming.sync_synonyms AND chemistry.chemicals.synonyms IS DISTINCT FROM incoming.synonyms) OR
            (chemistry.chemicals.cb_number IS NULL AND cardinality(incoming.cas_in) > 0
             AND NOT coalesce(chemistry.chemicals.cas_numbers, ARRAY[]::text[]) @> incoming.cas_in) OR
            (cardinality(incoming.nikkaji_in) > 0
             AND (chemistry.chemicals.nikkaji_numbers IS NULL OR chemistry.chemicals.nikkaji_numbers <> incoming.nikkaji_in)) OR
            (cardinality(incoming.chembl_in) > 0
             AND (chemistry.chemicals.chembl_ids IS NULL OR chemistry.chemicals.chembl_ids <> incoming.chembl_in)) OR
            (cardinality(incoming.ec_in) > 0
             AND (chemistry.chemicals.ec_numbers IS NULL OR chemistry.chemicals.ec_numbers <> incoming.ec_in)) OR
            (cardinality(incoming.unii_in) > 0
             AND (chemistry.chemicals.unii_codes IS NULL OR chemistry.chemicals.unii_codes <> incoming.unii_in)) OR
            (cardinality(incoming.chebi_in) > 0
             AND (chemistry.chemicals.chebi_ids IS NULL OR chemistry.chemicals.chebi_ids <> incoming.chebi_in)) OR
            (incoming.dtxsid_in IS NOT NULL AND chemistry.chemicals.dtxsid IS DISTINCT FROM incoming.dtxsid_in)
        )
    """), {
        "chemical_id": chemical_id,
        "sync_synonyms": validated is not None,
        # 0904: validate_synonyms 原是四层重构孤儿(全库零引用)。它是 PB
        # synonyms 上限防线(20万条/8MB), 接回写入口。校验 raise ValueError
        # → 此处捕获: 跳过 synonyms 写入(其余字段照写), log 留痕不静默。
        "synonyms": validated,
        "cas_in": cas_numbers or [],
        "nikkaji_in": id_sets.get("nikkaji_numbers", []),
        "chembl_in": id_sets.get("chembl_ids", []),
        "ec_in": id_sets.get("ec_numbers", []),
        "unii_in": id_sets.get("unii_codes", []),
        "chebi_in": id_sets.get("chebi_ids", []),
        "dtxsid_in": dtxsid_in,
        **values,
    })
    # name_index 摄入: synonyms 镜像, 与核心列同步同事务(仅校验通过时)
    if validated is not None:
        await ingest_from_synonyms(db, chemical_id, synonyms)


async def reconcile_pubchem_identity(
    db: Any, chemical_id: int, new_cid: int | None
) -> int:
    """0907 强身份回补 gate: enrichment 新获得 pubchem_cid 后的 re-resolution。

    冻结规则: 任何 enrichment 新获得此前行上不存在的强 identity evidence,
    必须在最终落主表身份前重新经过 identity resolution (CID=entity proof,
    IK 不单独授权, 复用 resolve_chemical/absorb, 不另写 matcher)。

    返回最终 canonical chemical_id。create=False — callback 永不因 enrichment
    自行新建 chemical 行。分支:
    - resolver 指向当前行 → 正常 enrichment, 返回原 id
    - resolver 指向他行 → 正式 absorb() (gate 内置 can_merge), 返回 survivor
    - absorb 被 gate 拒 → 保留两行 + structured warning, 返回原 id
    - CONFLICT → 不覆盖 + structured warning, 返回原 id
    """
    if new_cid is None:
        return chemical_id
    import logging
    logger = logging.getLogger("huagongshe.workqueue")
    from .identity import resolve_chemical, absorb, MergeBlockedError
    res = await resolve_chemical(db, cid=new_cid, create=False)
    if res.status == "CONFLICT":
        logger.warning(
            "pubchem_identity_conflict chemical_id=%s new_cid=%s candidates=%s",
            chemical_id, new_cid, res.candidates)
        return chemical_id
    # cid 命中行的全体 candidates 中, 除当前行外还有他行 → 必须 reconcile。
    # 不用 res.chemical_id(picked): picked 可能恰为当前行而残留他行重复;
    # reconcile 对象由 resolver candidates 决定, survivor 仍由 absorb 裁定。
    others = [c for c in (res.candidates or []) if c != chemical_id]
    if not others:
        return chemical_id
    target = others[0]
    try:
        survivor = await absorb(
            db, source_id=chemical_id, target_id=target,
            reason="pubchem-cid-relocation", trigger="pubchem_fetch_callback",
            evidence_cid=new_cid)
        return survivor
    except MergeBlockedError as exc:
        # 保留两行不中断回补, 但必须可观测 — 身份冲突不允许静默
        logger.warning(
            "merge_gate_blocked chemical_id=%s target=%s reason=%s",
            chemical_id, target, exc)
        return chemical_id


async def adjudicate_pubchem_identity(
    db: Any, chemical_id: int,
    inc_cid: int | None, inc_ik: str | None,
) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
    """0909 §2 写前裁定: incoming CID/IK 先裁定, 后写入。

    返回 (canonical_chemical_id, identity_grant, conflict):
    - grant: 经裁定可落的强身份值(仅补空), 由 sync_chemical_core 写入
    - conflict: 行上强身份冲突事实 — 不吞、不覆盖、不吸收, 仅可观测
    顺序: 行上冲突判断 → 补空 grant → same-CID fork 收敛(reconcile/absorb)
    → fork 未收敛时撤回 CID grant(禁止制造 same-CID 分叉)。
    can_merge/absorb 冻结规则不变; 本函数只重排写序, 不新增任何合并权限。
    """
    from ..pubchem_core import INCHIKEY_RE
    if inc_ik is not None and not INCHIKEY_RE.fullmatch(inc_ik):
        inc_ik = None  # 格式非法的 IK 不作为 evidence

    row = (await db.execute(text("""
        SELECT pubchem_cid, inchikey FROM chemistry.chemicals WHERE id=:id
    """), {"id": chemical_id})).mappings().first()
    if row is None:
        return chemical_id, {}, None
    ex_cid, ex_ik = row["pubchem_cid"], row["inchikey"]

    # --- 行上强身份冲突: fail-closed, 身份零写入(普通 enrichment 照走) ---
    conflict = None
    if inc_cid is not None and ex_cid is not None and inc_cid != ex_cid:
        # CID 冲突先判 — 不因 incoming IK 恰巧相同而绕过
        conflict = {"existing_cid": ex_cid, "existing_ik": ex_ik,
                    "incoming_cid": inc_cid, "reason": "cid-conflict"}
    elif inc_ik is not None and ex_ik is not None and inc_ik != ex_ik:
        conflict = {"existing_cid": ex_cid, "existing_ik": ex_ik,
                    "incoming_ik": inc_ik, "reason": "ik-conflict"}
    if conflict:
        return chemical_id, {}, conflict

    grant: dict[str, Any] = {}
    if ex_cid is None and inc_cid is not None:
        grant["pubchem_cid"] = inc_cid
    if ex_ik is None and inc_ik is not None:
        grant["inchikey"] = inc_ik

    if inc_cid is None:
        return chemical_id, grant, None

    # --- §2.1 holder preflight: incoming CID+IK 先过现有 resolver 完整裁定 ---
    # same-CID reconcile 只传 CID, 会漏 "holder CID=A/Ik=X vs incoming IK=Y"
    # 的强键冲突; destructive reconciliation 前用 resolve_chemical 的
    # 3.3 硬约束(cid vs 行上 ik)复核, CONFLICT → fail-closed, 不 absorb。
    if inc_ik is not None:
        from .identity import resolve_chemical
        pre = await resolve_chemical(db, cid=inc_cid, inchikey=inc_ik, create=False)
        if pre.status == "CONFLICT":
            return chemical_id, {}, {
                "incoming_cid": inc_cid, "incoming_ik": inc_ik,
                "candidates": pre.candidates, "reason": "holder-ik-conflict",
                **(pre.evidence or {})}

    # --- same-CID fork 收敛(0907 gate 原逻辑): resolve → absorb, 不改闸 ---
    canonical = await reconcile_pubchem_identity(db, chemical_id, inc_cid)
    if canonical != chemical_id:
        # 已收敛: 以 survivor 落库后实际状态重算 grant(merge 白名单可能已带上)
        srow = (await db.execute(text("""
            SELECT pubchem_cid, inchikey FROM chemistry.chemicals WHERE id=:id
        """), {"id": canonical})).mappings().first()
        grant = {}
        if srow is not None:
            if srow["pubchem_cid"] is None:
                grant["pubchem_cid"] = inc_cid
            if srow["inchikey"] is None and inc_ik is not None:
                grant["inchikey"] = inc_ik
        return canonical, grant, None

    # reconcile 未移动行: 他行仍持有该 CID(absorb 被闸拒 / resolver CONFLICT)
    # → 撤回 CID grant, 禁止制造 same-CID 分叉
    holder = (await db.execute(text("""
        SELECT 1 FROM chemistry.chemicals
        WHERE pubchem_cid=:c AND id<>:me LIMIT 1
    """), {"c": inc_cid, "me": chemical_id})).first()
    if holder is not None:
        grant.pop("pubchem_cid", None)
    return chemical_id, grant, None


async def upsert_details(
    db: Any,
    chemical_id: int,
    payload: dict[str, Any],
) -> None:
    """整包入库(0901 定案): 拉到就 update 全字段覆盖, fetched_at=now()。
    payload = worker 整包解析产物(结构化字段), 无 merge 无校验。"""
    def obj(key: str) -> str:
        return json.dumps(as_json_object(payload.get(key)), ensure_ascii=False, separators=(",", ":"))

    def num(key: str, cast=float):
        return number_or_none(payload.get(key), cast)

    from datetime import date as _date
    def as_date(key: str):
        raw = payload.get(key)
        if raw is None or isinstance(raw, _date):
            return raw
        try:
            return _date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    params = {
        "chemical_id": chemical_id,
        "record_title": payload.get("record_title"),
        "record_description": payload.get("record_description"),
        "xlogp": num("xlogp"), "tpsa": num("tpsa"), "complexity": num("complexity"),
        "hbd": num("hbd", int), "hba": num("hba", int), "rotatable": num("rotatable", int),
        "heavy": num("heavy", int), "charge": num("charge", int),
        "computed": obj("computed"), "physical": obj("physical"),
        "ghs": obj("ghs"), "hazards": obj("hazards"), "measures": obj("measures"),
        "toxicity": obj("toxicity"), "regulatory": obj("regulatory"),
        "pharmacology": obj("pharmacology"), "uses": obj("uses"),
        "identifiers": obj("identifiers"), "references": obj("references"),
        "external_ids": obj("external_ids"), "ghs_codes": obj("ghs_codes"),
        "reactivity": obj("reactivity"),
        "created_on": as_date("pubchem_created_on"),
        "modified_on": as_date("pubchem_modified_on"),
    }
    await db.execute(text("""
        INSERT INTO chemistry.chemical_pubchem (
            chemical_id,record_title,record_description,xlogp,
            topological_polar_surface_area,complexity,hbond_donor_count,
            hbond_acceptor_count,rotatable_bond_count,heavy_atom_count,formal_charge,
            computed_properties,physical_properties,ghs_classification,hazards,
            safety_measures,toxicity,regulatory,pharmacology,uses_and_manufacturing,
            identifier_evidence,source_references,
            external_ids,ghs_codes,reactivity,
            pubchem_created_on,pubchem_modified_on,
            fetched_at,updated_at
        ) VALUES (
            :chemical_id,:record_title,:record_description,:xlogp,
            :tpsa,:complexity,:hbd,:hba,:rotatable,:heavy,:charge,
            CAST(:computed AS jsonb),CAST(:physical AS jsonb),CAST(:ghs AS jsonb),
            CAST(:hazards AS jsonb),CAST(:measures AS jsonb),CAST(:toxicity AS jsonb),
            CAST(:regulatory AS jsonb),CAST(:pharmacology AS jsonb),CAST(:uses AS jsonb),
            CAST(:identifiers AS jsonb),CAST(:references AS jsonb),
            CAST(:external_ids AS jsonb),CAST(:ghs_codes AS jsonb),
            CAST(:reactivity AS jsonb),
            :created_on,:modified_on,
            now(),now()
        )
        ON CONFLICT (chemical_id) DO UPDATE SET
            record_title=excluded.record_title,
            record_description=excluded.record_description,
            xlogp=excluded.xlogp,
            topological_polar_surface_area=excluded.topological_polar_surface_area,
            complexity=excluded.complexity,
            hbond_donor_count=excluded.hbond_donor_count,
            hbond_acceptor_count=excluded.hbond_acceptor_count,
            rotatable_bond_count=excluded.rotatable_bond_count,
            heavy_atom_count=excluded.heavy_atom_count,
            formal_charge=excluded.formal_charge,
            computed_properties=excluded.computed_properties,
            physical_properties=excluded.physical_properties,
            ghs_classification=excluded.ghs_classification,
            hazards=excluded.hazards,
            safety_measures=excluded.safety_measures,
            toxicity=excluded.toxicity,
            regulatory=excluded.regulatory,
            pharmacology=excluded.pharmacology,
            uses_and_manufacturing=excluded.uses_and_manufacturing,
            identifier_evidence=excluded.identifier_evidence,
            source_references=excluded.source_references,
            external_ids=excluded.external_ids,
            ghs_codes=excluded.ghs_codes,
            reactivity=excluded.reactivity,
            pubchem_created_on=excluded.pubchem_created_on,
            pubchem_modified_on=excluded.pubchem_modified_on,
            fetched_at=excluded.fetched_at,
            updated_at=excluded.updated_at
    """), params)

async def verified_cas_lease(db: Any, proof: LeaseProof, worker_id: str, *, lock: bool = True):
    suffix = " FOR UPDATE" if lock else ""
    row = (await db.execute(text(f"""
        SELECT id,chemical_id,cas_number
        FROM maintenance.cas_jobs
        WHERE id=:job_id AND status='leased' AND lease_owner=:worker_id
          AND lease_token_hash=:lease_hash AND lease_expires_at>now(){suffix}
    """), {
        "job_id": proof.job_id,
        "worker_id": worker_id,
        "lease_hash": lease_hash(proof.lease_token),
    })).fetchone()
    if not row:
        raise LeaseConflictError("lease is missing, expired, or owned by another worker")
    return row
