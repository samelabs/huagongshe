"""PubChem PUG View client: 整记录化(0901)后的唯一活路径 = whole_record + request_json."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import aiohttp

PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
STATUS_RE = re.compile(r"(?:Request Count|Request Time|Service) status: ([A-Za-z]+)", re.I)
STATUS_RANK = {"green": 0, "idle": 0, "yellow": 1, "moderate": 1, "red": 2, "busy": 2, "black": 3, "overloaded": 3}


class PubChemError(RuntimeError):
    """PB 错误形态(数据链收口§2): 全部 = 没拿到有效回应, worker 一律报 error。"""
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


class PubChemRateController:
    """Process-local adaptive rate control for this worker's PubChem traffic."""

    def __init__(self, requests_per_second: float = 4.0):
        if not 0 < requests_per_second <= 5:
            raise ValueError("PubChem requests_per_second must be between 0 and 5")
        self.base_spacing = 1.0 / requests_per_second
        self.spacing = self.base_spacing
        self.next_at = 0.0
        self.pause_until = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()
        async with self.lock:
            now = loop.time()
            reserved = max(now, self.next_at, self.pause_until)
            self.next_at = reserved + self.spacing
            wait_seconds = max(0.0, reserved - now)
        if wait_seconds:
            await asyncio.sleep(wait_seconds)

    async def feedback(self, status: str, http_status: int) -> None:
        loop = asyncio.get_running_loop()
        async with self.lock:
            # 8-29 规范: 头缺失(unknown) ≠ green — 不收缩间距, 维持现值。
            # 封禁页恰好无 throttle 头, 最该保守的时刻不能回满速。
            if status == "green":
                self.spacing = max(self.base_spacing, self.spacing * 0.8)
            elif status == "unknown":
                pass
            elif status == "yellow":
                self.spacing = max(self.spacing, 0.5)
            elif status == "red":
                self.spacing = max(self.spacing, 1.0)
            else:
                self.spacing = max(self.spacing, 2.0)
            if status == "black" or http_status == 503:
                self.pause_until = max(self.pause_until, loop.time() + 60.0)


def throttle_status(header: str | None) -> str:
    # 8-29 规范: 头缺失/解析不出任何状态 = unknown, 调用方按"不收缩"处理。
    if not header:
        return "unknown"
    states = [value.lower() for value in STATUS_RE.findall(header)]
    if not states:
        return "unknown"
    worst = max((STATUS_RANK.get(value, 0) for value in states), default=0)
    return ("green", "yellow", "red", "black")[worst]


class PubChemClient:
    # (0901 整记录化) PB 唯一数据请求: PUG View 整包 + gzip。
    # resolve/properties/synonyms/view(逐 heading) 全部退役。

    async def whole_record(self, cid: int) -> dict[str, Any] | None:
        url = f"{PUG_VIEW}/data/compound/{cid}/JSON"
        payload = await self.request_json("GET", url, gzip_ok=True)
        if not payload:
            return None
        from .whole_record import parse_whole_record
        return parse_whole_record(payload)
    def __init__(self, session: aiohttp.ClientSession, rate: PubChemRateController):
        self.session = session
        self.rate = rate

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        gzip_ok: bool = False,
    ) -> dict[str, Any] | None:
        # 8-29 规范: 单趟制 — 无内部重试循环。任何失败形态一次定型:
        # miss(404)=None / 拒绝(403|302跳转|封禁页|4xx)=refused 终态 /
        # 上游5xx|网络错=终态。lease 过期回队是任务级唯一合法重试路径。
        # gzip_ok(0901): 整包请求带 Accept-Encoding (实测 1.8MB→185KB)。
        await self.rate.acquire()
        try:
            headers = {
                "User-Agent": "Huagongshe-AIchem-Chemical-Update/1.1 "
                "(https://huagongshe.com; mail@huagongshe.com; 3 req/s)"
            }
            if gzip_ok:
                headers["Accept-Encoding"] = "gzip"
            async with self.session.request(
                method,
                url,
                data=data,
                params=params,
                timeout=aiohttp.ClientTimeout(total=28),
                # NCBI 政策: 程序访问应自标识并留联系方式 — 这比伪装更抗封.
                # 仅 PB 链; CB 链(caslib/fetch.py)是浏览器头, 性质不同, 不动.
                # 速率说明: 3 req/s 持续采集, 详见站点.
                headers=headers,
                allow_redirects=False,
            ) as response:
                raw = await response.read()
                # 302 → misuse/abuse 页 = NCBI 封禁形态之一(2026-08-28 实测
                # 解封探测口径), 不跟随重定向, 直接按拒绝终态。
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location", "")
                    raise PubChemError(
                        "pubchem_refused",
                        f"PubChem redirect {response.status} -> {location[:200]}",
                    )
                status = throttle_status(response.headers.get("X-Throttling-Control"))
                await self.rate.feedback(status, response.status)
                if len(raw) > 8 * 1024 * 1024:
                    raise PubChemError("response_too_large", "PubChem response exceeded 8 MiB")
                if response.status == 404:
                    return None
                if response.status == 503 or response.status >= 500:
                    raise PubChemError("pubchem_unavailable", f"PubChem HTTP {response.status}")
                if response.status >= 400:
                    detail = raw.decode("utf-8", "replace")[:500]
                    raise PubChemError("pubchem_refused", f"PubChem HTTP {response.status}: {detail}")
                if "json" not in response.headers.get("Content-Type", "").lower():
                    raw_text = raw.decode("utf-8", "replace")
                    # NCBI 封禁页(200+text/html+"Access Denied"): error 报告
                    # 进闸门阶梯(连续错→静默), 不再单独置 redis 熔断 key。
                    if "Access Denied" in raw_text[:2000] and "ncbi" in raw_text.lower():
                        raise PubChemError("pubchem_refused", "PubChem ban page (Access Denied)")
                    raise PubChemError("unexpected_content_type", "PubChem did not return JSON")
                return json.loads(raw)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise PubChemError("network_error", str(exc)) from exc


