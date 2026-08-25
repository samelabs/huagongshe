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


@dataclass
class FetchResult:
    status: str  # "ok" | "not_found" | "error"
    cas_html: str | None = None
    supplier_html: str | None = None
    error: str | None = None
    stats: dict = field(default_factory=dict)


async def _get(session: aiohttp.ClientSession, url: str, timeout_s: float) -> tuple[int | None, str]:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_s)) as resp:
            body = await resp.text(errors="replace")
            return resp.status, body
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


async def fetch_cas(
    cas: str,
    *,
    total_budget_s: float = 3.0,
    fetch_suppliers: bool = True,
    session: aiohttp.ClientSession | None = None,
) -> FetchResult:
    """拉取一个 CAS 的中文详情页 + (可选)供应商专用页。

    total_budget_s 覆盖全程(两次请求)。同步路径传 3s; worker 可放宽。
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
            return FetchResult("ok", cas_html=body, stats=stats)
        status2, body2 = await _get(session, f"{BASE}/ProdSupplierGNCB{cb}.htm", per)
        stats["supplier_status"] = status2
        supplier_html = body2 if status2 == 200 else None
        return FetchResult("ok", cas_html=body, supplier_html=supplier_html, stats=stats)
    finally:
        if own_session:
            await session.close()
