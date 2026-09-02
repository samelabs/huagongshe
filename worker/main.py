"""PubChem worker using the authenticated maintenance API as its only writer."""

from __future__ import annotations

import asyncio
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
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                          default=str).encode()
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
                    # 0902: mol 双源 — CAS 页 span 形态 or CPP 页 dt/dd 形态
                    # (路径A cas_html=None, mol 只在 CPP 页上, 原先结构性拿不到)
                    mol_href = extract_mol_href(result.cas_html or "") or \
                        extract_mol_href(result.cpp_html or "")
                    if mol_href:
                        payload["mol"] = await fetch_mol(session, mol_href)
        else:
            # 语言行: cb_number 直拉 CPP 语言页, 只写 entry。
            cpp_state, cpp_html = await fetch_cpp_locale(session, job.get("cb_number"), locale)
            if cpp_state == "error":
                await workapi.post(
                    "/workapi/v1/cas/jobs/error",
                    {
                        "job_id": job["job_id"],
                        "lease_token": job["lease_token"],
                        "error_code": "cpp_error_page",
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


async def _pb_loop(
    workapi: WorkApiClient,
    pb_session: aiohttp.ClientSession | None,
    rate: PubChemRateController,
    concurrency: int,
) -> None:
    """PB 循环(独立退避/异常, 不与其他链互等)。

    pb_session 为 None = PB 代理缺席(0902 守卫): 本机 IP 已被 NCBI 封禁,
    直连=打进 abuse 页持续加害, 宁可 idle 等人修 env 重启。恢复途径只有
    restart(环境变量启动时读一次, 不做运行时热读)。
    """
    if pb_session is None:
        log.error("pb proxy missing (HGS_PUBCHEM_PROXY unset) — pubchem loop idle")
        return
    idle = 2.0
    while True:
        try:
            leased = await workapi.post(
                "/workapi/v1/jobs/lease",
                {"max_jobs": concurrency, "capabilities": ["pubchem"]},
            )
            jobs = leased.get("jobs") or []
            if not jobs:
                wait = float(leased.get("retry_after_seconds", 5))
                idle = min(1800.0, max(wait, idle * 1.5))
                await asyncio.sleep(idle + random.random())
                continue
            idle = 2.0
            await asyncio.gather(
                *(process_job(pb_session, workapi, rate, job) for job in jobs)
            )
        except Exception:
            log.exception("pb loop cycle failed")
            await asyncio.sleep(5)


async def _cb_loop(
    workapi: WorkApiClient,
    session: aiohttp.ClientSession,
) -> None:
    """CB 单链循环(直连链与代理链各起一个实例, 各自独立退避)。

    每轮 lease 一条 → 单发处理(内部含 2s 礼仪) → 下一轮。对上游保持
    各出口恒定串行节奏(与原主循环形态一致)。
    """
    idle = 2.0
    while True:
        try:
            leased = await workapi.post(
                "/workapi/v1/cas/jobs/lease",
                {"max_jobs": 1, "capabilities": ["cas"]},
            )
            jobs = leased.get("jobs") or []
            if not jobs:
                idle = min(10.0, idle * 1.5)
                await asyncio.sleep(idle + random.random())
                continue
            idle = 2.0
            for job in jobs:
                await process_cas_job(session, workapi, job)
        except Exception:
            log.exception("cb loop cycle failed")
            await asyncio.sleep(5)


async def run() -> None:
    base_url = os.environ["HGS_WORKAPI_URL"]
    worker_id = os.environ["HGS_WORKER_ID"]
    token = os.environ["HGS_WORKER_TOKEN"]
    concurrency = min(max(int(os.environ.get("HGS_WORKER_CONCURRENCY", "2")), 1), 8)
    requests_per_second = float(os.environ.get("HGS_PUBCHEM_REQUESTS_PER_SECOND", "4"))
    scopes = [
        s.strip() for s in os.environ.get("HGS_WORKER_SCOPES", "pubchem,cas").split(",")
        if s.strip()
    ]
    # 环境变量只在启动时读一次(0902): 运行时热读属画蛇添足, 变更走 restart+save。
    pb_proxy_url = os.environ.get("HGS_PUBCHEM_PROXY", "")
    cb_proxy_url = os.environ.get("HGS_CB_PROXY", "")

    # 代理 connector 显式创建(0902 GPT审计): 两出口各自导入, 不共享 PB 分支的
    # import — PB 代理缺席 + CB 代理在 的组合不得 NameError。
    from aiohttp_socks import ProxyConnector

    connector = aiohttp.TCPConnector(limit=concurrency + 4, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        # PB 专用出口(2026-08-29): 本机直连 IP 被 PubChem 封禁(abuse 302)。
        # 0902 守卫: 代理缺席不再退化为直连(nullcontext 删除), pb_session=None
        # → pb_loop 打 ERROR 后 idle。
        pb_session: aiohttp.ClientSession | None = None
        if "pubchem" in scopes:
            if pb_proxy_url:
                pb_session = aiohttp.ClientSession(
                    connector=ProxyConnector.from_url(pb_proxy_url, ttl_dns_cache=300)
                )
            else:
                log.error("HGS_PUBCHEM_PROXY unset — pubchem disabled (local IP banned)")
        # CB 代理链: 有 HGS_CB_PROXY 才创建(缺席=只有直连链, 现状语义)。
        cb_proxy_session: aiohttp.ClientSession | None = None
        if "cas" in scopes and cb_proxy_url:
            cb_proxy_session = aiohttp.ClientSession(
                connector=ProxyConnector.from_url(cb_proxy_url, ttl_dns_cache=300)
            )
        try:
            # 会话热身(2026-08-28): 首页一换取防爬令牌, 整进程直连链自动携带。
            try:
                from caslib.fetch import warm_session

                got = await warm_session(session)
                log.info("session warmup: %s cookies", got)
            except Exception as exc:
                log.warning("session warmup failed (continuing): %s", exc)
            workapi = WorkApiClient(session, base_url, worker_id, token)
            rate = PubChemRateController(requests_per_second)
            log.info(
                "worker started id=%s concurrency=%s pb_proxy=%s cb_proxy=%s scopes=%s",
                worker_id, concurrency, pb_proxy_url or "none(idle)",
                cb_proxy_url or "none", ",".join(scopes),
            )
            loops = []
            if "pubchem" in scopes:
                loops.append(_pb_loop(workapi, pb_session, rate, concurrency))
            if "cas" in scopes:
                loops.append(_cb_loop(workapi, session))
                if cb_proxy_session is not None:
                    loops.append(_cb_loop(workapi, cb_proxy_session))
            if not loops:
                log.error("no scopes enabled (HGS_WORKER_SCOPES=%r) — exiting", scopes)
                return
            await asyncio.gather(*loops)
        finally:
            if pb_session is not None:
                await pb_session.close()
            if cb_proxy_session is not None:
                await cb_proxy_session.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
