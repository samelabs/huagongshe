"""PubChem worker using the authenticated maintenance API as its only writer."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import random
import secrets
import time
from typing import Any

import aiohttp

from .pubchem import PubChemClient, PubChemError, PubChemRateController

log = logging.getLogger("huagongshe-worker")


class WorkApiClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, worker_id: str, token: str):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.worker_id = worker_id
        self.token = token

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(body) > 9_500_000:
            raise RuntimeError("workapi payload exceeds the 9.5 MB worker safety limit")
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        body_hash = hashlib.sha256(body).hexdigest()
        signed = "\n".join((timestamp, nonce, "POST", path, body_hash)).encode()
        signature = hmac.new(self.token.encode(), signed, hashlib.sha256).hexdigest()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Worker-Id": self.worker_id,
            "X-Work-Timestamp": timestamp,
            "X-Work-Nonce": nonce,
            "X-Work-Signature": signature,
        }
        async with self.session.post(
            self.base_url + path,
            data=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            raw = await response.read()
            if response.status >= 400:
                raise RuntimeError(f"workapi HTTP {response.status}: {raw.decode('utf-8','replace')[:500]}")
            return json.loads(raw)


async def heartbeat(client: WorkApiClient, job: dict[str, Any], stop: asyncio.Event) -> None:
    """CB 租约心跳(PB 已删: 整包单请求 lease_seconds=180 足够, 无续租场景)。"""
    interval = max(20, int(job.get("lease_seconds", 180)) // 3)
    path = "/workapi/v1/cas/jobs/heartbeat"
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            try:
                await client.post(
                    path,
                    {"job_id": job["job_id"], "lease_token": job["lease_token"]},
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A transient heartbeat failure must not stop lease renewal for
                # the remainder of a long-running PubChem request.
                log.warning("heartbeat failed for job=%s: %s", job["job_id"], exc)


async def process_job(
    session: aiohttp.ClientSession,
    workapi: WorkApiClient,
    rate: PubChemRateController,
    job: dict[str, Any],
) -> None:
    """PB 任务(0901 整记录化终版): PUG View 整包一个请求 → 解析 → complete。

    有数据 → complete(payload) → 服务端拉到就 update 全字段覆盖;
    整包无有效内容 → error(pubchem_empty): 留痕不沉底, 不计连击(非通道信号);
    网络不通(超时/5xx/403/封禁页) → error(事实码) → 连击+1, 闸门在 lease 派发口。
    """
    try:
        pubchem = PubChemClient(session, rate)
        payload = await pubchem.whole_record(int(job["cid"]))
        if payload is None:
            await workapi.post(
                "/workapi/v1/jobs/error",
                {
                    "job_id": job["job_id"],
                    "lease_token": job["lease_token"],
                    "error_code": "pubchem_empty",
                    "error_detail": "pug_view returned no parseable record",
                },
            )
            log.info("PubChem job=%s empty (no parseable record)", job["job_id"])
            return
        await workapi.post(
            "/workapi/v1/jobs/complete",
            {"job_id": job["job_id"], "lease_token": job["lease_token"],
             "result": {"payload": payload}},
        )
        log.info("completed job=%s cid=%s", job["job_id"], job["cid"])
    except PubChemError as exc:
        # 网络/拒服/封禁页 = 没拿到有效回应 → error 报事实, 判定全在闸门。
        await workapi.post(
            "/workapi/v1/jobs/error",
            {
                "job_id": job["job_id"],
                "lease_token": job["lease_token"],
                "error_code": exc.code,
                "error_detail": str(exc)[:2000],
            },
        )
        log.info("PubChem job=%s error: %s", job["job_id"], exc)
    except Exception as exc:
        try:
            await workapi.post(
                "/workapi/v1/jobs/error",
                {
                    "job_id": job["job_id"],
                    "lease_token": job["lease_token"],
                    "error_code": "worker_error",
                    "error_detail": str(exc)[:2000],
                },
            )
        except Exception:
            log.exception("could not report error for job=%s", job["job_id"])
        log.exception("worker job=%s errored", job["job_id"])


async def process_cas_job(
    session: aiohttp.ClientSession,
    workapi: WorkApiClient,
    job: dict[str, Any],
) -> None:
    """cas_jobs 处理(数据链收口§1/§3): fetch 三态直译, 两出口。

    complete(ok|not_found) — 写数据层, 出表;
    error — 不写数据层, job 留 error 行进阶梯(判定在 lease 派发口)。
    判定单点在 caslib(fetch 层), worker 不加工: 无空壳改判、无 Governor、
    无熔断预检、无 retryable/retry_after。判定映射:
      fetch ok        → complete(ok)   (entry 按页解析, 无号=供应商空)
      fetch not_found → complete(not_found) (含空壳200, 过渡判定§1)
      fetch error     → error          (非200/超时/busy)
    页间 2s 礼仪间隔(finally); 抓取预算放宽(后台路径非用户等待路径)。
    """
    from caslib.fetch import fetch_cas, fetch_cpp_locale, fetch_mol
    from caslib.parse import (
        extract_mol_href, parse_cpp_entry, parse_cpp_entry_en,
        parse_cpp_suppliers, parse_entry, parse_suppliers,
    )

    locale = job.get("locale") or "zh-CN"
    stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(heartbeat(workapi, job, stop))
    try:
        payload: dict[str, Any]
        if locale == "zh-CN":
            result = await fetch_cas(
                job["cas_number"], total_budget_s=20.0, session=session,
                cb_number=job.get("cb_number"),
            )
            if result.status == "error":
                await workapi.post(
                    "/workapi/v1/cas/jobs/error",
                    {
                        "job_id": job["job_id"],
                        "lease_token": job["lease_token"],
                        "error_code": f"cb_{result.error or 'error'}",
                        "error_detail": str(result.error or "")[:2000],
                    },
                )
                log.info("cas job=%s error zh-CN (%s)", job["job_id"], result.error)
                return
            if result.status == "not_found":
                payload = {"status": "not_found", "entry": None, "suppliers": []}
            else:
                # ok: entry 按 CPP 优先、CAS 页兜底; 无号=供应商空(定案)。
                entry = (
                    parse_cpp_entry(result.cpp_html) if result.cpp_html else None
                ) or (parse_entry(result.cas_html) if result.cas_html else None)
                if entry is None:
                    # fetch 判 ok 但双页解析皆空 = 无有效信息(§1: 空壳归 not_found)
                    payload = {"status": "not_found", "entry": None, "suppliers": []}
                else:
                    suppliers = (
                        parse_cpp_suppliers(result.cpp_html) if result.cpp_html else []
                    )
                    if not suppliers and result.cas_html:
                        suppliers = parse_suppliers(result.cas_html, None)
                    payload = {"status": "ok", "entry": entry, "suppliers": suppliers}
                    # CB条目号: 身份标识随载荷回传(落主表, 不进API输出)
                    if result.cb_number:
                        payload["cb_number"] = result.cb_number
                    # mol 文件: 详情页有外链才拉(无外链=零请求); 失败退化 None。
                    # 占位行靠这个回填结构三件, 否则smiles展示无图。
                    mol_href = extract_mol_href(result.cas_html or "")
                    if mol_href:
                        payload["mol"] = await fetch_mol(session, mol_href)
        else:
            # 语言行: cb_number 直拉 CPP 语言页, 只写 entry。
            cpp_state, cpp_html = await fetch_cpp_locale(session, job.get("cb_number"), locale)
            if cpp_state in ("busy", "error"):
                await workapi.post(
                    "/workapi/v1/cas/jobs/error",
                    {
                        "job_id": job["job_id"],
                        "lease_token": job["lease_token"],
                        "error_code": (
                            "cpp_busy" if cpp_state == "busy" else "cpp_fetch_error"
                        ),
                        "error_detail": f"locale={locale} {cpp_state}",
                    },
                )
                log.info("cas job=%s error %s (cpp %s)", job["job_id"], locale, cpp_state)
                return
            entry = parse_cpp_entry_en(cpp_html) if cpp_html else None
            if entry is None:
                # 判定成功的"无变体"(含空壳200): not_found 负缓存(8-29 定论,
                # 大量条目无语言变体, retry 只产无效请求喂上游风控画像)。
                payload = {"status": "not_found", "entry": None, "suppliers": [],
                           "locale": locale}
            else:
                payload = {"status": "ok", "entry": entry, "suppliers": [],
                           "locale": locale}
        await workapi.post(
            "/workapi/v1/cas/jobs/complete",
            {"job_id": job["job_id"], "lease_token": job["lease_token"], "result": payload},
        )
        log.info("cas job=%s %s %s", job["job_id"], payload["status"], locale)
    except Exception as exc:
        # 兜底=没拿到(§3), 不再打死成终态。
        try:
            await workapi.post(
                "/workapi/v1/cas/jobs/error",
                {
                    "job_id": job["job_id"],
                    "lease_token": job["lease_token"],
                    "error_code": "cas_fetch_error",
                    "error_detail": str(exc)[:2000],
                },
            )
        except Exception:
            log.exception("could not report cas error for job=%s", job["job_id"])
        log.warning("cas job=%s errored: %s", job["job_id"], exc)
    finally:
        stop.set()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        await asyncio.sleep(2)  # 抓取礼仪间隔


async def run() -> None:
    base_url = os.environ["HGS_WORKAPI_URL"]
    worker_id = os.environ["HGS_WORKER_ID"]
    token = os.environ["HGS_WORKER_TOKEN"]
    concurrency = min(max(int(os.environ.get("HGS_WORKER_CONCURRENCY", "2")), 1), 8)
    requests_per_second = float(os.environ.get("HGS_PUBCHEM_REQUESTS_PER_SECOND", "4"))
    connector = aiohttp.TCPConnector(limit=concurrency + 4, ttl_dns_cache=300)
    # PB 专用出口(2026-08-29): 本机直连 IP 被 PubChem 封禁(abuse 302),
    # 经本机 socks(127.0.0.1) 走远端出口, 仅 PubChem 流量使用。
    # CB/工作API等其余流量仍走直连 session, 两链出口互不影响。
    pb_proxy_url = os.environ.get("HGS_PUBCHEM_PROXY", "")
    if pb_proxy_url:
        from aiohttp_socks import ProxyConnector

        pb_connector = ProxyConnector.from_url(pb_proxy_url, ttl_dns_cache=300)
    else:
        pb_connector = None
    async with aiohttp.ClientSession(connector=connector) as session:
        # PB 代理 session 与直连 session 并存: 代理缺席时退化为直连(变量留空)。
        pb_session_ctx = (
            aiohttp.ClientSession(connector=pb_connector)
            if pb_connector
            else contextlib.nullcontext(session)
        )
        async with pb_session_ctx as pb_session:
            # 会话热身(2026-08-28): 首页一换取 ASP.NET_SessionId + _ancsi_ 防爬令牌,
            # 之后整进程自动携带(浏览器式会话)。失败不阻塞启动 — cookie 缺席仅降级不致命。
            try:
                from caslib.fetch import warm_session

                got = await warm_session(session)
                log.info("session warmup: %s cookies", got)
            except Exception as exc:
                log.warning("session warmup failed (continuing): %s", exc)
            workapi = WorkApiClient(session, base_url, worker_id, token)
            rate = PubChemRateController(requests_per_second)
            log.info(
                "worker started id=%s concurrency=%s pb_proxy=%s",
                worker_id, concurrency, pb_proxy_url or "direct",
            )
            idle_seconds = 2.0
            # cas 空闲退避上限收紧: 30s->10s。lease 是本地 workapi 轮询(不打外部源),
            # 换搜索miss用户重搜等待上限 40s->~20s(2026-08-28 体感收口)
            cas_idle_seconds = 2.0
            cas_idle_cap = 10.0
            cb_proxy_sessions: dict[str, aiohttp.ClientSession] = {}
            while True:
                try:
                    # 双队列: pubchem 优先轮询, cas 每轮附带认领(单并发,礼仪串行)。
                    # scopes 门控对两条链对称: 不含 pubchem 就跳过 PB 轮询(PB 封禁期
                    # 单停 PB 不伤 CAS, 8-28 事故后补的对称性, 原先只门控 cas 侧)。
                    _scopes = [
                        s.strip() for s in os.environ.get("HGS_WORKER_SCOPES", "pubchem,cas").split(",")
                    ]
                    jobs: list = []
                    if "pubchem" in _scopes:
                        leased = await workapi.post(
                            "/workapi/v1/jobs/lease",
                            {"max_jobs": concurrency, "capabilities": ["pubchem"]},
                        )
                        jobs = leased.get("jobs") or []
                    cas_coros = []
                    # CB 双入口并行(2026-08-30): 直连链恒在, HGS_CB_PROXY 设置时
                    # 加一条独立代理 session 链(VLESS 出口 IP), 两条链各自 lease
                    # 各自单发串行, 对 CB 呈两个独立出口各一恒定节奏。
                    cb_proxy_url = os.environ.get("HGS_CB_PROXY", "")
                    if "cas" in _scopes:
                        cas_leased = await workapi.post(
                            "/workapi/v1/cas/jobs/lease",
                            {"max_jobs": 1, "capabilities": ["cas"]},
                        )
                        cas_jobs = cas_leased.get("jobs") or []
                        cas_coros = [process_cas_job(session, workapi, job) for job in cas_jobs]
                        if cas_jobs:
                            cas_idle_seconds = 2.0
                        else:
                            cas_idle_seconds = min(cas_idle_cap, cas_idle_seconds * 1.5)
                        if cb_proxy_url:
                            cb_leased = await workapi.post(
                                "/workapi/v1/cas/jobs/lease",
                                {"max_jobs": 1, "capabilities": ["cas"]},
                            )
                            cb_jobs = cb_leased.get("jobs") or []
                            if cb_proxy_url not in cb_proxy_sessions:
                                cb_conn = ProxyConnector.from_url(cb_proxy_url, ttl_dns_cache=300)
                                cb_proxy_sessions[cb_proxy_url] = aiohttp.ClientSession(connector=cb_conn)
                            cas_coros += [process_cas_job(cb_proxy_sessions[cb_proxy_url], workapi, job) for job in cb_jobs]
                    if not jobs and not cas_coros:
                        # retry_after_seconds 承载闸门静默剩余(lease 返回 gate_wait+1),
                        # worker 照单退避 — 静默期零空转(§4)。
                        pb_wait = float(leased.get("retry_after_seconds", 5)) if "pubchem" in _scopes else 0
                        cas_wait = float(cas_leased.get("retry_after_seconds", 5)) if "cas" in _scopes else 0
                        requested_wait = max(pb_wait, cas_wait, 2)
                        idle_seconds = min(1800.0, max(requested_wait, idle_seconds * 1.5))
                        await asyncio.sleep(idle_seconds + random.random())
                        continue
                    idle_seconds = 2.0
                    await asyncio.gather(
                        *(process_job(pb_session, workapi, rate, job) for job in jobs),
                        *cas_coros,
                    )
                except Exception:
                    log.exception("worker cycle failed")
                    await asyncio.sleep(5)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
