"""§3 PubChem identity discovery 服务层 — InChIKey → candidate CID。

职责边界(§3 立项令):
- discovery 只产出候选证据, 绝不写 chemistry.chemicals 任何字段,
  绝不调用 absorb/merge;
- 单 CID 返回 = CANDIDATE, 不是 identity 裁定; 最终 authority 是
  §2 frozen adjudication(enrichment callback 链);
- 唯一出口 = candidate handoff: 同一事务内 canonicalize → 证据新鲜度
  复核 → 入既有 pubchem_jobs(query_value=CID) → identity job 置
  candidate, 任一步失败全 rollback。

状态机(§3 修正2):
  queued → leased → candidate | not_found | ambiguous | conflict
                        | superseded | error
- error 行留痕永不派发, 复活=同请求到达入列口翻态(对齐 cas_jobs);
- 终态不自动复活, 新 evidence_hash 才允许新 job(全局 UNIQUE dedupe)。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

INCHIKEY_ONLY = "inchikey"  # MVP 唯一 evidence 类型


async def canonicalize_id(db: Any, chemical_id: int) -> int:
    """redirect 解析(委托 identity, 不重复实现)。"""
    from .identity import canonicalize_id as _canon
    return int(await _canon(db, chemical_id))


def _evidence_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dedupe_key(chemical_id: int, evidence_type: str, evidence_hash: str) -> str:
    return f"disc:{chemical_id}:{evidence_type}:{evidence_hash}"


async def enqueue_discovery(
    db: Any,
    *,
    chemical_id: int,
    inchikey: str,
    priority: int = 60,
    request_context: dict[str, Any] | None = None,
) -> int | None:
    """触发入口(仅本地 DB 动作, 零网络): 幂等 upsert discovery job。

    全局 UNIQUE dedupe_key 语义(§3 修正1):
    - 同 evidence 活态(queued/leased) → 幂等刷新 priority, 不新建;
    - error → 翻态 queued 复活;
    - 终态(candidate/not_found/ambiguous/superseded/conflict) → 不复活;
    - 新 evidence_hash → 新 dedupe_key = 新行。
    返回 job id; 终态已存在时返回 None(调用方无感知, 不阻塞业务)。
    """
    ehash = _evidence_hash(inchikey)
    key = _dedupe_key(chemical_id, INCHIKEY_ONLY, ehash)
    row = (await db.execute(text("""
        INSERT INTO maintenance.pubchem_identity_jobs
            (chemical_id,evidence_type,evidence_value,evidence_hash,
             status,priority,dedupe_key,request_context)
        VALUES
            (:chemical_id,:evidence_type,:evidence_value,:evidence_hash,
             'queued',:priority,:dedupe_key,
             CAST(:request_context AS jsonb))
        ON CONFLICT (dedupe_key) DO UPDATE SET
            status=CASE WHEN maintenance.pubchem_identity_jobs.status='error'
                     THEN 'queued' ELSE maintenance.pubchem_identity_jobs.status END,
            priority=greatest(
                maintenance.pubchem_identity_jobs.priority, excluded.priority),
            updated_at=now()
        RETURNING id, status
    """), {
        "chemical_id": chemical_id,
        "evidence_type": INCHIKEY_ONLY,
        "evidence_value": inchikey,
        "evidence_hash": ehash,
        "priority": priority,
        "dedupe_key": key,
        "request_context": json.dumps(request_context or {}, ensure_ascii=False),
    })).fetchone()
    if row is None:  # ON CONFLICT 不可能 None, 防御
        return None
    return int(row[0])


async def complete_discovery(
    db: Any,
    *,
    job_id: int,
    cid_list: list[int],
) -> str:
    """discovery complete(§3 修正2+3): 单事务裁定 + candidate 原子 handoff。

    输入 cid_list = PubChem /cids 返回的原始 CID 集合(零裁剪):
    - 空 → not_found(负缓存: 绑定 evidence_hash, 同证据不重查);
    - >1 → ambiguous(不 first-hit, 终态);
    - 1 → candidate handoff(见模块 docstring), 失败整事务 rollback。

    freshness recheck(handoff 前强制, 使用结果前):
    canonicalize → 重读 canonical row → 验证 pubchem_cid IS NULL →
    验证 inchikey == job.evidence_value; 任一不满足 → superseded。

    返回终态字符串(candidate/not_found/ambiguous/superseded)。
    调用方(workapi)持有外层事务, 本函数不 commit — rollback 由调用方
    异常路径统一处理。
    """
    job = (await db.execute(text("""
        SELECT id,chemical_id,evidence_type,evidence_value
        FROM maintenance.pubchem_identity_jobs
        WHERE id=:job_id AND status='leased'
    """), {"job_id": job_id})).fetchone()
    if job is None:
        from fastapi import HTTPException
        raise HTTPException(409, "identity job is not leased")

    chem_raw = int(job[1])
    evidence_value = job[3]

    if not cid_list:
        await db.execute(text("""
            UPDATE maintenance.pubchem_identity_jobs
            SET status='not_found',result=CAST(:result AS jsonb),
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                updated_at=now()
            WHERE id=:job_id
        """), {"job_id": job_id, "result": json.dumps({"cids": []})})
        return "not_found"

    if len(cid_list) > 1:
        await db.execute(text("""
            UPDATE maintenance.pubchem_identity_jobs
            SET status='ambiguous',result=CAST(:result AS jsonb),
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                updated_at=now()
            WHERE id=:job_id
        """), {"job_id": job_id,
               "result": json.dumps({"cids": [int(c) for c in cid_list]})})
        return "ambiguous"

    candidate_cid = int(cid_list[0])

    # ── freshness recheck(§3 修正2): 使用结果前强制 ──
    canonical = await canonicalize_id(db, chem_raw)
    row = (await db.execute(text("""
        SELECT pubchem_cid,inchikey FROM chemistry.chemicals WHERE id=:id
    """), {"id": canonical})).fetchone()
    if (row is None
            or row[0] is not None
            or row[1] != evidence_value):
        await db.execute(text("""
            UPDATE maintenance.pubchem_identity_jobs
            SET status='superseded',
                result=CAST(:result AS jsonb),
                lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
                updated_at=now()
            WHERE id=:job_id
        """), {"job_id": job_id,
               "result": json.dumps({
                   "candidate_cid": candidate_cid,
                   "reason": "evidence-stale-or-row-changed"})})
        return "superseded"

    # ── candidate handoff(§3 修正3): 同一事务原子完成 ──
    from .enrichment import enqueue_job
    await enqueue_job(
        db,
        chemical_id=canonical,
        cid=candidate_cid,
        priority=60,
        request_context={"origin": "identity_discovery",
                         "evidence_type": INCHIKEY_ONLY},
    )
    await db.execute(text("""
        UPDATE maintenance.pubchem_identity_jobs
        SET status='candidate',
            result=CAST(:result AS jsonb),
            lease_owner=NULL,lease_token_hash=NULL,lease_expires_at=NULL,
            updated_at=now()
        WHERE id=:job_id
    """), {"job_id": job_id,
           "result": json.dumps({"candidate_cid": candidate_cid})})
    logger.info("identity_discovery_candidate job=%s chemical_id=%s cid=%s",
                job_id, canonical, candidate_cid)
    return "candidate"
