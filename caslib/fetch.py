"""caslib.fetch — ChemicalBook 页面拉取(三态)。

三态: ok / not_found / error (网络/超时/5xx)。
礼仪: 单请求 UA + 2s 页间间隔由调用方(worker)控制; 同步路径单 CAS 单次。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import aiohttp

log = logging.getLogger("caslib.fetch")

BASE = "https://www.chemicalbook.com"
# 0902 定案: 站点防爬升级为 JS 质询(_ancsi_ 令牌组, 纯HTTP客户端无法应答),
# Chrome 仿真 UA 全线 13B "SysTem ERROR！" / 42B "系统忙" 降级页(实测头/IP/TLS/
# cookie 逐项排除)。Googlebot UA 走搜索引擎白名单直通(实测 EN/CN/CAS 三类页
# 均 200 全量真页), 遂整体伪装。若上游启用反解域名验证再回退。
UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
# 爬虫UA不带浏览器配套头(Referer/Accept-Language 反而是破绽), 只保留最小集.
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class FetchResult:
    status: str  # "ok" | "not_found" | "error"
    cas_html: str | None = None
    cpp_html: str | None = None  # CPP-CN 页(ChemicalProductProperty_CN_CB{cb}.htm)
    cb_number: str | None = None  # CB条目号(身份标识, 落DB不进API)
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
    cb_number: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> FetchResult:
    """拉取一个 CAS — 两条单跳路径(2026-09-01 数据链收口, DATA_CHAIN_REFACTOR_PLAN §1)。

    有 cb_number: CPP-CN 一发定乾坤(1请求), CAS 页不再参与(它唯一目的是提号,
    已知号时无意义; 旧行为 CPP 失败落回 CAS 会把"CPP 没拿到"掩盖成完整 ok)。
    无 cb_number: CAS 详情页提号; 无号=ok 供应商空(定案), 有号再跳 CPP 拼装。

    过渡判定(§1 三行): 200+busy形态→error / 200其他→ok|not_found / 非200|超时→error。
    空壳 200(<500B) 归 not_found(CB 给 200 即可达)。
    cpp 熔断器已并入闸门阶梯, 本层不再有熔断逻辑。
    每次请求打一行 INFO 日志(status/bytes/state), 作为返回态识别的校准证据流。
    """
    from .parse import extract_cb_number, looks_like_not_found

    own_session = session is None
    if own_session:
        connector = aiohttp.TCPConnector(limit=4)
        session = aiohttp.ClientSession(connector=connector, headers={"User-Agent": UA})
    assert session is not None
    stats: dict = {}
    try:
        if cb_number:
            # 路径A: 已知 CB 号 → 直跳 CPP-CN, 不发 CAS 页
            status, body = await _get(
                session, f"{BASE}/ChemicalProductProperty_CN_CB{cb_number}.htm", total_budget_s)
            stats["cpp_status"] = status
            if status != 200:
                log.info("cpp cb=%s loc=zh status=%s bytes=%s state=error",
                         cb_number, status, len(body) if body else 0)
                return FetchResult("error", error=f"http_{status}", cb_number=cb_number,
                                   stats=stats)
            from .parse import cpp_page_state
            state = cpp_page_state(body)
            log.info("cpp cb=%s loc=zh status=200 bytes=%s state=%s",
                     cb_number, len(body), state)
            if state == "error":
                # 小页=系统错误/质询降级(0902): 留 error 行重试, 不落数据层。
                return FetchResult("error", error="cpp_error_page", cb_number=cb_number,
                                   stats=stats)
            return FetchResult("ok", cpp_html=body, cb_number=cb_number, stats=stats)
        # 路径B: 无号 → CAS 详情页
        status, body = await _get(session, f"{BASE}/CAS_{cas}.htm", total_budget_s)
        stats["cas_status"] = status
        if status is None or status != 200:
            log.info("cas %s status=%s state=error", cas, status)
            return FetchResult("error", error=body if status is None else f"http_{status}",
                               stats=stats)
        if looks_like_not_found(body):
            log.info("cas %s status=200 bytes=%s state=not_found", cas, len(body))
            return FetchResult("not_found", cas_html=body, stats=stats)
        cb = extract_cb_number(body)
        if not cb:
            # 详情页正常但无任何自身CB链接: 条目本身 ok, 供应商空(定案保持)。
            log.info("cas %s status=200 bytes=%s state=ok(no_cb)", cas, len(body))
            return FetchResult("ok", cas_html=body, cb_number=None, stats=stats)
        cpp_html = None
        status2, body2 = await _get(
            session, f"{BASE}/ChemicalProductProperty_CN_CB{cb}.htm", total_budget_s)
        stats["cpp_status"] = status2
        if status2 == 200:
            from .parse import cpp_page_state
            state2 = cpp_page_state(body2)
            stats["cpp_state"] = state2
            log.info("cpp cb=%s loc=zh status=200 bytes=%s state=%s",
                     cb, len(body2), state2)
            if state2 == "ok":
                cpp_html = body2
            # error(小页): CPP 段缺失, CAS 页 entry 仍完整 → ok 不降级
        else:
            log.info("cpp cb=%s loc=zh status=%s state=error", cb, status2)
        return FetchResult(
            "ok", cas_html=body, cpp_html=cpp_html,
            cb_number=cb, stats=stats,
        )
    finally:
        if own_session:
            await session.close()


# ---------------------------------------------------------------- 会话热身

async def warm_session(session: aiohttp.ClientSession) -> int:
    """首页一换 cookie(ASP.NET_SessionId + _ancsi_ 防爬令牌), 返回 cookie 数。

    浏览器式会话: 热身后进程内所有请求自动携带。任何失败返回 -1, 调用方降级继续。
    """
    try:
        status, _ = await _get(session, f"{BASE}/", 15)
        if status != 200:
            return -1
        return len(session.cookie_jar)
    except Exception:
        return -1


# ---------------------------------------------------------------- CPP 语言页
# (2026-09-01 收口: CPP 熔断器删除, 上游保护统一由 lease 闸门阶梯承担。)

_CPP_LANG_SUFFIX = {"en": "_EN", "ja": "_JP", "de": "_DE", "ko": "_KR"}


async def fetch_cpp_locale(
    session: aiohttp.ClientSession,
    cb_number: str,
    locale: str,
    *,
    timeout_s: float = 20.0,
) -> tuple[str, str | None]:
    """拉 CPP 语言变体页(ChemicalProductProperty_{L}_CB{cb}.htm), 返回 (state, html)。

    locale ∈ en/ja/de/ko/ru(zh-CN 走主链 fetch_cas, 不经此函数)。
    过渡判定对齐主链(§1 三行):
      - "ok":       200 且页面可判定 — 有效内容返回 html, 无变体返回 (ok, None)
      - "busy":     200 但"系统忙"限流页 → error 性质(调用方按 error 处理)
      - "error":    网络/超时/非200/未知 locale — 拿不到有效回应
    空壳 200(<500B) 归 not_found(可达, 无有效信息)。
    不抛异常。
    """
    suffix = _CPP_LANG_SUFFIX.get(locale)
    if not suffix:
        return "error", None
    try:
        status, body = await _get(
            session, f"{BASE}/ChemicalProductProperty{suffix}_CB{cb_number}.htm",
            timeout_s,
        )
    except Exception:
        log.info("cpp cb=%s loc=%s status=none state=error", cb_number, locale)
        return "error", None
    if status != 200 or not body:
        log.info("cpp cb=%s loc=%s status=%s state=error", cb_number, locale, status)
        return "error", None
    from .parse import cpp_page_state

    state = cpp_page_state(body)
    log.info("cpp cb=%s loc=%s status=200 bytes=%s state=%s",
             cb_number, locale, len(body), state)
    if state == "error":
        # 小页=系统错误/质询降级(0902): error 性质走重试, 不落 not_found。
        return "error", None
    return "ok", body


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
    # 0902: 不做路径白名单 — 上下文锚已防误配, 此处只要求站内绝对路径+.mol
    import re as _re
    if not _re.fullmatch(r"/[^?]+\.mol", mol_href):
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
