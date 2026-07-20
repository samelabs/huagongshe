"""Distributed PubChem worker.  It never opens a database connection."""

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

from .pubchem import PubChemClient, PubChemError
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
        if len(body) > 1_900_000:
            raise RuntimeError("workapi payload exceeds the 1.9 MB worker safety limit")
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
    interval = max(20, int(job.get("lease_seconds", 180)) // 3)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            await client.post(
                "/workapi/v1/jobs/heartbeat",
                {"job_id": job["job_id"], "lease_token": job["lease_token"]},
            )


async def process_job(
    session: aiohttp.ClientSession, workapi: WorkApiClient, job: dict[str, Any]
) -> None:
    stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(heartbeat(workapi, job, stop))
    try:
        pubchem = PubChemClient(session, workapi)
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
            for section in sorted(requested - {"computed"}):
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


async def run() -> None:
    base_url = os.environ["HGS_WORKAPI_URL"]
    worker_id = os.environ["HGS_WORKER_ID"]
    token = os.environ["HGS_WORKER_TOKEN"]
    concurrency = min(max(int(os.environ.get("HGS_WORKER_CONCURRENCY", "2")), 1), 8)
    connector = aiohttp.TCPConnector(limit=concurrency + 4, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        workapi = WorkApiClient(session, base_url, worker_id, token)
        log.info("worker started id=%s concurrency=%s", worker_id, concurrency)
        idle_seconds = 2.0
        while True:
            try:
                leased = await workapi.post(
                    "/workapi/v1/jobs/lease",
                    {"max_jobs": concurrency, "capabilities": ["pubchem"]},
                )
                jobs = leased.get("jobs") or []
                if not jobs:
                    requested_wait = float(leased.get("retry_after_seconds", 5))
                    idle_seconds = min(30.0, max(requested_wait, idle_seconds * 1.5))
                    await asyncio.sleep(idle_seconds + random.random())
                    continue
                idle_seconds = 2.0
                await asyncio.gather(*(process_job(session, workapi, job) for job in jobs))
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
