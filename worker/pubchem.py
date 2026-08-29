"""PubChem PUG REST/PUG View client and bounded annotation normalizer."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any
from urllib.parse import quote

import aiohttp

PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"
PROPERTY_NAMES = ",".join(
    (
        "MolecularFormula",
        "MolecularWeight",
        "MonoisotopicMass",
        "ExactMass",
        "SMILES",
        "ConnectivitySMILES",
        "InChI",
        "InChIKey",
        "IUPACName",
        "Title",
        "XLogP",
        "TPSA",
        "Complexity",
        "Charge",
        "HBondDonorCount",
        "HBondAcceptorCount",
        "RotatableBondCount",
        "HeavyAtomCount",
    )
)
VIEW_HEADINGS = {
    "identifiers": "Other Identifiers",
    "physical": "Experimental Properties",
    "safety": "Safety and Hazards",
    "toxicity": "Toxicity",
    "regulatory": "Regulatory Information",
    "pharmacology": "Pharmacology and Biochemistry",
    "uses": "Use and Manufacturing",
}
STATUS_RE = re.compile(r"(?:Request Count|Request Time|Service) status: ([A-Za-z]+)", re.I)
STATUS_RANK = {"green": 0, "idle": 0, "yellow": 1, "moderate": 1, "red": 2, "busy": 2, "black": 3, "overloaded": 3}
MAX_NORMALIZED_ENTRIES = 400
MAX_NORMALIZED_TEXT_CHARS = 150_000
MAX_NORMALIZED_REFERENCES = 100


class PubChemError(RuntimeError):
    # 8-29 规范: PB 任务单趟制 — 所有错误形态都是终态(retryable=False)。
    # 秒级 retry 无合法场景; lease 过期回队是 attempt 的唯一合法用途。
    def __init__(self, code: str, detail: str, *, retryable: bool = False):
        super().__init__(detail)
        self.code = code
        self.retryable = retryable


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


def _reference(reference: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "SourceName",
        "SourceID",
        "Name",
        "URL",
        "Description",
        "LicenseNote",
        "LicenseURL",
    )
    limits = {
        "SourceName": 500, "SourceID": 500, "Name": 500, "URL": 2000,
        "Description": 1000, "LicenseNote": 1000, "LicenseURL": 2000,
    }
    result = {
        key: str(reference[key])[:limits[key]]
        for key in allowed if reference.get(key) is not None
    }
    return result


def _value(value: dict[str, Any], budget: list[int]) -> tuple[Any, bool]:
    if not isinstance(value, dict):
        return None, False
    clipped = False

    def bounded_text(raw: Any) -> str:
        nonlocal clipped
        text = str(raw)
        allowed = max(0, min(2000, budget[0]))
        if len(text) > allowed:
            clipped = True
        result = text[:allowed]
        budget[0] -= len(result)
        return result

    if value.get("StringWithMarkup"):
        source = value["StringWithMarkup"]
        clipped = len(source) > 20
        return [bounded_text(item.get("String", "")) for item in source[:20] if item.get("String")], clipped
    if value.get("Number") is not None:
        numbers = value["Number"]
        if isinstance(numbers, list):
            return numbers[:20], len(numbers) > 20
        return numbers, False
    for key in ("String", "Boolean", "DateISO8601", "ExternalDataURL"):
        if key in value:
            item = value[key]
            return (bounded_text(item), clipped) if isinstance(item, str) else (item, False)
    return None, False


def normalize_view(payload: dict[str, Any], section_name: str) -> dict[str, Any]:
    record = payload.get("Record") or {}
    all_references = {
        str(item.get("ReferenceNumber")): _reference(item)
        for item in record.get("Reference", [])
        if item.get("ReferenceNumber") is not None
    }
    used_references: set[str] = set()
    entries: dict[str, list[dict[str, Any]]] = {}
    text_budget = [MAX_NORMALIZED_TEXT_CHARS]
    kept_entries = 0
    omitted_entries = 0
    clipped_values = 0

    def walk(sections: list[dict[str, Any]] | None, path: tuple[str, ...] = ()) -> None:
        nonlocal kept_entries, omitted_entries, clipped_values
        for section in sections or []:
            heading = str(section.get("TOCHeading") or "").strip()
            current = path + ((heading,) if heading else ())
            path_key = " > ".join(current)
            for info in section.get("Information", [])[:100]:
                if kept_entries >= MAX_NORMALIZED_ENTRIES or text_budget[0] <= 0:
                    omitted_entries += 1
                    continue
                value, clipped = _value(info.get("Value") or {}, text_budget)
                if value in (None, [], ""):
                    continue
                refs = info.get("ReferenceNumber") or []
                if not isinstance(refs, list):
                    refs = [refs]
                refs = [str(item) for item in refs[:10]]
                if len(used_references) >= MAX_NORMALIZED_REFERENCES:
                    refs = [item for item in refs if item in used_references]
                else:
                    room = MAX_NORMALIZED_REFERENCES - len(used_references)
                    new_refs = [item for item in refs if item not in used_references][:room]
                    refs = [item for item in refs if item in used_references] + new_refs
                used_references.update(refs)
                item = {"value": value, "references": refs}
                if info.get("Name"):
                    item["name"] = str(info["Name"])[:500]
                if (info.get("Value") or {}).get("Unit"):
                    item["unit"] = str(info["Value"]["Unit"])[:100]
                if info.get("Description"):
                    item["description"] = str(info["Description"])[:1000]
                bucket = entries.setdefault(path_key or section_name, [])
                if len(bucket) < 50:
                    bucket.append(item)
                    kept_entries += 1
                    clipped_values += int(clipped)
                else:
                    omitted_entries += 1
            walk(section.get("Section"), current)

    walk(record.get("Section"))
    references = {
        key: all_references[key] for key in sorted(used_references) if key in all_references
    }
    normalization = {
        "truncated": bool(omitted_entries or clipped_values),
        "kept_entries": kept_entries,
        "omitted_entries": omitted_entries,
        "clipped_values": clipped_values,
        "limits": {
            "entries": MAX_NORMALIZED_ENTRIES,
            "text_characters": MAX_NORMALIZED_TEXT_CHARS,
            "references": MAX_NORMALIZED_REFERENCES,
        },
    }
    normalized = {"entries": entries, "references": references, "normalization": normalization}
    if section_name != "safety":
        return normalized

    ghs: dict[str, Any] = {}
    hazards: dict[str, Any] = {}
    measures: dict[str, Any] = {}
    for path, values in entries.items():
        lower = path.lower()
        if "ghs classification" in lower:
            ghs[path] = values
        elif any(term in lower for term in (
            "first aid", "fire fighting", "accidental release", "handling and storage",
            "exposure control", "personal protection",
        )):
            measures[path] = values
        else:
            hazards[path] = values
    return {
        "ghs": {"entries": ghs},
        "hazards": {"entries": hazards},
        "measures": {"entries": measures},
        "references": references,
        "normalization": normalization,
    }


def extract_synonyms(payload: dict[str, Any] | None) -> list[str]:
    """Preserve the complete active synonym list and PubChem response order."""
    information = ((payload or {}).get("InformationList") or {}).get("Information") or []
    if not information:
        return []
    values = information[0].get("Synonym") or []
    return [value for value in values if isinstance(value, str)]


class PubChemClient:
    def __init__(self, session: aiohttp.ClientSession, rate: PubChemRateController):
        self.session = session
        self.rate = rate
        self.response_hashes: list[str] = []

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        # 8-29 规范: 单趟制 — 无内部重试循环。任何失败形态一次定型:
        # miss(404)=None / 拒绝(403|302跳转|封禁页|4xx)=refused 终态 /
        # 上游5xx|网络错=终态。lease 过期回队是任务级唯一合法重试路径。
        await self.rate.acquire()
        try:
            async with self.session.request(
                method,
                url,
                data=data,
                params=params,
                timeout=aiohttp.ClientTimeout(total=28),
                headers={"User-Agent": "huagongshe-pubchem-worker/1.0"},
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
                    # NCBI 封禁页(200+text/html+"Access Denied"): 置 redis 熔断
                    # key(server lease 闸门认它) + refused 终态
                    if "Access Denied" in raw_text[:2000] and "ncbi" in raw_text.lower():
                        try:
                            from api.cache import get_cache

                            redis = await get_cache()
                            if redis is not None:
                                await redis.set("pubchem:circuit_blocked", "1", ex=6 * 3600)
                        except Exception:
                            pass
                        raise PubChemError("pubchem_refused", "PubChem ban page (Access Denied)")
                    raise PubChemError("unexpected_content_type", "PubChem did not return JSON")
                self.response_hashes.append(hashlib.sha256(raw).hexdigest())
                return json.loads(raw)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise PubChemError("network_error", str(exc)) from exc

    async def resolve(self, kind: str, value: str) -> list[int]:
        if kind == "cid":
            return [int(value)] if value.isdigit() and int(value) > 0 else []
        if kind == "cas":
            url = f"{PUG_REST}/compound/name/{quote(value, safe='')}/cids/JSON"
            payload = await self.request_json("GET", url)
        elif kind == "inchikey":
            url = f"{PUG_REST}/compound/inchikey/{quote(value, safe='')}/cids/JSON"
            payload = await self.request_json("GET", url)
        elif kind == "smiles":
            url = f"{PUG_REST}/compound/fastidentity/smiles/cids/JSON"
            payload = await self.request_json(
                "POST", url, data={"smiles": value}, params={"identity_type": "same_stereo_isotope"}
            )
        else:
            raise PubChemError("unsupported_query", f"unsupported query kind {kind}", retryable=False)
        identifiers = (payload or {}).get("IdentifierList") or {}
        return [int(cid) for cid in identifiers.get("CID", [])[:20] if int(cid) > 0]

    async def properties(self, cids: list[int]) -> list[dict[str, Any]]:
        if not cids:
            return []
        cid_text = ",".join(str(cid) for cid in cids[:20])
        url = f"{PUG_REST}/compound/cid/{cid_text}/property/{PROPERTY_NAMES}/JSON"
        payload = await self.request_json("GET", url)
        return list(((payload or {}).get("PropertyTable") or {}).get("Properties") or [])

    async def synonyms(self, cid: int) -> list[str]:
        url = f"{PUG_REST}/compound/cid/{cid}/synonyms/JSON"
        return extract_synonyms(await self.request_json("GET", url))

    async def view(self, cid: int, section: str) -> tuple[str | None, dict[str, Any]]:
        heading = VIEW_HEADINGS[section]
        url = f"{PUG_VIEW}/data/compound/{cid}/JSON"
        payload = await self.request_json("GET", url, params={"heading": heading})
        if not payload:
            return None, {}
        record = payload.get("Record") or {}
        return record.get("RecordTitle"), normalize_view(payload, section)

    def source_hash(self) -> str:
        return hashlib.sha256("\n".join(sorted(self.response_hashes)).encode()).hexdigest()
