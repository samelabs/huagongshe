"""caslib.fetch — ChemicalBook 页面拉取(三态)。

三态: ok / not_found / error (网络/超时/5xx)。
礼仪: 单请求 UA + 2s 页间间隔由调用方(worker)控制; 同步路径单 CAS 单次。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import aiohttp

BASE = "https://www.chemicalbook.com"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
# 浏览器指纹补齐: 真实 Chrome 的配套请求头, 与 UA 同源.
# _get() 请求级合并; session 级仅兜底 UA(共享 session 由 _get 覆盖).
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": f"{BASE}/ProductIndex.aspx",
}


@dataclass
class FetchResult:
    status: str  # "ok" | "not_found" | "error"
    cas_html: str | None = None
    supplier_html: str | None = None
    cb_number: str | None = None  # CB条目号(身份标识, 落DB不进API)
    gw_html: str | None = None  # GW国际供应商页(异步路径附带)
    error: str | None = None
    stats: dict = field(default_factory=dict)


async def _get(session: aiohttp.ClientSession, url: str, timeout_s: float) -> tuple[int | None, str]:
    try:
        async with session.get(
            url,
            headers=BROWSER_HEADERS,  # 请求级: 指纹头全集(共享 session(api/worker)统一走这套)
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            body = await resp.text(errors="replace")
            return resp.status, body
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


async def fetch_cas(
    cas: str,
    *,
    total_budget_s: float = 3.0,
    fetch_suppliers: bool = True,
    fetch_gw: bool = False,
    session: aiohttp.ClientSession | None = None,
) -> FetchResult:
    """拉取一个 CAS 的中文详情页 + (可选)供应商专用页 + (可选)国际供应商页。

    total_budget_s 覆盖全程。同步路径传 3s(GN首跳+CAS页); worker 可放宽。
    fetch_gw 仅异步路径开启(GW页需CAS页Referer, 同趟追加第三请求)。
    """
    from .parse import extract_cb_number, looks_like_not_found

    own_session = session is None
    if own_session:
        connector = aiohttp.TCPConnector(limit=4)
        session = aiohttp.ClientSession(connector=connector, headers={"User-Agent": UA})
    assert session is not None
    stats: dict = {}
    try:
        per = max(1.0, total_budget_s / (2 if fetch_suppliers else 1))
        status, body = await _get(session, f"{BASE}/CAS_{cas}.htm", per)
        stats["cas_status"] = status
        if status is None:
            return FetchResult("error", error=body, stats=stats)
        if status != 200:
            return FetchResult("error", error=f"http_{status}", stats=stats)
        if looks_like_not_found(body):
            return FetchResult("not_found", cas_html=body, stats=stats)
        if not fetch_suppliers:
            return FetchResult("ok", cas_html=body, stats=stats)
        cb = extract_cb_number(body)
        if not cb:
            # 详情页正常但无供应商链接: 条目本身 ok, 供应商空
            return FetchResult("ok", cas_html=body, cb_number=None, stats=stats)
        status2, body2 = await _get(session, f"{BASE}/ProdSupplierGNCB{cb}.htm", per)
        stats["supplier_status"] = status2
        supplier_html = body2 if status2 == 200 else None
        gw_html = None
        if fetch_gw:
            # GW(国际供应商)页: 裸拉 500, 必须带 CAS 页 Referer(实测)
            gw_status, gw_body = await _get_gw(session, cb, cas, per)
            stats["gw_status"] = gw_status
            gw_html = gw_body if gw_status == 200 else None
        return FetchResult(
            "ok", cas_html=body, supplier_html=supplier_html,
            cb_number=cb, gw_html=gw_html, stats=stats,
        )
    finally:
        if own_session:
            await session.close()


async def _get_gw(
    session: aiohttp.ClientSession, cb: str, cas: str, timeout_s: float
) -> tuple[int | None, str]:
    """GW 页专用请求: Referer 指 CAS 详情页(缺此头实测 500)。"""
    try:
        async with session.get(
            f"{BASE}/ProdSupplierGWCB{cb}.htm",
            headers={**BROWSER_HEADERS,
                     "Referer": f"{BASE}/CAS_{cas}.htm"},
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            body = await resp.text(errors="replace")
            return resp.status, body
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------- mol 文件

# CB 详情页 mol 外链存在才拉; 404/HTML错误页/非molfile 一律 None, 三态退化不报错。
_MAX_MOL_BYTES = 1_000_000  # molfile 尺寸上限(超大=异常载荷, 直接丢)


def normalize_molblock(body: str) -> str:
    """BOM/前置空白/CRLF 清洗。不改内容, 只修传输杂质。"""
    return body.lstrip("\ufeff \t\r\n").replace("\r\n", "\n")


def looks_like_molfile(body: str) -> bool:
    """真 molfile 判据: ≥4行(表头3行+计数行) + 以 'M  END' 收尾(V2000/V3000 通用)。"""
    if not body or len(body) > _MAX_MOL_BYTES:
        return False
    lines = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
    return len(lines) >= 4 and lines[-1].upper() == "M  END"


async def fetch_mol(
    session: aiohttp.ClientSession,
    mol_href: str,
    *,
    timeout_s: float = 10.0,
) -> str | None:
    """拉一个 mol 文件(站内绝对路径)。任何失败返回 None, 不抛。"""
    if not mol_href.startswith("/CAS/mol/") or not mol_href.endswith(".mol"):
        return None
    try:
        status, body = await _get(session, f"{BASE}{mol_href}", timeout_s)
        if status != 200 or not body:
            return None
        if not looks_like_molfile(body):
            return None
        return normalize_molblock(body)
    except Exception:
        return None
