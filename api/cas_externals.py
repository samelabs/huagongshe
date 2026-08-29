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
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from .cache import cache_delete, get_cache
from .database import get_db
from .name_index import ingest_from_entry_cn

# 时间只记录不驱动(2026-08-29定): 化学数据基本不变, 一切TTL回补环拆除。
# chemical_cb.expires_at 恒 NULL(建表列保留, 兼容); fetched_at 即
# "何时取到 / 何时确认没有"。ok 与 not_found 同为终态;
# 回补 = 未来手动脚本, 不进自动机制。
SYNC_FETCH_BUDGET_S = 3.0
CACHE_KEY = "v3:cas-ext:{chemical_id}"  # v3: 表改名+locale(2026-08-28)
CACHE_TTL_S = 6 * 3600
MAX_ENTRY_JSON_BYTES = 2_000_000  # 双保险: workapi 载荷上限内的条目尺寸


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_externals_row(db: Any, chemical_id: int) -> dict[str, Any] | None:
    row = (await db.execute(text("""
        SELECT chemical_id,cas_number,entry,last_status,fetched_at
        FROM chemistry.chemical_cb WHERE chemical_id=:chemical_id AND locale='zh-CN'
    """), {"chemical_id": chemical_id})).mappings().fetchone()
    return dict(row) if row else None


async def get_suppliers(db: Any, chemical_id: int) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT ref,name,phone,email,website,purity,pack_price,remark
        FROM chemistry.chemical_supplier WHERE chemical_id=:chemical_id ORDER BY ref
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
    locale: str = "zh-CN",
) -> None:
    """worker complete 与同步拉取共用的唯一写入口(事务由调用方管理)。

    cb_number/cbsid 为原站身份标识: cb_number 落主表 chemicals(2026-08-28 上移,
    chemical_cb 不存); cbsid 落 chemical_supplier, 任何 API/DOM 输出零标识。
    locale: zh-CN 为主行(供应商同写); en 等语言行只写 entry, suppliers 恒空。
    """
    entry_json = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) if entry else None
    if entry_json and len(entry_json.encode()) > MAX_ENTRY_JSON_BYTES:
        raise ValueError("cas entry payload exceeds safety limit")
    # 时间只记录不驱动(2026-08-29定): 化学数据基本不变, 一切TTL回补环
    # 拆除 — expires_at 恒 NULL, fetched_at 即"何时取到/何时确认没有"。
    # ok 与 not_found 同为终态; 回补是未来手动脚本的事, 不进自动机制。
    expires = None
    await db.execute(text("""
        INSERT INTO chemistry.chemical_cb
            (chemical_id,cas_number,entry,last_status,fetched_at,expires_at,locale)
        VALUES
            (:chemical_id,:cas_number,CAST(:entry AS jsonb),:status,now(),:expires,:locale)
        ON CONFLICT (chemical_id, locale) DO UPDATE SET
            cas_number=excluded.cas_number,
            entry=excluded.entry,
            last_status=excluded.last_status,
            fetched_at=excluded.fetched_at,
            expires_at=excluded.expires_at,
            updated_at=now()
    """), {
        "chemical_id": chemical_id, "cas_number": cas_number,
        "entry": entry_json, "status": status, "expires": expires,
        "locale": locale,
    })
    # CB 号上移主表: 只补空不覆盖(同号不同品目由 partial unique 兜底)
    if cb_number:
        await db.execute(text("""
            UPDATE chemistry.chemicals
            SET cb_number=coalesce(cb_number, :cb), updated_at=now()
            WHERE id=:chemical_id
        """), {"cb": cb_number, "chemical_id": chemical_id})
    # name_index 摄入: 仅 zh-CN 主行(镜像)
    if locale == "zh-CN":
        await ingest_from_entry_cn(
            db, chemical_id, entry,
            [s.get("name") for s in suppliers] if status == "ok" else [],
        )
    # 供应商: cbsid 键 upsert(有值 UPDATE 无值 INSERT)。仅 zh-CN 主行写;
    # locale(国家)只补空(GW/CPP 数据源合并, 不覆盖既有判定)。
    # 残留防护: 本轮未出现的行(cbsid/ref 都不在)DELETE, 防 CB 下架供应商驻留。
    if locale == "zh-CN":
        if status == "ok":
            await db.execute(text("""
                DELETE FROM chemistry.chemical_supplier a
                WHERE a.chemical_id=:chemical_id
                  AND (a.cbsid IS NULL OR a.cbsid <> ALL(CAST(:cbsids AS text[])))
                  AND a.ref <> ALL(CAST(:refs AS text[]))
            """), {"chemical_id": chemical_id,
                   "cbsids": [s.get("cbsid") for s in suppliers if s.get("cbsid")],
                   "refs": [s.get("ref") for s in suppliers]})
            if suppliers:
                await db.execute(text("""
                    INSERT INTO chemistry.chemical_supplier
                        (chemical_id,ref,cbsid,name,phone,email,website,purity,pack_price,remark,locale)
                    SELECT :chemical_id,* FROM unnest(
                        CAST(:refs AS text[]),CAST(:cbsids AS text[]),
                        CAST(:names AS text[]),
                        CAST(:phones AS text[]),CAST(:emails AS text[]),CAST(:websites AS text[]),
                        CAST(:purities AS text[]),CAST(:packs AS text[]),CAST(:remarks AS text[]),
                        CAST(:locales AS text[]))
                    AS t(ref,cbsid,name,phone,email,website,purity,pack_price,remark,locale)
                    ON CONFLICT (chemical_id, ref) DO UPDATE SET
                        cbsid=coalesce(excluded.cbsid, chemistry.chemical_supplier.cbsid),
                        name=excluded.name,
                        phone=coalesce(excluded.phone, chemistry.chemical_supplier.phone),
                        email=coalesce(excluded.email, chemistry.chemical_supplier.email),
                        website=coalesce(excluded.website, chemistry.chemical_supplier.website),
                        purity=excluded.purity,
                        pack_price=excluded.pack_price,
                        remark=excluded.remark,
                        locale=coalesce(chemistry.chemical_supplier.locale, excluded.locale)
                """), _suppliers_params(chemical_id, suppliers))
        else:
            await db.execute(text("""
                DELETE FROM chemistry.chemical_supplier WHERE chemical_id=:chemical_id
            """), {"chemical_id": chemical_id})


def _suppliers_params(chemical_id: int, suppliers: list[dict[str, Any]]) -> dict[str, Any]:
    def col(key: str) -> list[str | None]:
        return [s.get(key) for s in suppliers]
    return {
        "chemical_id": chemical_id,
        "refs": col("ref"), "cbsids": col("cbsid"), "names": col("name"),
        "phones": col("phone"), "emails": col("email"), "websites": col("website"),
        "purities": col("purity"), "packs": col("pack_price"), "remarks": col("remark"),
        "locales": col("locale"),
    }


def _dedupe_key(chemical_id: int, cas_number: str, locale: str = "zh-CN") -> str:
    digest = hashlib.sha256(cas_number.strip().encode()).hexdigest()[:16]
    # locale 后缀: 语言行与主行各自独立去重(否则 en 任务会被 zh 活跃窗口吞掉)
    suffix = "" if locale == "zh-CN" else f":{locale}"
    return f"cas:{chemical_id}:{digest}{suffix}"


async def enqueue_cas_job(
    db: Any,
    *,
    chemical_id: int,
    cas_number: str,
    priority: int = 50,
    locale: str = "zh-CN",
    request_context: dict[str, Any] | None = None,
) -> int | None:
    """活跃窗口去重入队; 已有活跃任务时返回 None。

    locale>zh-CN 为语言行任务: 租约端从 request_context->>'locale' 寻址。
    """
    context = dict(request_context or {})
    context["locale"] = locale
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
        "priority": priority, "dedupe_key": _dedupe_key(chemical_id, cas_number, locale),
        "context": json.dumps(context, ensure_ascii=False),
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
          AND completed_at > now()-interval '30 days'
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

    入口(搜索miss入队)已确认本地无此CAS, 此处不再查重(2026-08-29定,
    冗余二次动作)。名称归属: 中文名/别名随 chemical_cb 语言行(entry.basic/
    aliases), 不抄主表; 主表只落 preferred_name(英文名,缺则CAS号) +
    式/量。statistics.exact_count 同步+1 (镜像 reactions.py 建行口径)。
    """
    name_en = _basic_field(entry, "英文名称") or cas_number
    formula = _basic_field(entry, "分子式")
    mass_raw = _basic_field(entry, "分子量")
    try:
        mass = float(mass_raw) if mass_raw else None
    except ValueError:
        mass = None
    chemical_id = int((await db.execute(text("""
        INSERT INTO chemistry.chemicals
            (preferred_name,synonyms,molecular_formula,average_mass,cas_numbers,
             created_at,updated_at)
        VALUES
            (:name,'[]'::jsonb,:formula,:mass,ARRAY[:cas],now(),now())
        RETURNING id
    """), {
        "name": name_en,
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
    from caslib.parse import (
        cpp_page_state, parse_cpp_entry, parse_cpp_suppliers, parse_entry,
        parse_suppliers,
    )

    async def _fetch() -> tuple[str, dict | None, list, str | None]:
        result = await fetch_cas(cas_number, total_budget_s=SYNC_FETCH_BUDGET_S)
        if result.status == "error":
            return "error", None, [], None
        if result.status == "not_found":
            return "not_found", None, [], None
        # 上游"系统忙"限流: 语义=error, 同步路径不落行走入队
        if result.cpp_html and cpp_page_state(result.cpp_html) in ("busy", "empty"):
            return "error", None, [], None
        # CPP-CN 页为主(信息更全+100家供应商+国家); 缺席退 CAS 页旧链
        entry = parse_cpp_entry(result.cpp_html) if result.cpp_html else None
        suppliers = parse_cpp_suppliers(result.cpp_html or "") if result.cpp_html else []
        if entry is None and result.cas_html:
            entry = parse_entry(result.cas_html)
        if not suppliers and result.cas_html:
            suppliers = parse_suppliers(result.cas_html, None)
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
    {state: fresh|queued|absent, entry, suppliers, job_id}
    - fresh: ok 行直接出 / not_found 行出空(negative)
    - absent: 无 cb 行(首访) — 调用方(sync路径)决定同步拉或入队
    时间只记录不驱动(2026-08-29定): 无TTL无stale环, error终态不自动重试。
    """
    redis = await get_cache()
    cache_key = CACHE_KEY.format(chemical_id=chemical_id)
    try:
        cached = await redis.get(cache_key)
        if cached:
            payload = json.loads(cached)
            if payload.get("state") == "fresh":
                return payload
    except Exception:
        pass

    row = await get_externals_row(db, chemical_id)
    if row is None:
        return {"state": "absent", "entry": None, "suppliers": [], "job_id": None}
    if row["last_status"] == "not_found":
        # 终态: 恒"确认没有", 永不入队。fetched_at=确认时间。
        return {"state": "fresh", "entry": None, "suppliers": [], "job_id": None,
                "negative": True}
    if row["last_status"] == "error":
        # 拉取异常终态: 不自动重试(回补是未来手动脚本的事)。
        return {"state": "fresh", "entry": None, "suppliers": [], "job_id": None,
                "error": True}
    # ok 行: 终态直出。suppliers 同行取。
    suppliers = await get_suppliers(db, chemical_id)
    payload = {"state": "fresh", "entry": row["entry"], "suppliers": suppliers,
               "job_id": None}
    try:
        await redis.set(cache_key, json.dumps(payload, ensure_ascii=False,
                                              default=str), ex=CACHE_TTL_S)
    except Exception:
        pass
    return payload


async def scan_expired_into_queue(db: Any, batch: int = 200) -> int:
    """已退役(2026-08-29定): TTL回补环全拆 — 时间只记录不驱动。
    ok/not_found 同为终态, 无到期无回炉。回补=未来手动脚本。
    保留空壳防外部调用报错; 返回 0。
    """
    return 0
