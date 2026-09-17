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
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

from ..core.cache import cache_delete, get_cache
from ..core.rate_limit import enforce
from .name_index import ingest_from_entry_cn

# 时间只记录不驱动(2026-08-29定): 化学数据基本不变, 一切TTL回补环拆除。
# fetched_at 即"何时取到 / 何时确认没有"。ok 与 not_found 同为终态;
# 回补 = 未来手动脚本, 不进自动机制。
SYNC_FETCH_BUDGET_S = 3.0
CACHE_KEY = "v4:cas-ext:{chemical_id}"  # v4: 0905 CB entry schema 规范化(canonical)
CACHE_TTL_S = 6 * 3600
MAX_ENTRY_JSON_BYTES = 2_000_000  # 双保险: workapi 载荷上限内的条目尺寸


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_externals_row(db: Any, chemical_id: int) -> dict[str, Any] | None:
    """详情读路径: 优先主表 imprint 对应的 source 行(convenience cb),
    回落任意 zh-CN 行(legacy/多行任意一条, 与旧行为兼容)。"""
    row = (await db.execute(text("""
        SELECT x.chemical_id,x.cas_number,x.entry,x.last_status,x.fetched_at,x.cb_number
        FROM chemistry.chemical_cb x
        JOIN chemistry.chemicals c ON c.id=x.chemical_id
        WHERE x.chemical_id=:chemical_id AND x.locale='zh-CN'
          AND x.cb_number IS NOT DISTINCT FROM c.cb_number
        LIMIT 1
    """), {"chemical_id": chemical_id})).mappings().fetchone()
    if row is None:
        row = (await db.execute(text("""
            SELECT chemical_id,cas_number,entry,last_status,fetched_at,cb_number
            FROM chemistry.chemical_cb
            WHERE chemical_id=:chemical_id AND locale='zh-CN'
            LIMIT 1
        """), {"chemical_id": chemical_id})).mappings().fetchone()
    return dict(row) if row else None


async def get_suppliers(db: Any, chemical_id: int) -> list[dict[str, Any]]:
    # 2026-08-31 收口: 老表迁移完成(profile 6,417/listing 449k), 双读回退桥拆除,
    # 只读两新表。旧表 chemical_supplier 已摘除。
    rows = (await db.execute(text("""
        SELECT p.ref, p.name, p.phone, p.email, p.website,
               l.purity, l.pack_price, l.remark
        FROM chemistry.chemical_supplier_listing l
        JOIN chemistry.chemical_supplier_profile p ON p.cbsid=l.cbsid
        WHERE l.chemical_id=:chemical_id
        ORDER BY p.ref
    """), {"chemical_id": chemical_id})).fetchall()
    return [dict(r._mapping) for r in rows]


def _strip_nul(value):
    """0904 P0收口: CB上游页面字段可含 U+0000, PG text/jsonb 拒绝 \u0000 转义
    (UntranslatableCharacterError 实锤于 error.log)。递归剔除, 仅处理 str,
    其他类型原样返回。entry/suppliers 全部过这一道 — 写库前的唯一清洗点。
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip_nul(v) for k, v in value.items()}
    return value


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
    2026-09-07 source grain: 亦随行写入 chemical_cb.cb_number — 一 chemical
    多 CB record (CB001/CB002/...) 各自独立成行, 不再互相覆盖; 主表 cb_number
    收窄为 convenience/first-known imprint, 完整事实在 source 行);
    cbsid 落 supplier profile/listing 两表, 任何 API/DOM 输出零标识。
    locale: zh-CN 为主行(供应商同写); en 等语言行只写 entry, suppliers 恒空。
    """
    entry = _strip_nul(entry)
    suppliers = _strip_nul(suppliers)
    entry_json = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) if entry else None
    if entry_json and len(entry_json.encode()) > MAX_ENTRY_JSON_BYTES:
        raise ValueError("cas entry payload exceeds safety limit")
    # 数据链收口(§5): 数据层只有 ok/not_found — error 不落数据层(留在 job 表)。
    # 时间只记录不驱动(2026-08-29定): 化学数据基本不变, 一切TTL回补环
    # 拆除 — fetched_at 即"何时取到/何时确认没有"。
    # ok 与 not_found 同为终态; 回补是未来手动脚本的事, 不进自动机制。
    # 0902 剥离定案: not_found 零写入 — complete 静默出列(job 层删行),
    # 收录与否由记录表本身表达(无行/主表 cb_number IS NULL)。
    if status == "not_found":
        return
    # 0907 source grain: 冲突键 (chemical_id, cb_number, locale) —
    # 同 cb 同 locale 幂等 UPSERT; 不同 cb 各自成行不覆盖。
    # cb_number=NULL(线上无号路径): 回落 legacy (chemical_id, locale) 粒度,
    # 与旧行为一致。
    if cb_number:
        await db.execute(text("""
            INSERT INTO chemistry.chemical_cb
                (chemical_id,cas_number,cb_number,entry,last_status,fetched_at,locale)
            VALUES
                (:chemical_id,:cas_number,:cb_number,
                 CAST(:entry AS jsonb),:status,now(),:locale)
            ON CONFLICT (chemical_id, cb_number, locale) WHERE cb_number IS NOT NULL
            DO UPDATE SET
                cas_number=excluded.cas_number,
                entry=excluded.entry,
                last_status=excluded.last_status,
                fetched_at=excluded.fetched_at,
                updated_at=now()
        """), {
            "chemical_id": chemical_id, "cas_number": cas_number,
            "cb_number": cb_number,
            "entry": entry_json, "status": status,
            "locale": locale,
        })
    else:
        await db.execute(text("""
            INSERT INTO chemistry.chemical_cb
                (chemical_id,cas_number,entry,last_status,fetched_at,locale)
            VALUES
                (:chemical_id,:cas_number,CAST(:entry AS jsonb),:status,now(),:locale)
            ON CONFLICT (chemical_id, locale) WHERE cb_number IS NULL
            DO UPDATE SET
                cas_number=excluded.cas_number,
                entry=excluded.entry,
                last_status=excluded.last_status,
                fetched_at=excluded.fetched_at,
                updated_at=now()
        """), {
            "chemical_id": chemical_id, "cas_number": cas_number,
            "entry": entry_json, "status": status,
            "locale": locale,
        })
    # CB 号上移主表: 只补空不覆盖。同 CAS 多 CID 行合法共享同一 cb_number
    # (CB 按 CAS 建页, CID 才是真区分键; 唯一索引已于 20260830 迁移改为普通索引)。
    if cb_number:
        await db.execute(text("""
            UPDATE chemistry.chemicals
            SET cb_number=coalesce(cb_number, :cb), updated_at=now()
            WHERE id=:chemical_id
        """), {"cb": cb_number, "chemical_id": chemical_id})
    # 0905 规范化schema: identity 直取(canonical键), 无标签兼容。
    # 分子量只接受有限正数; CAS 格式校验。仅 zh-CN ok 载荷。
    if status == "ok" and locale == "zh-CN" and entry:
        identity = entry.get("identity") or {}
        cb_name = identity.get("en")
        cb_formula = identity.get("formula")
        cb_mass = identity.get("mw")
        if cb_mass is not None and not (0 < cb_mass < 10000):
            cb_mass = None
        cb_cas = cas_number if cas_number and CAS_FORMAT_RE.fullmatch(str(cas_number).strip()) else None
        await db.execute(text("""
            UPDATE chemistry.chemicals SET
                preferred_name=coalesce(preferred_name, :nm),
                molecular_formula=coalesce(molecular_formula, :fm),
                average_mass=coalesce(average_mass, :ms),
                cas_numbers = CASE WHEN :cs = ANY(cas_numbers) OR :cs IS NULL
                    THEN cas_numbers
                    ELSE array_append(cas_numbers, :cs) END,
                updated_at=now()
            WHERE id=:chemical_id
        """), {
            "nm": cb_name, "fm": cb_formula, "ms": cb_mass,
            "cs": cb_cas, "chemical_id": chemical_id,
        })
    # name_index 摄入: 仅 zh-CN 主行(镜像)
    if locale == "zh-CN":
        await ingest_from_entry_cn(
            db, chemical_id, entry,
            [s.get("name") for s in suppliers] if status == "ok" else [],
        )
    # 供应商两表写入(2026-08-30 准线§4): 档表(cbsid主键,过期才重拉)+映射表
    # (chemical_id+cbsid 全量替换)。仅 zh-CN 主行写。
    # locale 规范化(ISO 3166-1 alpha-2)。
    if locale == "zh-CN":
        if status == "ok":
            norm_locales = [_norm_country_code(s.get("locale")) for s in suppliers]
            with_profile = [i for i, s in enumerate(suppliers) if s.get("cbsid")]
            # 1) 档表: cbsid 缺失或过期才 upsert(同 cbsid 一家一档)
            if with_profile:
                await db.execute(text("""
                    INSERT INTO chemistry.chemical_supplier_profile
                        (cbsid,name,ref,phone,email,website,locale,fetched_at,expires_at)
                    SELECT cbsid,name,ref,phone,email,website,locale,now(),
                           now()+(:expiry_days||' days')::interval
                    FROM unnest(
                        CAST(:cbsids AS text[]),CAST(:names AS text[]),CAST(:refs AS text[]),
                        CAST(:phones AS text[]),CAST(:emails AS text[]),CAST(:websites AS text[]),
                        CAST(:locales AS text[])) AS t(cbsid,name,ref,phone,email,website,locale)
                    ON CONFLICT (cbsid) DO UPDATE SET
                        name=excluded.name,
                        ref=coalesce(excluded.ref, chemistry.chemical_supplier_profile.ref),
                        phone=coalesce(excluded.phone, chemistry.chemical_supplier_profile.phone),
                        email=coalesce(excluded.email, chemistry.chemical_supplier_profile.email),
                        website=coalesce(excluded.website, chemistry.chemical_supplier_profile.website),
                        locale=coalesce(excluded.locale, chemistry.chemical_supplier_profile.locale),
                        fetched_at=now(),
                        expires_at=now()+(:expiry_days||' days')::interval
                    WHERE chemistry.chemical_supplier_profile.expires_at < now()
                       OR chemistry.chemical_supplier_profile.phone IS NULL
                """), {
                    "expiry_days": "180",
                    "cbsids": [suppliers[i].get("cbsid") for i in with_profile],
                    "names": [suppliers[i].get("name") for i in with_profile],
                    "refs": [suppliers[i].get("ref") for i in with_profile],
                    "phones": [suppliers[i].get("phone") for i in with_profile],
                    "emails": [suppliers[i].get("email") for i in with_profile],
                    "websites": [suppliers[i].get("website") for i in with_profile],
                    "locales": [norm_locales[i] for i in with_profile],
                })
            # 2) 映射表: 化合物粒度全量替换(报价纯度属化合物, 档案不随行)
            await db.execute(text("""
                DELETE FROM chemistry.chemical_supplier_listing
                WHERE chemical_id=:chemical_id
            """), {"chemical_id": chemical_id})
            if with_profile:
                await db.execute(text("""
                    INSERT INTO chemistry.chemical_supplier_listing
                        (chemical_id,cbsid,purity,pack_price,remark,fetched_at)
                    SELECT :chemical_id,cbsid,purity,pack_price,remark,now()
                    FROM unnest(
                        CAST(:cbsids AS text[]),
                        CAST(:purities AS text[]),CAST(:packs AS text[]),CAST(:remarks AS text[]))
                    AS t(cbsid,purity,pack_price,remark)
                    ON CONFLICT (chemical_id, cbsid) DO UPDATE SET
                        purity=excluded.purity,
                        pack_price=excluded.pack_price,
                        remark=excluded.remark,
                        fetched_at=now()
                """), {
                    "chemical_id": chemical_id,
                    "cbsids": [suppliers[i].get("cbsid") for i in with_profile],
                    "purities": [suppliers[i].get("purity") for i in with_profile],
                    "packs": [suppliers[i].get("pack_price") for i in with_profile],
                    "remarks": [suppliers[i].get("remark") for i in with_profile],
                })
        else:
            await db.execute(text("""
                DELETE FROM chemistry.chemical_supplier_listing
                WHERE chemical_id=:chemical_id
            """), {"chemical_id": chemical_id})
        # 2026-08-31 收口: 旧表双写拆除(迁移完成, chemical_supplier 已摘除),
        # zh 成功路径只写 profile/listing 两新表(上方已写)。


_COUNTRY_CODE_MAP = {
    "中国": "CN", "中国香港": "HK", "中国台湾": "TW", "台湾": "TW", "中国澳门": "MO",
    "日本": "JP", "韩国": "KR", "朝鲜": "KP", "美国": "US", "英国": "GB", "德国": "DE",
    "法国": "FR", "印度": "IN", "俄罗斯": "RU", "乌克兰": "UA", "加拿大": "CA",
    "匈牙利": "HU", "南非": "ZA", "巴西": "BR", "澳大利亚": "AU", "新西兰": "NZ",
    "意大利": "IT", "西班牙": "ES", "葡萄牙": "PT", "荷兰": "NL", "比利时": "BE",
    "瑞士": "CH", "奥地利": "AT", "瑞典": "SE", "挪威": "NO", "丹麦": "DK",
    "芬兰": "FI", "波兰": "PL", "捷克": "CZ", "斯洛伐克": "SK",
    "罗马尼亚": "RO", "保加利亚": "BG", "希腊": "GR", "土耳其": "TR", "以色列": "IL",
    "沙特": "SA", "阿联酋": "AE", "伊朗": "IR", "巴基斯坦": "PK", "孟加拉": "BD",
    "泰国": "TH", "越南": "VN", "马来西亚": "MY", "印度尼西亚": "ID", "印尼": "ID",
    "菲律宾": "PH", "新加坡": "SG", "墨西哥": "MX", "阿根廷": "AR", "智利": "CL",
    "哥伦比亚": "CO", "秘鲁": "PE", "埃及": "EG", "尼日利亚": "NG", "肯尼亚": "KE",
    "摩洛哥": "MA", "爱尔兰": "IE", "冰岛": "IS", "卢森堡": "LU", "马耳他": "MT",
    "爱沙尼亚": "EE", "拉脱维亚": "LV", "立陶宛": "LT", "斯洛文尼亚": "SI",
    "克罗地亚": "HR", "塞尔维亚": "RS", "白俄罗斯": "BY", "哈萨克斯坦": "KZ",
    "乌兹别克斯坦": "UZ", "蒙古": "MN",
}


def _norm_country_code(raw: str | None) -> str | None:
    """中文国名 → ISO 3166-1 alpha-2(2026-08-30 用户定: 供应商 locale 用国家简称
    英文字符)。已是两位大写字母原样通过; 未识别保留原值待补映射。"""
    if not raw:
        return None
    s = raw.strip()
    if len(s) == 2 and s.isalpha() and s.isupper():
        return s
    return _COUNTRY_CODE_MAP.get(s, s)


# CAS 格式校验(0902 basic分拣用): 2-7位-2位-1位数字
CAS_FORMAT_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def _dedupe_key(chemical_id: int, cas_number: str, locale: str = "zh-CN",
                source_cb_number: str | None = None) -> str:
    digest = hashlib.sha256(cas_number.strip().encode()).hexdigest()[:16]
    # locale 后缀: 语言行与主行各自独立去重(否则 en 任务会被 zh 活跃窗口吞掉)
    suffix = "" if locale == "zh-CN" else f":{locale}"
    # source_cb 后缀(0907 source grain): 仅 backfill 显式传入。同 CAS 多
    # ChemicalBook record(CB001/CB002/...) 各自独立 fetch, 不被主行活跃窗
    # 吞掉。线上路径不传 → key 与历史逐字节一致, 语义零漂移。
    if source_cb_number:
        suffix = f"{suffix}:cb{source_cb_number}" if suffix else f":cb{source_cb_number}"
    return f"cas:{chemical_id}:{digest}{suffix}"


async def enqueue_cas_job(
    db: Any,
    *,
    chemical_id: int,
    cas_number: str,
    priority: int = 50,
    locale: str = "zh-CN",
    request_context: dict[str, Any] | None = None,
    source_cb_number: str | None = None,
) -> int | None:
    """活跃窗口去重入队; 已有活跃任务时返回 None。

    locale>zh-CN 为语言行任务: 租约端从 request_context->>'locale' 寻址。
    source_cb_number (0907 source grain): backfill 专用 source record 寻址键 —
    同 CAS 多 cb_number 的 ChemicalBook source records 必须各自独立成 job,
    不得被 (chemical_id,cas) 活跃窗折叠。为 None(全部线上路径)时行为零变化:
    dedupe_key/locale/lease 语义均与旧版逐字节一致。该键只影响 source
    retrieval identity(取哪条 CB record), 不是 chemical entity identity —
    归属/合并仍全走 resolve_chemical/absorb, cb_number 不参与 can_merge。
    """
    context = dict(request_context or {})
    context["locale"] = locale
    if source_cb_number:
        context["source_cb"] = source_cb_number
    row = (await db.execute(text("""
        INSERT INTO maintenance.cas_jobs
            (chemical_id,cas_number,priority,dedupe_key,request_context)
        VALUES
            (:chemical_id,:cas_number,:priority,:dedupe_key,
             CAST(:context AS jsonb))
        ON CONFLICT (dedupe_key) WHERE status IN ('queued','leased','error')
        DO UPDATE SET
            -- 0904 P1收口: error 行复活=同请求翻态(与 PB 链 enrichment.py 同构)。
            -- 原实现只 bump priority 不翻 queued, error 行卡死后用户重试永远
            -- "正在获取"(cas_search_state 只认 queued/leased 活跃窗)。
            status=CASE WHEN maintenance.cas_jobs.status='error'
                     THEN 'queued' ELSE maintenance.cas_jobs.status END,
            priority=greatest(maintenance.cas_jobs.priority,excluded.priority),
            updated_at=now()
        RETURNING id
    """), {
        "chemical_id": chemical_id, "cas_number": cas_number.strip(),
        "priority": priority,
        "dedupe_key": _dedupe_key(
            chemical_id, cas_number, locale,
            source_cb_number=source_cb_number),
        "context": json.dumps(context, ensure_ascii=False),
    })).fetchone()
    return int(row[0]) if row else None


# ---- 搜索miss -> CB建行 (standalone cas job) -------------------------------
# 边界(2026-08-27定案): 不做建行比对(防污染既有行); 允许有/无CAS行同存;
# PubChem侧只update不insert(sync_chemical_core coalesce), 天然补全无重复。

SEARCH_MISS_PRIORITY = 80       # 用户触发 > 后台刷新(30/50)
# 2026-08-30: SEARCH_MISS_MAX_QUEUE 深度闸门拆除(用户裁定: 治理交互不治理
# 总量, 队列深度无害, 消化靠 worker 水平扩)。入队无水位上限。


# ---- CB 结构三件写入(smiles/inchikey/mol, 只补空不覆盖) ---------------------
# 依据: 详情页"物理化学性质"区 xztr 自带 SMILES/InChI/InChIKey(已入 props),
# mol 文件是 worker 同趟附带。口径: 页面三件优先, mol 派生兜底; 主表宁缺勿错
# —— RDKit 校验不过的值整字段丢弃, 绝不把脏值写进 chemicals。

def _props_field(entry: dict[str, Any], canonical_key: str) -> str | None:
    """CB props 取字段(0905 canonical 键: smiles/inchikey)。"""
    for item in entry.get("props") or []:
        if isinstance(item, dict) and item.get("key") == canonical_key:
            value = str(item.get("text") or "").strip()
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
        smiles = _validate_smiles(_props_field(entry, "smiles"))
        inchikey = _props_field(entry, "inchikey")
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
    # §3 MVP trigger 2 前置读: 本次 UPDATE 前行的 inchikey/pubchem_cid 状态,
    # 用于判定"本次真正发生 inchikey NULL → non-NULL"。
    before = (await db.execute(text("""
        SELECT inchikey,pubchem_cid FROM chemistry.chemicals WHERE id=:id
    """), {"id": chemical_id})).fetchone()
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
    # §3 MVP trigger 2(§3.1 修正: 真正 best-effort):
    # 本次真正发生 inchikey NULL → non-NULL 且 CID 仍空 → discovery 入列。
    # begin_nested savepoint 隔离 — SQL error 只回滚 savepoint,
    # CB 回补主 transaction 可继续 commit。
    if before is not None and before[0] is None and inchikey and before[1] is None:
        try:
            async with db.begin_nested():
                from .discovery import enqueue_discovery
                await enqueue_discovery(
                    db, chemical_id=chemical_id, inchikey=inchikey,
                    request_context={"origin": "cb_structure_fill"})
        except Exception:
            logger.warning("identity discovery enqueue failed chemical_id=%s",
                           chemical_id, exc_info=True)


# ---- 五态判定(数据链收口§5, DATA_CHAIN_REFACTOR_PLAN) ------
# 锚 = chemical_cb 行 (chemical_id, locale)。时间窗口配置化, 可调。

CB_LOCALES = ("zh-CN", "en", "ja", "de", "ko")  # ru已摘(0831误加未实测, ru页对爬虫全封)


# ---------------------------------------------------------------------------
# B-minimal: CB negative observations (absence semantics, 2026-09-10 用户令)
#
# 不变量:
# - chemical_cb 只承载 positive data; 本机制绝不写 last_status='not_found'
# - cas_jobs 继续只承载 queued/leased/error; 终态 complete 后 DELETE 不变
# - negative observation 无 chemical_id — absorb/rekey/merge registry 零关联
# - ERROR 永不落 negative; 只有 caslib 判定的明确 NOT_FOUND 才记录
# - key grain 不折叠: cas_locator(CAS 缺) ≠ locale_variant((cb,locale) 缺)
# ---------------------------------------------------------------------------


def negative_key(kind: str, *, cas_number: str | None = None,
                 cb_number: str | None = None,
                 locale: str | None = None) -> str | None:
    """规范化 negative key。shape 不合(缺定位键)→ None = fail closed 不记录。"""
    cas = (cas_number or "").strip() or None
    cb = (cb_number or "").strip() or None
    loc = (locale or "").strip() or None
    if kind == "cas_locator":
        return f"cbneg:cas:{cas}" if cas else None
    if kind == "locale_variant":
        # 禁止从 chemicals.cb_number convenience 字段猜 cb_number —
        # 调用方拿不到明确 source locator 时必须不记录(fail closed)。
        return f"cbneg:locale:{cb}:{loc}" if (cb and loc) else None
    return None


async def record_negative(db: Any, kind: str, *, cas_number: str | None = None,
                          cb_number: str | None = None,
                          locale: str | None = None) -> bool:
    """记录一次明确 NOT_FOUND。重复观察: 保留 first_observed_at, 只推
    observed_at。事务由调用方管理(与数据写入同事务)。返回是否落键。"""
    key = negative_key(kind, cas_number=cas_number, cb_number=cb_number,
                       locale=locale)
    if key is None:
        return False
    await db.execute(text("""
        INSERT INTO maintenance.cb_negative_observations
            (negative_key, kind, cas_number, cb_number, locale,
             first_observed_at, observed_at)
        VALUES
            (:key, :kind, :cas_number, :cb_number, :locale, now(), now())
        ON CONFLICT (negative_key) DO UPDATE SET
            observed_at = now()
    """), {"key": key, "kind": kind, "cas_number": cas_number,
           "cb_number": cb_number, "locale": locale})
    return True


async def clear_negative(db: Any, kind: str, *, cas_number: str | None = None,
                         cb_number: str | None = None,
                         locale: str | None = None) -> None:
    """上游转 positive(明确 ok)时同事务清除对应 negative。"""
    key = negative_key(kind, cas_number=cas_number, cb_number=cb_number,
                       locale=locale)
    if key is None:
        return
    await db.execute(text("""
        DELETE FROM maintenance.cb_negative_observations
        WHERE negative_key = :key
    """), {"key": key})


async def negative_is_fresh(db: Any, kind: str, *,
                            cas_number: str | None = None,
                            cb_number: str | None = None,
                            locale: str | None = None) -> bool:
    """fresh = 观察在重问窗内(cb.not_found_requery_days, 缺省 180 天)。
    过期不删行 — 判定时允许 requery(返回 False)。无观察行 = False。"""
    key = negative_key(kind, cas_number=cas_number, cb_number=cb_number,
                       locale=locale)
    if key is None:
        return False
    row = (await db.execute(text("""
        SELECT observed_at FROM maintenance.cb_negative_observations
        WHERE negative_key = :key
    """), {"key": key})).first()
    if row is None:
        return False
    requery_days, _ = await _cb_window_days(db)
    age = (await db.execute(text("SELECT now()-:ft"),
                            {"ft": row[0]})).scalar()
    return age < timedelta(days=requery_days)


async def _cb_window_days(db: Any) -> tuple[int, int]:
    """system_config: cb 命名空间两键, 缺省 180/60。"""
    try:
        rows = (await db.execute(text("""
            SELECT key, value FROM community.system_config WHERE namespace='cb'
        """))).fetchall()
        cfg = {k: v for k, v in rows}
        requery = int(cfg.get("not_found_requery_days", {}).get("days", 180))
        refresh = int(cfg.get("ok_refresh_days", {}).get("days", 60))
        return requery, refresh
    except Exception:
        return 180, 60


async def cb_decide(
    db: Any, chemical_id: int, locale: str = "zh-CN",
    *, has_cb_number: bool | None = None, cb_number: str | None = None,
) -> str:
    """四态判定(0902 剥离: not 负缓存态已亡, 收录与否由行缺省表达)。返回:
    - serve_fresh      ok 且未超刷新窗 → 直接出 entry
    - enqueue_first    无行(首问; 未知状态防御性同此)
    - enqueue_refresh  ok 超刷新窗 → 刷新(有 cb_number 直跳 CPP)
    - skip             多语言前置 cb_number 缺失, 不可寻址不入列
    """
    if locale not in CB_LOCALES:
        return "skip"
    if locale != "zh-CN" and has_cb_number is False:
        return "skip"  # 语言页靠 cb_number 寻址, 无号不可执行
    # 0907 source grain: 有 cb_number 时按 source record 行判定
    # (CB001/en 与 CB002/en 互不遮挡); 无 cb_number(普通线上路径)回落
    # 旧行为 — 兼容 legacy NULL-grain 行。
    if cb_number:
        row = (await db.execute(text("""
            SELECT last_status, fetched_at FROM chemistry.chemical_cb
            WHERE chemical_id=:id AND locale=:loc AND cb_number=:cb
        """), {"id": chemical_id, "loc": locale, "cb": cb_number})).first()
    else:
        # source grain 收口(2026-09-10): 未显式传 cb_number 时按主表
        # imprint 判定 — 与 get_externals_row 首选查询同一语义, 删除
        # 恒真 (cb_number IS NULL OR TRUE)。legacy(c.cb_number IS NULL)
        # 时唯一命中 NULL-grain 行(partial UNIQUE (chemical_id, locale)
        # WHERE cb_number IS NULL), 不再"任意一行"。
        row = (await db.execute(text("""
            SELECT x.last_status, x.fetched_at
            FROM chemistry.chemical_cb x
            JOIN chemistry.chemicals c ON c.id=x.chemical_id
            WHERE x.chemical_id=:id AND x.locale=:loc
              AND x.cb_number IS NOT DISTINCT FROM c.cb_number
        """), {"id": chemical_id, "loc": locale})).first()
    if row is None:
        return "enqueue_first"
    status, fetched_at = row[0], row[1]
    _requery_days, refresh_days = await _cb_window_days(db)
    if status == "ok":
        age = (await db.execute(text("SELECT now()-:ft"), {"ft": fetched_at})).scalar()
        return "serve_fresh" if age < timedelta(days=refresh_days) else "enqueue_refresh"
    return "enqueue_first"  # 未知状态防御性按首问(数据层已无 error/not 态)


async def cas_search_state(db: Any, cas_number: str) -> str:
    """搜索miss三态: pending(活跃任务在途或已触发入列) / miss(终态且负缓存内,
    不再入列) / new(可占行)。五态判定驱动(§5): not_found 超重问窗/ok 超刷新窗
    均入列。返回 enqueue 态时调用方须真实入列(与详情路径同逻辑)。
    """
    row = (await db.execute(text("""
        SELECT 1 FROM maintenance.cas_jobs
        WHERE cas_number=:cas AND status IN ('queued','leased','error')
        LIMIT 1
    """), {"cas": cas_number})).first()
    if row:
        return "pending"
    row = (await db.execute(text("""
        SELECT 1 FROM chemistry.chemicals
        WHERE cas_numbers @> ARRAY[:cas]
        LIMIT 1
    """), {"cas": cas_number})).first()
    if row:
        chemical_id = (await db.execute(text("""
            SELECT id FROM chemistry.chemicals
            WHERE cas_numbers @> ARRAY[:cas] LIMIT 1
        """), {"cas": cas_number})).scalar()
        decision = await cb_decide(db, int(chemical_id))
        if not decision.startswith("enqueue"):
            return "miss"
        # B-minimal: fresh cas_locator negative(明确 not_found 重问窗内)
        # → miss 零入列。不依赖 cb_decide 的 NULL-selector 表达 CAS
        # negative(既有 selector 问题本轮只记录不顺手修, 独立负缓存
        # lookup 不走那条查询)。expired → 允许现有 requery 链继续。
        if decision == "enqueue_first" and await negative_is_fresh(
                db, "cas_locator", cas_number=cas_number):
            return "miss"
        # 五态判需再问(首问外的 超窗刷新/超窗重问): 真实入列 —
        # 与详情路径 stale→enqueue 同逻辑(审计修复①, 2026-08-30)
        enqueued = await enqueue_cas_job(
            db, chemical_id=int(chemical_id), cas_number=cas_number,
            priority=40, request_context={"reason": "search_stale"},
        )
        return "pending" if enqueued else "miss"
    return "new"


async def enqueue_cas_search_fetch(
    db: Any, *, cas_number: str
) -> tuple[bool, str | None, int | None]:
    """搜索miss: 占主表行(CAS登记, 只落 cas_numbers) + 入队(带行id)。

    0905 治理机制: 定位/建行改走 api/services/identity.resolve_chemical
    (身份序位 cid > inchikey > cas, 治理五条见该文件头注释)。原裸
    NOT EXISTS 只查 cas_numbers, 撞不上既有同物 SMILES 行(inchikey 行),
    双行并存 388 例的病根即此。resolve_chemical 内含 advisory 锁, 原
    0904 锁代码随之移除。

    0907 门禁收口: 返回 (enqueued, resolve_status, chemical_id) —
    resolver 裁定结果必须穿透给调用方, 调用方禁止再按 CAS 自行重查
    任意行(旧 LIMIT 1 旁路已删, 全链路覆盖审计 BYPASS 项)。
    """
    cas = cas_number.strip()
    from .identity import resolve_chemical
    # 0906 规范: 五状态契约。AMBIGUOUS/CONFLICT 不建行不写身份字段,
    # 仅入队等待结构判据后 re-resolve; EXACT/EQUIVALENT/NEW 占行入队。
    res = await resolve_chemical(db, cas=cas)
    chemical_id, created = res.chemical_id, (res.status == "NEW")
    if chemical_id is None:
        # AMBIGUOUS(cas 多行无判据): 不猜行(规范3.3), 入队不带行,
        # worker 解析出结构判据后由回补路 re-resolve 收敛
        pass
    if created:
        await db.execute(text("""
            UPDATE chemistry.statistics SET exact_count=exact_count+1,calculated_at=now()
            WHERE metric='chemicals'
        """))
    digest = hashlib.sha256(cas.encode()).hexdigest()[:16]
    await db.execute(text("""
        INSERT INTO maintenance.cas_jobs
            (chemical_id,cas_number,priority,dedupe_key,request_context)
        VALUES
            (:chemical_id,:cas_number,:priority,:dedupe_key,
             CAST(:context AS jsonb))
        ON CONFLICT (dedupe_key) WHERE status IN ('queued','leased','error')
        DO UPDATE SET
            -- 0904 P1收口: 同上, error 复活=同请求翻态(search_miss 入口)。
            status=CASE WHEN maintenance.cas_jobs.status='error'
                     THEN 'queued' ELSE maintenance.cas_jobs.status END,
            priority=greatest(maintenance.cas_jobs.priority,excluded.priority),
            updated_at=now()
    """), {
        "chemical_id": int(chemical_id) if chemical_id is not None else None,
        "cas_number": cas,
        "priority": SEARCH_MISS_PRIORITY,
        "dedupe_key": f"cas:new:{digest}",
        "context": json.dumps(
            {"reason": "search_miss",
             **({"identity_status": res.status} if chemical_id is None else {})},
            ensure_ascii=False),
    })
    return True, res.status, (int(chemical_id) if chemical_id is not None else None)


async def sync_fetch_and_store(
    db: Any, *, chemical_id: int, cas_number: str
) -> dict[str, Any] | None:
    """同步拉取路径(详情页首访)。3s 预算, 线程池执行防阻塞事件循环。

    返回 ensure 状态字典; 网络失败/超时不落 error 行(留给 worker 重试)。
    """
    from caslib.fetch import fetch_cas
    from caslib.parse import parse_cpp_suppliers
    from caslib.parse_cpp import parse_cpp_page

    async def _fetch() -> tuple[str, dict | None, list, str | None]:
        # 判定单点在 caslib fetch 层(§5): ok/not_found/error 三态直译。
        result = await fetch_cas(cas_number, total_budget_s=SYNC_FETCH_BUDGET_S)
        if result.status == "error":
            return "error", None, [], None
        if result.status == "not_found":
            return "not_found", None, [], None
        # 0905 规范化: CPP 唯一解析源(canonical schema), CAS 页不解析内容。
        entry = parse_cpp_page(result.cpp_html) if result.cpp_html else None
        suppliers = parse_cpp_suppliers(result.cpp_html or "") if result.cpp_html else []
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
    if status == "not_found":
        # B-minimal: 同步路径明确 not_found → 记录 cas_locator negative
        # (调用方 routes 据 sync["status"] 分流, 不再误判为失败入列重抓)
        await record_negative(db, "cas_locator", cas_number=cas_number)
        await db.commit()
        await cache_delete(CACHE_KEY.format(chemical_id=chemical_id))
        return {"status": "not_found"}
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
    - fresh: ok 行直接出 (negative 由 B-minimal 独立观察表表达,
      absent 分支调用方 routes 先查 fresh cas_locator negative)
    - absent: 无 cb 行(首访) — 调用方(sync路径)决定同步拉或入队
    时间只记录不驱动(2026-08-29定): 无TTL无stale环。
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
        # 降级直查DB是设计; 但Redis故障必须留痕, 防静默打穿连接池无人知
        logger.warning("externals cache read unavailable, fallback to db", exc_info=True)

    row = await get_externals_row(db, chemical_id)
    if row is None:
        return {"state": "absent", "entry": None, "suppliers": [], "job_id": None}
    # 四态判定驱动(0902 剥离): ok 刷新窗。
    decision = await cb_decide(db, chemical_id, cb_number=row.get("cb_number"))
    if decision == "enqueue_refresh":
        # 需再问: 出当前数据但标记 stale, 调用方决定入列
        return {"state": "stale", "entry": row["entry"], "suppliers": [], "job_id": None}
    # ok 行: 终态直出。suppliers 同行取。
    suppliers = await get_suppliers(db, chemical_id)
    payload = {"state": "fresh", "entry": row["entry"], "suppliers": suppliers,
               "job_id": None}
    try:
        await redis.set(cache_key, json.dumps(payload, ensure_ascii=False,
                                              default=str), ex=CACHE_TTL_S)
    except Exception:
        # 返回无缓存是设计; 写失败留痕与读路径同口径
        logger.warning("externals cache write unavailable", exc_info=True)
    return payload


# --- Chemical Externals 共享编排(G2.4C) ----------------------------------
# HTTP/MCP 唯一 application flow; adapter 只保留 transport 解析/auth/
# 错误映射。状态机/限流位置/负缓存/入队顺序与基线 routes.chemical_externals
# 逐分支一致。


class ChemicalExternalsNotFoundError(Exception):
    """chemical_id 无对应行的 neutral 语义错误(detail 固定基线原文)。"""


async def get_chemical_externals(db: Any, chemical_id: int, *, actor_id: int | None) -> dict[str, Any]:
    """CB 扩展读: 读库+ensure 驱动(新 CAS 首访同步拉, 超期 worker 刷)。

    actor_id 仅作 externals-fetch 限流 identity policy(actor=10/min,
    anonymous-global=30/min); 限流只覆盖即将同步外呼的 absent-not-neg 分支,
    纯读路径(fresh cache/DB/negative/stale enqueue/no_cas)零消耗。
    """
    row = (await db.execute(text("""
        SELECT id, cas_numbers[1] AS cas FROM chemistry.chemicals WHERE id=:id
    """), {"id": chemical_id})).fetchone()
    if not row:
        raise ChemicalExternalsNotFoundError("化合物不存在")
    cas_number = row[1]
    if not cas_number:
        return {"chemical_id": chemical_id, "state": "no_cas",
                "entry": None, "suppliers": []}
    outcome = await ensure_externals(db, chemical_id, cas_number=cas_number)
    if outcome["state"] == "stale":
        # 六态判定需再问(超窗刷新/超窗重问/error): 出旧数据同时入列
        job_id = await enqueue_cas_job(
            db, chemical_id=chemical_id, cas_number=cas_number, priority=40,
            request_context={"reason": "stale_refresh"},
        )
        await db.commit()
        outcome = {"state": "fresh", "entry": outcome.get("entry"),
                   "suppliers": outcome.get("suppliers") or [], "job_id": job_id}
    if outcome["state"] == "absent":
        # B-minimal: fresh cas_locator negative → 明确 not_found 在重问窗内,
        # 零同步 fetch 零 enqueue(此前每次页面访问=1次同步外呼+1次入列重抓)。
        # expired → 允许现有同步验证链继续。
        if await negative_is_fresh(db, "cas_locator", cas_number=cas_number):
            return {
                "chemical_id": chemical_id,
                "state": "fresh",
                "entry": None, "suppliers": [], "job_id": None,
                "negative": True,  # 内部 decision; 不扩前端公开 state 协议
            }
        # P1修复(II): 同步外呼限流只覆盖"即将发生同步上游外呼"的分支(照抄
        # smiles-create 口径) — 同步外呼有 3s 预算且全程持有 DB 连接(pool 仅
        # 5+5), 爬虫顺序扫 HCID 可打满连接池。额度不变: 10/min 鉴权、
        # 30/min 匿名全局。不得放入口: fresh cache/fresh DB/
        # fresh negative/stale enqueue/no_cas/404 这些零外呼路径不消耗配额,
        # Redis 故障时也不该把正常读取打成 503。
        if actor_id is not None:
            await enforce("externals-fetch", str(actor_id), 10, 60)
        else:
            await enforce("externals-fetch", "anonymous-global", 30, 60)
        # 首访: 同步拉取(3s 预算); 失败入队,本响应出空
        sync = await sync_fetch_and_store(db, chemical_id=chemical_id, cas_number=cas_number)
        if sync and sync["status"] == "ok":
            outcome = await ensure_externals(db, chemical_id, cas_number=cas_number)
        elif sync and sync["status"] == "not_found":
            # 明确 not_found: negative 已在 sync 内记录 — 不 enqueue
            # (二连击修复: 一次访问最多一次上游验证, 不再排队重抓)
            outcome = {"state": "fresh", "entry": None, "suppliers": [],
                       "job_id": None}
        else:
            job_id = await enqueue_cas_job(
                db, chemical_id=chemical_id, cas_number=cas_number, priority=80,
                request_context={"reason": "sync_failed"},
            )
            await db.commit()
            outcome = {"state": "queued", "entry": None, "suppliers": [],
                       "job_id": job_id}
    return {
        "chemical_id": chemical_id,
        "state": outcome["state"],
        "entry": outcome.get("entry"),
        "suppliers": outcome.get("suppliers") or [],
    }
