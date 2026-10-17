"""ChemicalBook(CB) 数据层: 读路径选行 / 刷新判定 / 入队 / 回调写入。

现行访问规则(唯一事实, 注释与代码以此为准):
- 详情(REST/MCP full)读 get_externals_row 选行 → cb_decide 判定:
  ok 未超刷新窗(system_config cb.ok_refresh_days, 缺省 60 天)出数据;
  超窗出旧数据并 enqueue_cas_job 刷新; 无 CB 行(absent)恒不首次采集。
- 新 CAS 只经搜索 miss 占行入队(enqueue_cas_search_fetch)。
- API 进程零外呼: CB 抓取只由 worker 执行, 结果经 workapi complete
  复用本模块 upsert_externals 写入。
- negative observation 只记明确 not_found(重问窗缺省 180 天)。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from ..chemistry import valid_cas

logger = logging.getLogger(__name__)

from .name_index import ingest_from_cb_locales

CACHE_KEY = "v4:cas-ext:{chemical_id}"  # v4: 0905 CB entry schema 规范化(canonical)
MAX_ENTRY_JSON_BYTES = 2_000_000  # 双保险: workapi 载荷上限内的条目尺寸


# CB 详情读路径 locale 白名单 — 与 web/lib/i18n/locales.ts SUPPORTED_LOCALES 同源
# (API 侧唯一权威列表; 未列出的 locale 一律回落 en, 不做第二套协商)。
# v1.6.0 收口: 此前 CB_DETAIL_LOCALES 与 CB_LOCALES 两份重复定义(silent drift 风险),
# 现合并为单一权威 tuple; normalize/get_externals_row/cb_decide 全部消费同一份。
# ru 已摘(0831 误加未实测, ru 页对爬虫全封)。
CB_LOCALES = ("zh-CN", "en", "ja", "de", "ko")
CB_DETAIL_LOCALES = CB_LOCALES  # 历史别名, 保留引用面; 定义唯一
CB_DETAIL_DEFAULT_LOCALE = "en"


def normalize_cb_locale(value: str | None) -> str:
    """详情读路径 locale 归一: 未指定/非法 → en(默认), 合法原样。"""
    if value in CB_LOCALES:
        return value  # type: ignore[return-value]
    return CB_DETAIL_DEFAULT_LOCALE


async def get_externals_row(db: Any, chemical_id: int, *, locale: str = CB_DETAIL_DEFAULT_LOCALE) -> dict[str, Any] | None:
    """详情读路径(locale-aware, 2026-10 CB locale 读取):

    选择顺序(任务卡 §2):
      1. requested locale + 主表 imprint 对应的 source 行(convenience cb_number)
      2. en + 当前 cb_number
      3. requested locale + 任意 legacy 行
      4. en + 任意 legacy 行
      5. 无结果 → None
    locale=en 时 1/2 与 3/4 自然去重(同查询重复执行, 第二次空结果直接跳过)。
    未指定/非法 locale 由 normalize_cb_locale 归一为 en。
    """
    locale = normalize_cb_locale(locale)

    async def _query(loc: str, match_cb: bool) -> dict[str, Any] | None:
        if match_cb:
            row = (await db.execute(text("""
                SELECT x.chemical_id,x.cas_number,x.entry,x.last_status,x.fetched_at,x.cb_number,x.locale
                FROM chemistry.chemical_cb x
                JOIN chemistry.chemicals c ON c.id=x.chemical_id
                WHERE x.chemical_id=:chemical_id AND x.locale=:locale
                  AND x.cb_number IS NOT DISTINCT FROM c.cb_number
                LIMIT 1
            """), {"chemical_id": chemical_id, "locale": loc})).mappings().fetchone()
        else:
            # legacy fallback(步骤 3/4): 同 locale 多个非-imprint source row 时,
            # ORDER BY cb_number ASC 建立稳定 tie-break — 只消除数据库随机性,
            # 不把时间/热度解释成 source 优先级, 不参与身份裁定, 数据零修改
            # (v1.6.0: 生产 84 组 no-imprint-match 暴露面实证需要确定性)。
            row = (await db.execute(text("""
                SELECT chemical_id,cas_number,entry,last_status,fetched_at,cb_number,locale
                FROM chemistry.chemical_cb
                WHERE chemical_id=:chemical_id AND locale=:locale
                ORDER BY cb_number ASC NULLS LAST
                LIMIT 1
            """), {"chemical_id": chemical_id, "locale": loc})).mappings().fetchone()
        return dict(row) if row else None

    # en 与 requested 相同时, 同组合只查一次
    tried: set[tuple[str, bool]] = set()
    for loc, match_cb in ((locale, True), ("en", True), (locale, False), ("en", False)):
        key = (loc, match_cb)
        if key in tried:
            continue
        tried.add(key)
        row = await _query(loc, match_cb)
        if row is not None:
            return row
    return None


async def get_suppliers(db: Any, chemical_id: int) -> list[dict[str, Any]]:
    # 2026-08-31 收口: 老表迁移完成(profile 6,417/listing 449k), 双读回退桥拆除,
    # 只读两新表。旧表 chemical_supplier 已摘除。
    # I-056(v1.7.1): 对外 ref 一律为 caslib/redact.supplier_ref 不透明哈希。
    # 库内 ref 列保存原站标识形态(cb-supplier:{cbsid}), 属 DB 身份字段不出
    # 公开详情/MCP; 库内键与数据不变, 哈希在此出口计算。输出不含 cbsid 键。
    from caslib.redact import supplier_ref

    rows = (await db.execute(text("""
        SELECT p.cbsid, p.name, p.phone, p.email, p.website,
               l.purity, l.pack_price, l.remark
        FROM chemistry.chemical_supplier_listing l
        JOIN chemistry.chemical_supplier_profile p ON p.cbsid=l.cbsid
        WHERE l.chemical_id=:chemical_id
        ORDER BY p.cbsid
        LIMIT 200  -- 供应商载荷有界(CB 单品供应商实际十几到几十)
    """), {"chemical_id": chemical_id})).fetchall()
    return [
        {"ref": supplier_ref(row.cbsid), "name": row.name, "phone": row.phone,
         "email": row.email, "website": row.website, "purity": row.purity,
         "pack_price": row.pack_price, "remark": row.remark}
        for row in rows
    ]


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
    # fetched_at = 最近一次取到的时间; 刷新由读路径 cb_decide 按刷新窗
    # (cb.ok_refresh_days, 缺省 60 天)驱动入队, 见模块头注释。
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
        cb_cas = cas_number if cas_number and valid_cas(str(cas_number).strip()) else None
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
            # 2) 映射表: 按 (chemical_id, cbsid) 分行合并(HGS-CB-01)。
            # cbsid 全局唯一标识一家供应商 — 不同 CB source(CB001/CB002)的
            # 供应商天然分行共存, 后到的 source 回调不再全删全写覆盖他源;
            # 同 cbsid 重复回调按最新载荷刷新。全删全写旧语义会把 CB001 的
            # 供应商整表抹掉换成 CB002 的(展示层张冠李戴的病根)。
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
        # else: zh error 载荷 — 只刷 last_status/fetched_at, 不删任何 source
        # 的供应商行(非权威信号不得抹掉他源数据; not_found 已在上方早退)。

    # name_index 摄入在函数尾(供应商两表写入之后): 镜像内供应商名取
    # listing ⋈ profile 的落库结果, 必须在同事务更晚位置读。I-087: 任意
    # locale 行落库(含 error)都触发重建 —— 名称取全部 locale ok 行并集,
    # 某个 locale 转 error 后其名称随之移除
    # (见 name_index.ingest_from_cb_locales)。
    await ingest_from_cb_locales(db, chemical_id)


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


# CAS 校验(I-061): 往主表 cas_numbers 追加只收「格式+校验位」都合法的 CAS,
# 统一走 api/chemistry.py valid_cas(原仅格式正则已于 2026-10-14 移除)。


def _dedupe_key(chemical_id: int, cas_number: str, locale: str = "zh-CN",
                source_cb_number: str | None = None) -> str:
    digest = hashlib.sha256(cas_number.strip().encode()).hexdigest()[:16]
    # locale 后缀: 语言行与主行各自独立去重(否则 en 任务会被 zh 活跃窗口吞掉)
    suffix = "" if locale == "zh-CN" else f":{locale}"
    # source_cb 后缀(0907 source grain): 同 CAS 多 ChemicalBook record
    # (CB001/CB002/...) 各自独立 fetch, 不被主行活跃窗吞掉。传入方: 语言
    # 派发(workapi complete)、详情刷新的非 zh-CN-imprint 行。zh-CN imprint
    # 刷新与 search_stale 不传 → 无后缀 key, 同页同窗去重。
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
    source_cb_number (0907 source grain): source record 寻址键 —
    同 CAS 多 cb_number 的 ChemicalBook source records 必须各自独立成 job,
    不得被 (chemical_id,cas) 活跃窗折叠。为 None 时 dedupe_key 无后缀, lease
    回落主表 cb_number(imprint)。该键只影响 source
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
# 后台优先级档: 站内后台刷新与服务接口(数据 API)触发的采集入队共用,
# 不占用户触发档 —— 服务接口的采集压力由每凭证额度约束, 队列侧不抬档。
PRIORITY_BACKGROUND = 40
# 2026-08-30: SEARCH_MISS_MAX_QUEUE 深度闸门拆除(用户裁定: 治理交互不治理
# 总量, 队列深度无害, 消化靠 worker 水平扩)。入队无水位上限。


# ---- CB 结构三件写入(smiles/inchikey/mol, 只补空不覆盖) ---------------------
# 依据: 详情页"物理化学性质"区 xztr 自带 SMILES/InChI/InChIKey(已入 props),
# mol 文件是 worker 同趟附带。口径: 页面三件优先, mol 派生兜底; 主表宁缺勿错
# —— RDKit 校验不过的值整字段丢弃, 绝不把脏值写进 chemicals。
#
# HGS-CB-STRUCT-01/02(交叉校验): 三种结构表示互为独立来源, 全部可解析时
# 必须指向同一分子 — 以标准 InChIKey 为归一判据(page IK / mol 派生 IK /
# SMILES 派生 IK), 任何两份不一致 → 整组拒写 + 结构化 warning 留痕,
# 不允许把语义不一致的结构写进同一化合物分喂三条下游。
# SMILES 独在场时推导 IK(RDKit), 使 CB 入口与反应入口一样能进发现流程。


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


def _ik_from_smiles(smiles: str | None) -> str | None:
    """HGS-CB-STRUCT-02: 合法 SMILES → 标准 InChIKey(RDKit)。"""
    if not smiles:
        return None
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smiles)
        return Chem.MolToInchiKey(mol) if mol is not None else None
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
    """CB 三源 -> 结构字段(交叉校验版)。页面三件优先, mol 派生兜底;
    全部只补空用。

    返回 {"smiles":..., "inchikey":..., "mol":...(molblock原文)}。
    - 页面 IK 格式非法(非 14-10-1)不作结构表示, 整字段丢弃(不写脏值);
    - 三源 IK 交叉校验: 两份及以上可解析且不一致 → 整组拒写(None)+留痕;
    - smiles 校验失败时 mol 仍可独立派生(连接表本身有效);
    - 只有 SMILES 时推导 IK(HGS-CB-STRUCT-02), 进入发现流程。
    """
    from ..pubchem_core import INCHIKEY_RE
    smiles = None
    page_ik = None
    if entry:
        page_ik = _props_field(entry, "inchikey")
        if page_ik is not None and not INCHIKEY_RE.fullmatch(page_ik):
            page_ik = None  # malformed IK 不作结构表示(与 bind_unbound_ok 口径一致)
        smiles = _validate_smiles(_props_field(entry, "smiles"))
    mol_smiles, mol_ik = _derive_from_molblock(molblock)
    smiles_ik = _ik_from_smiles(smiles)

    known_iks = {k for k in (page_ik, mol_ik, smiles_ik) if k}
    if len(known_iks) > 1:
        logger.warning(
            "event=cb_structure_cross_validation_failed "
            "page_ik=%s mol_ik=%s smiles_ik=%s — representations disagree, "
            "structure write refused (HGS-CB-STRUCT-01)",
            page_ik, mol_ik, smiles_ik)
        return {"smiles": None, "inchikey": None, "mol": None}
    inchikey = next(iter(known_iks), None)
    if not smiles:
        smiles = mol_smiles
    mol = molblock if (molblock and mol_smiles) else None
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
# (locale 白名单已上移至模块头 CB_LOCALES 单一权威定义)


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
            priority=PRIORITY_BACKGROUND, request_context={"reason": "search_stale"},
        )
        return "pending" if enqueued else "miss"
    return "new"


async def enqueue_cas_search_fetch(
    db: Any, *, cas_number: str, priority: int = SEARCH_MISS_PRIORITY
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
        "priority": priority,
        "dedupe_key": f"cas:new:{digest}",
        "context": json.dumps(
            {"reason": "search_miss",
             **({"identity_status": res.status} if chemical_id is None else {})},
            ensure_ascii=False),
    })
    return True, res.status, (int(chemical_id) if chemical_id is not None else None)
