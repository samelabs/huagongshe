"""对外数据服务 HTTP 路由(/data/v1, 只读 GET)。

经接入层(nginx /data/)直连 FastAPI, 不经站内代理。每个请求:
凭证(HMAC 签名 + 时间窗 + nonce 防重放) → scope 精确映射 → 按凭证计量
→ 领域服务层取数 → 投影输出。响应统一 JSON 且带 request_id; 错误统一
{"error": {"code", "message"}}。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .core.database import get_db
from .services.chemicals import ChemicalNotFoundError, get_chemical_detail
from .services.data_api.auth import (
    DataApiAuthError, authorize_scope, body_sha256_hex, check_nonce,
    CHEMICAL_INGEST_SCOPE,
    load_client, sign_message, verify_signature,
)
from .services.data_api.lookup import DataApiInvalidParameter, lookup
from .services.data_api.metering import enforce_quota, record_usage
from .services.data_api.projections import (
    project_chemical, project_reaction, project_reaction_summary,
)
from .services.reactions import load_reaction_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data/v1", tags=["data-api"])

CHEMICAL_BATCH_MAX = 50
REACTION_BATCH_MAX = 20
REACTION_PAGE_MAX = 50
REACTION_PAGE_SIZE_DEFAULT = 20
# 采集/刷新入队走后台优先级(与站内后台刷新同档), 不占用户优先级。
ENRICH_PRIORITY_BACKGROUND = 40
SITE_ORIGIN = "https://huagongshe.com"


def _payload(request_id: str, **fields: Any) -> dict[str, Any]:
    return {"request_id": request_id, **fields}


def _error_response(exc: Exception, request_id: str) -> JSONResponse:
    if isinstance(exc, DataApiAuthError):
        status, code, message = exc.status, exc.code, exc.message
    elif isinstance(exc, DataApiInvalidParameter):
        status, code, message = 422, "invalid_parameter", exc.message
    else:
        status, code, message = 404, "not_found", str(exc)
    response = JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}, "request_id": request_id})
    cause = getattr(exc, "__cause__", None)
    retry_after = getattr(cause, "retry_after", None)
    if code == "rate_limited":
        response.headers["Retry-After"] = str(retry_after or 60)
    return response


async def _authenticate(request: Request, db, path_template: str):  # noqa: ANN202
    """凭证校验链: 鉴权头 → 载入凭证 → 签名 → nonce → scope → 计量。

    返回已通过校验的凭证; 失败抛 DataApiAuthError。签名按真实请求要素
    (method / path / query / body 哈希 / timestamp / nonce)计算。
    """
    auth = request.headers.get("authorization", "") or ""
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    client_id = (request.headers.get("x-client-id", "") or "").strip()
    timestamp = request.headers.get("x-timestamp", "")
    nonce = request.headers.get("x-nonce", "")
    signature = request.headers.get("x-signature", "")
    if not token or not client_id or not timestamp or not nonce or not signature:
        raise DataApiAuthError("unauthorized", "缺少鉴权头")
    client = await load_client(db, client_id, token)
    verify_signature(
        token,
        method=request.method, path=request.url.path, query=request.url.query,
        body=await request.body(), timestamp=timestamp, nonce=nonce,
        signature=signature)
    await check_nonce(client.client_id, nonce)
    authorize_scope(client, request.method, path_template)
    await enforce_quota(client)
    return client


@router.get("/chemicals/lookup")
async def chemicals_lookup(
    request: Request,
    hcid: int | None = Query(None),
    cas: str | None = Query(None, max_length=40),
    smiles: str | None = Query(None, max_length=4000),
    inchikey: str | None = Query(None, max_length=30),
    name: str | None = Query(None, max_length=500),
    locale: str | None = Query(None, max_length=10),
    db=Depends(get_db),
):
    """按唯一标识或名称查化合物候选; 未收录的 SMILES 建行、CAS 入列采集。"""
    request_id = uuid.uuid4().hex
    provided = [v for v in (hcid, cas, smiles, inchikey, name) if v is not None]
    if len(provided) != 1:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_parameter",
                               "message": "hcid / cas / smiles / inchikey / name 只能提供一个"},
                     "request_id": request_id})
    client = None
    try:
        client = await _authenticate(request, db, "/data/v1/chemicals/lookup")
        result = await lookup(db, locale=locale, hcid=hcid, cas=cas,
                              smiles=smiles, inchikey=inchikey, name=name,
                              allow_ingest=CHEMICAL_INGEST_SCOPE in client.scopes)
        await record_usage(db, client.id)
        return _payload(request_id, **result)
    except (DataApiAuthError, DataApiInvalidParameter) as exc:
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(exc, request_id)
    except ChemicalNotFoundError as exc:
        await record_usage(db, client.id, error=True)
        return _error_response(exc, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("data api lookup failed", exc_info=True)
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(
            DataApiAuthError("unavailable", "服务暂时不可用", status=503), request_id)


@router.get("/chemicals/{hcid}")
async def chemical_detail(
    request: Request,
    hcid: int,
    locale: str | None = Query(None, max_length=10),
    db=Depends(get_db),
):
    """单个化合物的完整投影(与站内详情页同分区同字段)。"""
    request_id = uuid.uuid4().hex
    client = None
    try:
        client = await _authenticate(request, db, "/data/v1/chemicals/{hcid}")
        detail = await get_chemical_detail(
            db, hcid, actor_id=None, priority=ENRICH_PRIORITY_BACKGROUND,
            enrich="full", locale=locale, pb_display_limit=True)
        await record_usage(db, client.id)
        return _payload(request_id, chemical=project_chemical(detail, locale or "en", site_origin=SITE_ORIGIN))
    except (DataApiAuthError, ChemicalNotFoundError) as exc:
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(exc, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("data api chemical detail failed", exc_info=True)
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(
            DataApiAuthError("unavailable", "服务暂时不可用", status=503), request_id)


@router.get("/chemicals")
async def chemicals_batch(
    request: Request,
    ids: str = Query(..., max_length=600),
    locale: str | None = Query(None, max_length=10),
    db=Depends(get_db),
):
    """批量取化合物(每次最多 50 个)。"""
    request_id = uuid.uuid4().hex
    client = None
    try:
        client = await _authenticate(request, db, "/data/v1/chemicals")
        raw_ids = [chunk.strip() for chunk in ids.split(",") if chunk.strip()]
        if not raw_ids or len(raw_ids) > CHEMICAL_BATCH_MAX:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "invalid_parameter",
                                   "message": f"ids 数量须在 1–{CHEMICAL_BATCH_MAX} 之间"},
                         "request_id": request_id})
        parsed: list[int] = []
        for chunk in raw_ids:
            if not chunk.isdigit():
                return JSONResponse(
                    status_code=422,
                    content={"error": {"code": "invalid_parameter",
                                       "message": "ids 只能包含 HCID 数字"},
                             "request_id": request_id})
            parsed.append(int(chunk))
        items: list[dict[str, Any]] = []
        missing: list[int] = []
        for hcid in parsed:
            try:
                detail = await get_chemical_detail(
                    db, hcid, actor_id=None, priority=ENRICH_PRIORITY_BACKGROUND,
                    enrich="full", locale=locale, pb_display_limit=True)
                items.append(project_chemical(detail, locale or "en", site_origin=SITE_ORIGIN))
            except ChemicalNotFoundError:
                missing.append(hcid)
        await record_usage(db, client.id)
        return _payload(request_id, items=items, missing=missing)
    except DataApiAuthError as exc:
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(exc, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("data api chemicals batch failed", exc_info=True)
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(
            DataApiAuthError("unavailable", "服务暂时不可用", status=503), request_id)


@router.get("/chemicals/{hcid}/reactions")
async def chemical_reactions(
    request: Request,
    hcid: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(REACTION_PAGE_SIZE_DEFAULT, ge=1, le=REACTION_PAGE_MAX),
    db=Depends(get_db),
):
    """该化合物参与的公开反应摘要(分页)。"""
    request_id = uuid.uuid4().hex
    client = None
    try:
        client = await _authenticate(request, db, "/data/v1/chemicals/{hcid}/reactions")
        offset = (page - 1) * page_size
        rows = (await db.execute(text("""
            SELECT rx.id, rx.reaction_smiles, rx.visibility, rx.updated_at,
                   (SELECT count(*) FROM chemistry.reaction_chemicals rc2
                     WHERE rc2.reaction_id = rx.id)
            FROM chemistry.reaction_chemicals rc
            JOIN chemistry.reactions rx ON rx.id = rc.reaction_id
            WHERE rc.chemical_id = :cid
              AND rx.visibility = 'public' AND rx.moderation_status = 'visible'
            ORDER BY rx.updated_at DESC NULLS LAST, rx.id DESC
            LIMIT :n OFFSET :offset
        """), {"cid": hcid, "n": page_size + 1, "offset": offset})).fetchall()
        total_row = (await db.execute(text("""
            SELECT count(*)
            FROM chemistry.reaction_chemicals rc
            JOIN chemistry.reactions rx ON rx.id = rc.reaction_id
            WHERE rc.chemical_id = :cid
              AND rx.visibility = 'public' AND rx.moderation_status = 'visible'
        """), {"cid": hcid})).scalar()
        await record_usage(db, client.id)
        return _payload(
            request_id,
            items=[project_reaction_summary(row) for row in rows[:page_size]],
            total=int(total_row or 0),
            page=page, page_size=page_size,
            has_more=len(rows) > page_size)
    except DataApiAuthError as exc:
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(exc, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("data api chemical reactions failed", exc_info=True)
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(
            DataApiAuthError("unavailable", "服务暂时不可用", status=503), request_id)


@router.get("/reactions/{hrid}")
async def reaction_detail(
    request: Request,
    hrid: int,
    locale: str | None = Query(None, max_length=10),
    db=Depends(get_db),
):
    """单个公开反应的完整投影(私有反应不可见)。"""
    request_id = uuid.uuid4().hex
    client = None
    try:
        client = await _authenticate(request, db, "/data/v1/reactions/{hrid}")
        reaction = await load_reaction_detail(db, hrid, viewer_id=0, viewer_is_admin=False)
        if reaction is None:
            raise ChemicalNotFoundError("反应不存在或不可见")
        await record_usage(db, client.id)
        return _payload(request_id, reaction=project_reaction(reaction, locale or "en", site_origin=SITE_ORIGIN))
    except (DataApiAuthError, ChemicalNotFoundError) as exc:
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(exc, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("data api reaction detail failed", exc_info=True)
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(
            DataApiAuthError("unavailable", "服务暂时不可用", status=503), request_id)


@router.get("/reactions")
async def reactions_batch(
    request: Request,
    ids: str = Query(..., max_length=300),
    locale: str | None = Query(None, max_length=10),
    db=Depends(get_db),
):
    """批量取公开反应(每次最多 20 个)。"""
    request_id = uuid.uuid4().hex
    client = None
    try:
        client = await _authenticate(request, db, "/data/v1/reactions")
        raw_ids = [chunk.strip() for chunk in ids.split(",") if chunk.strip()]
        if not raw_ids or len(raw_ids) > REACTION_BATCH_MAX:
            return JSONResponse(
                status_code=422,
                content={"error": {"code": "invalid_parameter",
                                   "message": f"ids 数量须在 1–{REACTION_BATCH_MAX} 之间"},
                         "request_id": request_id})
        items: list[dict[str, Any]] = []
        missing: list[int] = []
        for chunk in raw_ids:
            if not chunk.isdigit():
                return JSONResponse(
                    status_code=422,
                    content={"error": {"code": "invalid_parameter",
                                       "message": "ids 只能包含 HRID 数字"},
                             "request_id": request_id})
            reaction = await load_reaction_detail(db, int(chunk), viewer_id=0, viewer_is_admin=False)
            if reaction is None:
                missing.append(int(chunk))
            else:
                items.append(project_reaction(reaction, locale or "en", site_origin=SITE_ORIGIN))
        await record_usage(db, client.id)
        return _payload(request_id, items=items, missing=missing)
    except DataApiAuthError as exc:
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(exc, request_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("data api reactions batch failed", exc_info=True)
        if client is not None:
            await record_usage(db, client.id, error=True)
        return _error_response(
            DataApiAuthError("unavailable", "服务暂时不可用", status=503), request_id)
