"""cas-externals: ChemicalBook 中文条目/供应商 懒加载读写层.

机制镜像 enrichment.py(pubchem 链):
- ensure_externals(): fresh 直出 | miss 同步拉(3s 预算,线程池) | stale 出旧+入队
- not_found 落行为负缓存
- 入队 ON CONFLICT 活跃窗口去重
本模块不挂公开路由(批次3 由 /chemicals/{id}/externals 与 SSR 调用);
workapi 的 cas complete 载荷写入也复用此处的 upsert。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from .cache import cache_delete, get_cache
from .database import get_db
from .name_index import ingest_from_entry_cn

# entry 30d / suppliers 7d: 两周期独立驱动 — cas_externals.expires_at 取
# entry 周期(30d), cas_suppliers 自带 fetched_at, 刷新任务同趟刷新两者,
# 任务到期判定 = min(entry 剩余, suppliers 剩余) — 由 ensure 层计算,表结构不感知。
ENTRY_TTL_DAYS = 30
SUPPLIERS_TTL_DAYS = 7
NOT_FOUND_TTL_DAYS = 1  # 负缓存: not_found 行 1 天内不重试
SYNC_FETCH_BUDGET_S = 3.0
CACHE_KEY = "v2:cas-ext:{chemical_id}"
CACHE_TTL_S = 6 * 3600
MAX_ENTRY_JSON_BYTES = 2_000_000  # 双保险: workapi 载荷上限内的条目尺寸


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry_expires() -> datetime:
    return _now() + timedelta(days=ENTRY_TTL_DAYS)


def _not_found_expires() -> datetime:
    return _now() + timedelta(days=NOT_FOUND_TTL_DAYS)


def suppliers_fresh(fetched_at: Any) -> bool:
    if not isinstance(fetched_at, datetime):
        return False
    value = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    return value >= _now() - timedelta(days=SUPPLIERS_TTL_DAYS)


async def get_externals_row(db: Any, chemical_id: int) -> dict[str, Any] | None:
    row = (await db.execute(text("""
        SELECT chemical_id,cas_number,entry_cn,last_status,fetched_at,expires_at
        FROM chemistry.cas_externals WHERE chemical_id=:chemical_id
    """), {"chemical_id": chemical_id})).mappings().fetchone()
    return dict(row) if row else None


async def get_suppliers(db: Any, chemical_id: int) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT ref,name,phone,email,website,purity,pack_price,remark
        FROM chemistry.cas_suppliers WHERE chemical_id=:chemical_id ORDER BY ref
    """), {"chemical_id": chemical_id})).fetchall()
    return [dict(r._mapping) for r in rows]


async def upsert_externals(
    db: Any,
    *,
    chemical_id: int,
    cas_number: str,
    entry: dict[str, Any] | None,
    suppliers: list[dict[str, Any]],
    status: str,
    cb_number: str | None = None,
) -> None:
    """worker complete 与同步拉取共用的唯一写入口(事务由调用方管理)。

    cb_number/cbsid 为原站身份标识: 只落DB, 任何API/DOM输出不经手(公开面零标识)。
    """
    entry_json = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) if entry else None
    if entry_json and len(entry_json.encode()) > MAX_ENTRY_JSON_BYTES:
        raise ValueError("cas entry payload exceeds safety limit")
    expires = _entry_expires() if status == "ok" else (
        _not_found_expires() if status == "not_found" else None
    )
    await db.execute(text("""
        INSERT INTO chemistry.cas_externals
            (chemical_id,cas_number,entry_cn,last_status,fetched_at,expires_at,cb_number)
        VALUES
            (:chemical_id,:cas_number,CAST(:entry AS jsonb),:status,now(),:expires,
             NULLIF(:cb_number,''))
        ON CONFLICT (chemical_id) DO UPDATE SET
            cas_number=excluded.cas_number,
            entry_cn=excluded.entry_cn,
            last_status=excluded.last_status,
            fetched_at=excluded.fetched_at,
            expires_at=excluded.expires_at,
            cb_number=excluded.cb_number,
            updated_at=now()
    """), {
        "chemical_id": chemical_id, "cas_number": cas_number,
        "entry": entry_json, "status": status, "expires": expires,
        "cb_number": cb_number,
    })
    # name_index 摄入: 与 cas_externals 同事务, 纯镜像
    await ingest_from_entry_cn(
        db, chemical_id, entry,
        [s.get("name") for s in suppliers] if status == "ok" else [],
    )
    # 主档+关联表: GN 供应商(含 CAS 页与专用页合并产物)按 cbsid 入注册表
    if status == "ok" and suppliers:
        await upsert_supplier_registry(
            db, cas_number=cas_number, suppliers=suppliers, source="gn",
        )
    # 供应商: cbsid 键 upsert(2026-08-28 定案: 有值 UPDATE, 无值 INSERT)。
    # 仅 ok 时写入; not_found 清空。残留防护: 化合物层面先清掉本轮未出现的行,
    # 防止 CB 下架供应商后旧行永久驻留(整组语义不变, 行内改为按 cbsid 更新)。
    if status == "ok":
        await db.execute(text("""
            DELETE FROM chemistry.cas_suppliers a
            WHERE a.chemical_id=:chemical_id
              AND (a.cbsid IS NULL OR a.cbsid <> ALL(CAST(:cbsids AS text[])))
              AND a.ref <> ALL(CAST(:refs AS text[]))
        """), {"chemical_id": chemical_id,
               "cbsids": [s.get("cbsid") for s in suppliers if s.get("cbsid")],
               "refs": [s.get("ref") for s in suppliers]})
        if suppliers:
            await db.execute(text("""
                INSERT INTO chemistry.cas_suppliers
                    (chemical_id,ref,cbsid,name,phone,email,website,purity,pack_price,remark)
                SELECT :chemical_id,* FROM unnest(
                    CAST(:refs AS text[]),CAST(:cbsids AS text[]),
                    CAST(:names AS text[]),
                    CAST(:phones AS text[]),CAST(:emails AS text[]),CAST(:websites AS text[]),
                    CAST(:purities AS text[]),CAST(:packs AS text[]),CAST(:remarks AS text[]))
                AS t(ref,cbsid,name,phone,email,website,purity,pack_price,remark)
                ON CONFLICT (chemical_id, ref) DO UPDATE SET
                    cbsid=coalesce(excluded.cbsid, chemistry.cas_suppliers.cbsid),
                    name=excluded.name,
                    phone=coalesce(excluded.phone, chemistry.cas_suppliers.phone),
                    email=coalesce(excluded.email, chemistry.cas_suppliers.email),
                    website=coalesce(excluded.website, chemistry.cas_suppliers.website),
                    purity=excluded.purity,
                    pack_price=excluded.pack_price,
                    remark=excluded.remark
            """), _suppliers_params(chemical_id, suppliers))
    else:
        await db.execute(text("""
            DELETE FROM chemistry.cas_suppliers WHERE chemical_id=:chemical_id
        """), {"chemical_id": chemical_id})


def _suppliers_params(chemical_id: int, suppliers: list[dict[str, Any]]) -> dict[str, Any]:
    def col(key: str) -> list[str | None]:
        return [s.get(key) for s in suppliers]
    return {
        "chemical_id": chemical_id,
        "refs": col("ref"), "cbsids": col("cbsid"), "names": col("name"),
        "phones": col("phone"), "emails": col("email"), "websites": col("website"),
        "purities": col("purity"), "packs": col("pack_price"), "remarks": col("remark"),
    }


# ---- 供应商主档 + 品目关联(2026-08-28 定案: 专表+关联表) ---------------------

async def upsert_supplier_registry(
    db: Any,
    *,
    cas_number: str,
    suppliers: list[dict[str, Any]],
    source: str,
) -> None:
    """GN/GW 供应商 -> cb_suppliers 主档(键 cbsid) + cb_product_suppliers 关联(键 cas↔cbsid)。

    主档字段随供应商(coalesce 保守), 品级字段随品目(关联行); nationality/cb_index
    仅 GW 有, GN 行不覆盖已有国际主档信息。无 cbsid 行不入(无身份键)。
    """
    rows = [s for s in suppliers if s.get("cbsid")]
    if not rows:
        return
    await db.execute(text("""
        INSERT INTO chemistry.cb_suppliers
            (cbsid, name, nationality, phone, email, website, cb_index)
        SELECT * FROM unnest(
            CAST(:cbsids AS text[]), CAST(:names AS text[]),
            CAST(:nationalities AS text[]), CAST(:phones AS text[]),
            CAST(:emails AS text[]), CAST(:websites AS text[]),
            CAST(:cb_indexes AS integer[]))
        AS t(cbsid, name, nationality, phone, email, website, cb_index)
        ON CONFLICT (cbsid) DO UPDATE SET
            name=excluded.name,
            nationality=coalesce(excluded.nationality, chemistry.cb_suppliers.nationality),
            phone=coalesce(excluded.phone, chemistry.cb_suppliers.phone),
            email=coalesce(excluded.email, chemistry.cb_suppliers.email),
            website=coalesce(excluded.website, chemistry.cb_suppliers.website),
            cb_index=coalesce(excluded.cb_index, chemistry.cb_suppliers.cb_index),
            last_seen_at=now()
    """), {
        "cbsids": [s["cbsid"] for s in rows],
        "names": [s.get("name") for s in rows],
        "nationalities": [s.get("nationality") for s in rows],
        "phones": [s.get("phone") for s in rows],
        "emails": [s.get("email") for s in rows],
        "websites": [s.get("website") for s in rows],
        "cb_indexes": [s.get("cb_index") for s in rows],
    })
    await db.execute(text("""
        INSERT INTO chemistry.cb_product_suppliers
            (cas_number, cbsid, source, product_name_en, purity, pack_price, remark)
        SELECT * FROM unnest(
            CAST(:cas AS text[]), CAST(:cbsids AS text[]), CAST(:sources AS text[]),
            CAST(:pnens AS text[]), CAST(:purities AS text[]),
            CAST(:packs AS text[]), CAST(:remarks AS text[]))
        AS t(cas_number, cbsid, source, product_name_en, purity, pack_price, remark)
        ON CONFLICT (cas_number, cbsid) DO UPDATE SET
            source=excluded.source,
            product_name_en=coalesce(excluded.product_name_en, chemistry.cb_product_suppliers.product_name_en),
            purity=coalesce(excluded.purity, chemistry.cb_product_suppliers.purity),
            pack_price=coalesce(excluded.pack_price, chemistry.cb_product_suppliers.pack_price),
            remark=coalesce(excluded.remark, chemistry.cb_product_suppliers.remark),
            last_seen_at=now()
    """), {
        "cas": [cas_number] * len(rows),
        "cbsids": [s["cbsid"] for s in rows],
        "sources": [source] * len(rows),
        "pnens": [s.get("product_name_en") for s in rows],
        "purities": [s.get("purity") for s in rows],
        "packs": [s.get("pack_price") for s in rows],
        "remarks": [s.get("remark") for s in rows],
    })


def _dedupe_key(chemical_id: int, cas_number: str) -> str:
    digest = hashlib.sha256(cas_number.strip().encode()).hexdigest()[:16]
    return f"cas:{chemical_id}:{digest}"


async def enqueue_cas_job(
    db: Any,
    *,
    chemical_id: int,
    cas_number: str,
    priority: int = 50,
    request_context: dict[str, Any] | None = None,
) -> int | None:
    """活跃窗口去重入队; 已有活跃任务时返回 None。"""
    row = (await db.execute(text("""
        INSERT INTO maintenance.cas_jobs
            (chemical_id,cas_number,priority,dedupe_key,request_context)
        VALUES
            (:chemical_id,:cas_number,:priority,:dedupe_key,
             CAST(:context AS jsonb))
        ON CONFLICT (dedupe_key) WHERE status IN ('queued','leased','retry')
        DO UPDATE SET priority=greatest(maintenance.cas_jobs.priority,excluded.priority),
                      updated_at=now()
        RETURNING id
    """), {
        "chemical_id": chemical_id, "cas_number": cas_number.strip(),
        "priority": priority, "dedupe_key": _dedupe_key(chemical_id, cas_number),
        "context": json.dumps(request_context or {}, ensure_ascii=False),
    })).fetchone()
    return int(row[0]) if row else None


# ---- 搜索miss -> CB建行 (standalone cas job) -------------------------------
# 边界(2026-08-27定案): 不做建行比对(防污染既有行); 允许有/无CAS行同存;
# PubChem侧只update不insert(sync_chemical_core coalesce), 天然补全无重复。

SEARCH_MISS_PRIORITY = 80       # 用户触发 > 后台刷新(30/50)
SEARCH_MISS_MAX_QUEUE = 1000    # 活跃队列深度闸门: 超过则不再入队(爆灌降级)


# ---- CB 结构三件写入(smiles/inchikey/mol, 只补空不覆盖) ---------------------
# 依据: 详情页"物理化学性质"区 xztr 自带 SMILES/InChI/InChIKey(已入 props),
# mol 文件是 worker 同趟附带。口径: 页面三件优先, mol 派生兜底; 主表宁缺勿错
# —— RDKit 校验不过的值整字段丢弃, 绝不把脏值写进 chemicals。

def _props_field(entry: dict[str, Any], label: str) -> str | None:
    """CB props 块取字段(物理化学性质区 xztr 行)。"""
    for item in entry.get("props") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] == label:
            value = str(item[1]).strip()
            return value or None
    return None


def _validate_smiles(smiles: str | None) -> str | None:
    """RDKit 解析+规范化; 失败返回 None(整字段丢弃)。"""
    if not smiles:
        return None
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        canonical = Chem.MolToSmiles(mol)
        return canonical or None
    except Exception:
        return None


def _derive_from_molblock(molblock: str | None) -> tuple[str | None, str | None]:
    """molblock -> (canonical smiles, inchikey); 解析失败 (None, None)。

    mol 列是 cartridge mol 类型: 必须走 mol_from_ctab(直绑按 SMILES 解析必炸,
    实测 DataError)。garbage 输入 mol_from_ctab 返回 NULL — 前置 RDKit 校验
    与其双保险。
    """
    if not molblock:
        return None, None
    try:
        from rdkit import Chem
        mol = Chem.MolFromMolBlock(molblock)
        if mol is None:
            return None, None
        smiles = Chem.MolToSmiles(mol) or None
        inchikey = Chem.MolToInchiKey(mol) or None
        return smiles, inchikey
    except Exception:
        return None, None


def resolve_structure(
    entry: dict[str, Any] | None, molblock: str | None
) -> dict[str, str | None]:
    """CB 三源 -> 结构字段。页面三件优先, mol 派生兜底; 全部只补空用。

    返回 {"smiles":..., "inchikey":..., "mol":...(molblock原文)}。
    校验失败的键值为 None; smiles 校验不过时 mol 仍可写(连接表本身有效)。
    """
    smiles = inchikey = None
    if entry:
        smiles = _validate_smiles(_props_field(entry, "SMILES"))
        inchikey = _props_field(entry, "InChIKey")
        if not inchikey or not smiles:
            d_smiles, d_ik = _derive_from_molblock(molblock)
            if not smiles:
                smiles = d_smiles
            if not inchikey:
                inchikey = d_ik
    mol = molblock if (molblock and _derive_from_molblock(molblock)[0]) else None
    return {"smiles": smiles, "inchikey": inchikey, "mol": mol}


async def apply_structure_fill(
    db: Any, chemical_id: int, structure: dict[str, str | None]
) -> None:
    """chemicals 结构三件只补空(coalesce 语义, 已有值不动); morgan 指纹同步生成。

    mol 写入口径照抄 reactions.py:151 建行点(cartridge 函数生成, 不裸绑文本);
    smiles 为 NULL 时 mol/指纹一并跳过(指纹由 smiles 生成, smiles 缺则结构
    检索不可用 — 与既有无结构行同等状态, 不半吊子)。
    """
    smiles = structure.get("smiles")
    if not smiles:
        return
    inchikey = structure.get("inchikey")
    molblock = structure.get("mol")
    await db.execute(text("""
        WITH incoming AS (
            SELECT CAST(:smiles AS text) AS smiles,
                   CAST(:inchikey AS text) AS inchikey
        )
        UPDATE chemistry.chemicals
        SET smiles=coalesce(chemistry.chemicals.smiles, incoming.smiles),
            inchikey=coalesce(chemistry.chemicals.inchikey, incoming.inchikey),
            -- mol_from_ctab 参数是 cstring 伪类型: 经 text 中转会 "function
            -- mol_from_ctab(text) does not exist"(实测)。参数必须直绑让 PG 推断
            -- cstring; 畸形 molblock 返回 NULL 不抛(garbage 实测)。
            mol=coalesce(chemistry.chemicals.mol, mol_from_ctab(:molblock)),
            morgan_bfp=coalesce(chemistry.chemicals.morgan_bfp,
                morganbv_fp(mol_from_smiles(incoming.smiles))),
            morgan_sfp=coalesce(chemistry.chemicals.morgan_sfp,
                morgan_fp(mol_from_smiles(incoming.smiles))),
            updated_at=now()
        FROM incoming
        WHERE chemistry.chemicals.id=:chemical_id
    """), {
        "chemical_id": chemical_id, "smiles": smiles,
        "inchikey": inchikey, "molblock": molblock,
    })


def _basic_field(entry: dict[str, Any], label: str) -> str | None:
    """CB basic 块取字段: [[标签,值],...] -> 值。"""
    for item in entry.get("basic") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] == label:
            value = str(item[1]).strip()
            return value or None
    return None


async def cas_search_state(db: Any, cas_number: str) -> str:
    """搜索miss三态: pending(活跃任务在途) / miss(负缓存命中) / new(可入队)。"""
    row = (await db.execute(text("""
        SELECT 1 FROM maintenance.cas_jobs
        WHERE cas_number=:cas AND status IN ('queued','leased','retry')
        LIMIT 1
    """), {"cas": cas_number})).first()
    if row:
        return "pending"
    row = (await db.execute(text("""
        SELECT 1 FROM maintenance.cas_jobs
        WHERE cas_number=:cas AND status='succeeded'
          AND result_summary->>'status'='not_found'
          AND completed_at > now()-interval '1 day'
        LIMIT 1
    """), {"cas": cas_number})).first()
    if row:
        return "miss"
    return "new"


async def enqueue_cas_search_fetch(db: Any, *, cas_number: str) -> bool:
    """搜索miss入队(standalone, chemical_id=NULL)。深度超闸门返回 False。"""
    depth = (await db.execute(text("""
        SELECT count(*) FROM maintenance.cas_jobs
        WHERE status IN ('queued','retry')
    """))).scalar()
    if depth is not None and int(depth) > SEARCH_MISS_MAX_QUEUE:
        return False
    digest = hashlib.sha256(cas_number.strip().encode()).hexdigest()[:16]
    await db.execute(text("""
        INSERT INTO maintenance.cas_jobs
            (chemical_id,cas_number,priority,dedupe_key,request_context)
        VALUES
            (NULL,:cas_number,:priority,:dedupe_key,
             CAST(:context AS jsonb))
        ON CONFLICT (dedupe_key) WHERE status IN ('queued','leased','retry')
        DO UPDATE SET priority=greatest(maintenance.cas_jobs.priority,excluded.priority),
                      updated_at=now()
    """), {
        "cas_number": cas_number.strip(), "priority": SEARCH_MISS_PRIORITY,
        "dedupe_key": f"cas:new:{digest}",
        "context": json.dumps({"reason": "search_miss"}, ensure_ascii=False),
    })
    return True


async def create_chemical_from_cb_entry(
    db: Any, *, cas_number: str, entry: dict[str, Any]
) -> int:
    """CB entry -> chemicals 最小行(无结构, mol=NULL)。

    已有同CAS行则直接返回其id(不建行); 否则序列取号:
    preferred_name=英文名, synonyms=中英别名, 式/量来自basic, cas_numbers单元素。
    statistics.exact_count 同步+1 (镜像 reactions.py 建行口径)。
    """
    existing = (await db.execute(text("""
        SELECT id FROM chemistry.chemicals
        WHERE cas_numbers @> ARRAY[:cas] ORDER BY id LIMIT 1
    """), {"cas": cas_number})).scalar()
    if existing is not None:
        return int(existing)
    name_en = _basic_field(entry, "英文名称") or cas_number
    name_cn = _basic_field(entry, "中文名称")
    formula = _basic_field(entry, "分子式")
    mass_raw = _basic_field(entry, "分子量")
    try:
        mass = float(mass_raw) if mass_raw else None
    except ValueError:
        mass = None
    synonyms: list[str] = []
    if name_cn:
        synonyms.append(name_cn)
    aliases = entry.get("aliases") or {}
    for group in (aliases.get("cn"), aliases.get("en")):
        for name in group or []:
            if name and name not in synonyms:
                synonyms.append(name)
    chemical_id = int((await db.execute(text("""
        INSERT INTO chemistry.chemicals
            (preferred_name,synonyms,molecular_formula,average_mass,cas_numbers,
             created_at,updated_at)
        VALUES
            (:name,CAST(:synonyms AS jsonb),:formula,:mass,ARRAY[:cas],now(),now())
        RETURNING id
    """), {
        "name": name_en, "synonyms": json.dumps(synonyms[:50], ensure_ascii=False),
        "formula": formula, "mass": mass, "cas": cas_number,
    })).scalar_one())
    await db.execute(text("""
        UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
        WHERE metric='chemicals'
    """))
    return chemical_id


async def sync_fetch_and_store(
    db: Any, *, chemical_id: int, cas_number: str
) -> dict[str, Any] | None:
    """同步拉取路径(详情页首访)。3s 预算, 线程池执行防阻塞事件循环。

    返回 ensure 状态字典; 网络失败/超时不落 error 行(留给 worker 重试)。
    """
    from caslib.fetch import fetch_cas
    from caslib.parse import parse_entry, parse_suppliers

    async def _fetch() -> tuple[str, dict | None, list, str | None]:
        result = await fetch_cas(cas_number, total_budget_s=SYNC_FETCH_BUDGET_S)
        if result.status == "error":
            return "error", None, [], None
        if result.status == "not_found":
            return "not_found", None, [], None
        entry = parse_entry(result.cas_html or "")
        suppliers = parse_suppliers(result.cas_html or "", result.supplier_html)
        if entry is None:
            return "not_found", None, [], None
        return "ok", entry, suppliers, result.cb_number

    try:
        status, entry, suppliers, cb_number = await asyncio.wait_for(
            _fetch(), timeout=SYNC_FETCH_BUDGET_S + 1.5,
        )
    except Exception:
        return None  # 网络层失败: 不落行, 走入队
    if status == "error":
        return None
    await upsert_externals(
        db, chemical_id=chemical_id, cas_number=cas_number.strip(),
        entry=entry, suppliers=suppliers, status=status,
        cb_number=cb_number,
    )
    await db.commit()
    await cache_delete(CACHE_KEY.format(chemical_id=chemical_id))
    return {"status": status}


async def ensure_externals(
    db: Any, chemical_id: int, *, cas_number: str
) -> dict[str, Any]:
    """ensure 链入口。返回:
    {state: fresh|stale|queued|absent, entry, suppliers, job_id}
    - fresh: 直接出
    - stale: 出旧数据 + 入队刷新
    - absent: 无数据(首访) — 调用方(sync路径)决定同步拉或入队
    """
    redis = await get_cache()
    cache_key = CACHE_KEY.format(chemical_id=chemical_id)
    try:
        cached = await redis.get(cache_key)
        if cached:
            payload = json.loads(cached)
            # 缓存只信任"行仍在有效期内": 轻量校验行 expires_at,
            # 防止行被刷新/外部置过期后缓存继续兜售旧判定
            if payload.get("state") == "fresh":
                probe = (await db.execute(text(
                    "SELECT expires_at,fetched_at FROM chemistry.cas_externals "
                    "WHERE chemical_id=:i"
                ), {"i": chemical_id})).fetchone()
                row_fresh = bool(
                    probe and probe[0] and probe[0] > _now()
                    and suppliers_fresh(probe[1])
                )
                if row_fresh:
                    return payload
                await redis.delete(cache_key)
    except Exception:
        pass

    row = await get_externals_row(db, chemical_id)
    if row is None:
        return {"state": "absent", "entry": None, "suppliers": [], "job_id": None}
    if row["last_status"] == "not_found":
        if row["expires_at"] and row["expires_at"] > _now():
            return {"state": "fresh", "entry": None, "suppliers": [], "job_id": None,
                    "negative": True}
        # 负缓存过期: 入队重试
        job_id = await enqueue_cas_job(
            db, chemical_id=chemical_id, cas_number=row["cas_number"],
            request_context={"reason": "negative_expiry"},
        )
        await db.commit()
        return {"state": "fresh", "entry": None, "suppliers": [], "job_id": job_id,
                "negative": True}
    if row["last_status"] == "error":
        job_id = await enqueue_cas_job(
            db, chemical_id=chemical_id, cas_number=row["cas_number"],
            request_context={"reason": "error_retry"},
        )
        await db.commit()
        return {"state": "queued", "entry": None, "suppliers": [], "job_id": job_id}
    # ok 行: 新鲜度 = entry expires_at(30d) 与 suppliers 组时间(7d)双周期;
    # 供应商整组替换, 组时间=条目行 fetched_at
    suppliers = await get_suppliers(db, chemical_id)
    entry_fresh = bool(row["expires_at"] and row["expires_at"] > _now())
    sup_fresh = suppliers_fresh(row["fetched_at"])
    payload: dict[str, Any]
    if entry_fresh and sup_fresh:
        payload = {"state": "fresh", "entry": row["entry_cn"], "suppliers": suppliers,
                   "job_id": None}
    else:
        job_id = await enqueue_cas_job(
            db, chemical_id=chemical_id, cas_number=row["cas_number"], priority=60,
            request_context={"reason": "stale_refresh"},
        )
        await db.commit()
        payload = {"state": "stale", "entry": row["entry_cn"], "suppliers": suppliers,
                   "job_id": job_id}
    try:
        if payload["state"] == "fresh":
            await redis.set(cache_key, json.dumps(payload, ensure_ascii=False,
                                                  default=str), ex=CACHE_TTL_S)
    except Exception:
        pass
    return payload


async def scan_expired_into_queue(db: Any, batch: int = 200) -> int:
    """worker 自扫: expires_at 超期(含 not_found 负缓存到期)分批入队。"""
    rows = (await db.execute(text("""
        SELECT chemical_id,cas_number FROM chemistry.cas_externals
        WHERE expires_at IS NOT NULL AND expires_at<now()
        ORDER BY expires_at LIMIT :batch
    """), {"batch": batch})).fetchall()
    enqueued = 0
    for r in rows:
        job_id = await enqueue_cas_job(
            db, chemical_id=r[0], cas_number=r[1], priority=30,
            request_context={"reason": "expiry_scan"},
        )
        if job_id:
            enqueued += 1
    if enqueued:
        await db.commit()
    return enqueued
