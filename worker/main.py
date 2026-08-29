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
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .pubchem import PubChemClient, PubChemError, PubChemRateController
from .chemistry import select_verified_cid

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


async def heartbeat(client: WorkApiClient, job: dict[str, Any], stop: asyncio.Event, *, cas: bool = False) -> None:
    interval = max(20, int(job.get("lease_seconds", 180)) // 3)
    path = "/workapi/v1/cas/jobs/heartbeat" if cas else "/workapi/v1/jobs/heartbeat"
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
    stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(heartbeat(workapi, job, stop))
    try:
        pubchem = PubChemClient(session, rate)
        candidates = await pubchem.resolve(job["query_kind"], str(job["query_value"]))
        properties = await pubchem.properties(candidates)
        expected_cid = job.get("expected_pubchem_cid")
        property_map = {int(item.get("CID")): item for item in properties if item.get("CID")}
        selected_cid = select_verified_cid(
            candidates,
            properties,
            expected_cid=int(expected_cid) if expected_cid else None,
            expected_smiles=job.get("expected_smiles"),
        )
        if selected_cid is None:
            code = "pubchem_not_found" if not candidates else "ambiguous_pubchem_identity"
            raise PubChemError(code, "PubChem did not resolve exactly one verified CID", retryable=False)
        selected_properties = property_map.get(selected_cid, {}) if selected_cid else {}
        if not selected_properties:
            raise PubChemError(
                "pubchem_properties_missing",
                "PubChem did not return the selected CID property record",
            )
        sections: dict[str, Any] = {}
        record_title = None
        requested = set(job.get("sections") or [])
        if selected_cid is not None:
            if "computed" in requested:
                sections["computed"] = {
                    "values": selected_properties,
                    "source": "PubChem PUG REST",
                }
            if "synonyms" in requested:
                sections["synonyms"] = {
                    "values": await pubchem.synonyms(selected_cid),
                    "source": "PubChem PUG REST",
                }
            for section in sorted(requested - {"computed", "synonyms"}):
                if section not in {"identifiers", "physical", "safety", "toxicity", "regulatory", "pharmacology", "uses"}:
                    continue
                title, normalized = await pubchem.view(selected_cid, section)
                record_title = record_title or title
                sections[section] = normalized or {
                    "entries": {},
                    "references": {},
                    "unavailable": True,
                }
        candidate_summaries = [
            {
                key: item[key]
                for key in ("CID", "MolecularFormula", "MolecularWeight", "SMILES", "InChIKey", "IUPACName")
                if key in item
            }
            for item in properties[:10]
        ]
        result = {
            "selected_cid": selected_cid,
            "candidates": candidate_summaries,
            "properties": selected_properties,
            "sections": sections,
            "record_title": record_title,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source_hash": pubchem.source_hash(),
        }
        await workapi.post(
            "/workapi/v1/jobs/complete",
            {"job_id": job["job_id"], "lease_token": job["lease_token"], "result": result},
        )
        log.info("completed job=%s cid=%s", job["job_id"], selected_cid)
    except PubChemError as exc:
        await workapi.post(
            "/workapi/v1/jobs/fail",
            {
                "job_id": job["job_id"],
                "lease_token": job["lease_token"],
                "error_code": exc.code,
                "error_detail": str(exc),
                "retryable": exc.retryable,
                "retry_after_seconds": 60,
            },
        )
        log.warning("PubChem job=%s failed: %s", job["job_id"], exc)
    except Exception as exc:
        try:
            await workapi.post(
                "/workapi/v1/jobs/fail",
                {
                    "job_id": job["job_id"],
                    "lease_token": job["lease_token"],
                    "error_code": "worker_error",
                    "error_detail": str(exc)[:2000],
                    "retryable": True,
                    "retry_after_seconds": 60,
                },
            )
        except Exception:
            log.exception("could not report failure for job=%s", job["job_id"])
        log.exception("worker job=%s failed", job["job_id"])
    finally:
        stop.set()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


async def process_cas_job(
    session: aiohttp.ClientSession,
    workapi: WorkApiClient,
    job: dict[str, Any],
) -> None:
    """cas_jobs 处理: caslib 拉取解析 -> /cas/jobs/complete|fail。

    抓取预算放宽(后台路径非用户等待路径), 页间 2s 礼仪间隔。
    locale: zh-CN 主行走 fetch_cas 主链(CPP-CN 一页全量);
    en 等语言行用主表 cb_number 直拉 CPP 语言页, 只写 entry。
    """
    from caslib.fetch import fetch_cas, fetch_cpp_locale, fetch_mol
    from caslib.parse import (
        cpp_page_state, extract_mol_href, parse_cpp_entry, parse_cpp_entry_en,
        parse_cpp_suppliers, parse_entry, parse_suppliers,
    )

    locale = job.get("locale") or "zh-CN"
    stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(heartbeat(workapi, job, stop, cas=True))
    try:
        payload: dict[str, Any]
        if locale == "zh-CN":
            cb_hint = job.get("cb_number")
            result = await fetch_cas(
                job["cas_number"], total_budget_s=20.0, session=session,
                cb_number=cb_hint,
            )
            if result.status == "not_found":
                payload = {"status": "not_found", "entry": None, "suppliers": []}
            elif result.status == "error":
                raise RuntimeError(f"cas fetch error: {result.error}")
            else:
                # CPP busy 已由 fetch 层熔断计数; 这里走 CAS 页兜底出 entry,
                # job 照常成功(数据可用, CPP 增量段待上游恢复后刷新趟补)
                entry = (
                    parse_cpp_entry(result.cpp_html) if result.cpp_html else None
                ) or (parse_entry(result.cas_html) if result.cas_html else None)
                if entry is None:
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
                    # mol 文件: 详情页有外链才拉(无外链=零请求); 失败退化 None
                    mol_href = extract_mol_href(result.cas_html or "")
                    if mol_href:
                        payload["mol"] = await fetch_mol(session, mol_href)
        else:
            # 语言行: 主表 cb_number 直拉 CPP 语言页, 只写 entry。
            from caslib.fetch import cpp_circuit_open

            cb_number = job.get("cb_number")
            if not cb_number or cpp_circuit_open():
                # 熔断期/无 cb_number = "没查", 不是 "查了没有"。
                # 不 complete(否则落 not_found 负缓存抹 entry, 且 en 行
                # 无 expiry_scan 自动刷新路径, 数据会静默丢失) —
                # 回队延迟重试, retry_after 盖过 10 分钟熔断窗。
                await workapi.post(
                    "/workapi/v1/cas/jobs/fail",
                    {
                        "job_id": job["job_id"],
                        "lease_token": job["lease_token"],
                        "error_code": "cpp_circuit_defer",
                        "error_detail": (
                            f"locale={locale} deferred: "
                            f"circuit_open={cpp_circuit_open()} "
                            f"cb_number={'present' if cb_number else 'missing'}"
                        )[:2000],
                        "retryable": True,
                        "retry_after_seconds": 600,
                    },
                )
                log.info("cas job=%s deferred %s (circuit/cb_number)", job["job_id"], locale)
                return
            cpp_html = await fetch_cpp_locale(session, cb_number, locale)
            entry = parse_cpp_entry_en(cpp_html) if cpp_html else None
            if entry is None:
                # 语言页第一发没拿到 = 终态"查了没有", 不再 fail/retry(8-29 定论):
                # 大量条目 CB 本就没有 EN 变体, retry 只产无效请求(已实测死 3.4k
                # 任务/1万+发空打, 错误流量正是上游风控画像)。落 not_found 负缓存,
                # 复查交给日级 expiry 轮次; en 行是主行增量, 损失量级≈0。
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
        try:
            await workapi.post(
                "/workapi/v1/cas/jobs/fail",
                {
                    "job_id": job["job_id"],
                    "lease_token": job["lease_token"],
                    "error_code": "cas_fetch_error",
                    "error_detail": str(exc)[:2000],
                    "retryable": True,
                    "retry_after_seconds": 120,
                },
            )
        except Exception:
            log.exception("could not report cas failure for job=%s", job["job_id"])
        log.warning("cas job=%s failed: %s", job["job_id"], exc)
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
    async with aiohttp.ClientSession(connector=connector) as session:
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
        log.info("worker started id=%s concurrency=%s", worker_id, concurrency)
        idle_seconds = 2.0
        # cas 空闲退避上限收紧: 30s->10s。lease 是本地 workapi 轮询(不打外部源),
        # 换搜索miss用户重搜等待上限 40s->~20s(2026-08-28 体感收口)
        cas_idle_seconds = 2.0
        cas_idle_cap = 10.0
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
                if "cas" in _scopes:
                    cas_leased = await workapi.post(
                        "/workapi/v1/cas/jobs/lease",
                        {"max_jobs": 1, "capabilities": ["cas"]},
                    )
                    cas_jobs = cas_leased.get("jobs") or []
                    cas_coros = [process_cas_job(session, workapi, job) for job in cas_jobs]
                    if not cas_jobs:
                        cas_idle_seconds = min(cas_idle_cap, cas_idle_seconds * 1.5)
                    else:
                        cas_idle_seconds = 2.0
                if not jobs and not cas_coros:
                    requested_wait = float(leased.get("retry_after_seconds", 5)) if "pubchem" in _scopes else 5
                    idle_seconds = min(30.0, max(requested_wait, idle_seconds * 1.5))
                    await asyncio.sleep(idle_seconds + random.random())
                    continue
                idle_seconds = 2.0
                await asyncio.gather(
                    *(process_job(session, workapi, rate, job) for job in jobs),
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
