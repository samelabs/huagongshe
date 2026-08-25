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
    """
    from caslib.fetch import fetch_cas
    from caslib.parse import parse_entry, parse_suppliers

    stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(heartbeat(workapi, job, stop, cas=True))
    try:
        result = await fetch_cas(
            job["cas_number"], total_budget_s=20.0, session=session
        )
        if result.status == "not_found":
            payload = {"status": "not_found", "entry": None, "suppliers": []}
        elif result.status == "error":
            raise RuntimeError(f"cas fetch error: {result.error}")
        else:
            entry = parse_entry(result.cas_html or "")
            if entry is None:
                payload = {"status": "not_found", "entry": None, "suppliers": []}
            else:
                suppliers = parse_suppliers(result.cas_html or "", result.supplier_html)
                payload = {"status": "ok", "entry": entry, "suppliers": suppliers}
        await workapi.post(
            "/workapi/v1/cas/jobs/complete",
            {"job_id": job["job_id"], "lease_token": job["lease_token"], "result": payload},
        )
        log.info("cas job=%s %s", job["job_id"], payload["status"])
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
        workapi = WorkApiClient(session, base_url, worker_id, token)
        rate = PubChemRateController(requests_per_second)
        log.info("worker started id=%s concurrency=%s", worker_id, concurrency)
        idle_seconds = 2.0
        cas_idle_seconds = 2.0
        while True:
            try:
                # 双队列: pubchem 优先轮询, cas 每轮附带认领(单并发,礼仪串行)
                leased = await workapi.post(
                    "/workapi/v1/jobs/lease",
                    {"max_jobs": concurrency, "capabilities": ["pubchem"]},
                )
                jobs = leased.get("jobs") or []
                cas_coros = []
                if "cas" in os.environ.get("HGS_WORKER_SCOPES", "pubchem,cas").split(","):
                    cas_leased = await workapi.post(
                        "/workapi/v1/cas/jobs/lease",
                        {"max_jobs": 1, "capabilities": ["cas"]},
                    )
                    cas_jobs = cas_leased.get("jobs") or []
                    cas_coros = [process_cas_job(session, workapi, job) for job in cas_jobs]
                    if not cas_jobs:
                        cas_idle_seconds = min(30.0, cas_idle_seconds * 1.5)
                    else:
                        cas_idle_seconds = 2.0
                if not jobs and not cas_coros:
                    requested_wait = float(leased.get("retry_after_seconds", 5))
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
