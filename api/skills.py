"""User-owned and platform-public skill registry: validate, store, fetch.

存储模型：DB 索引（community.skills / skill_files）+ FS 内容
（settings.skill_root/{skill_id}/{path}）。服务端永不执行 skill 内容；
脚本仅做语法级检查与危险调用扫描，结果作为警告披露，执行责任在拉取者。
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Path as PathParam, Query, Response, UploadFile
from sqlalchemy import text

from .core.config import settings
from .core.database import get_db
from .rate_limit_http import to_http_exception
from .core.rate_limit import RateLimitError
from .core.security import Actor, current_actor, public_or_actor, require_scope
from .services.skills import (list_skills as list_skills_service,
    SkillNotAccessibleError, get_skill_detail as get_skill_detail_service,
    load_accessible_skill)
from .services.skills import (MissingSkillIdempotencyKeyError,
    SkillArchiveValidationError, SkillCategoryError,
    SkillIdempotencyKeyTooLongError, SkillSlugConflictError)
from .services.skills import create_skill as create_skill_service
from .services.skills import extract_skill_zip
from .services.skills import validate_category
# E4 lifecycle owner(唯一 owner): adapter 只做 neutral error → HTTP 映射。
from .services.skills import (SkillArchiveUnavailableError, SkillFileNotFoundError,
    SkillFilesystemError, SkillNotFoundError, SkillUpdateValidationError,
    build_skill_archive, delete_skill_lifecycle, read_skill_file,
    update_skill_metadata)

router = APIRouter(tags=["skills"])

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SAFE_PATH_RE = re.compile(r"^[a-zA-Z0-9._-]+(?:/[a-zA-Z0-9._-]+)*$")
MAX_PATH_LEN = 200
MAX_DEPTH = 6
MAX_COMPRESSION_RATIO = 100
BINARY_DIRS = ("assets/", "examples/")

TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".sh", ".js", ".ts", ".json", ".csv", ".tsv",
    ".xsd", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".tex",
    ".rst", ".html", ".css", ".svg", ".env",
}
SCRIPT_EXTENSIONS = {".py", ".sh", ".js", ".ts", ".rb", ".pl"}

DANGER_PATTERNS = (
    "eval(", "exec(", "os.system", "subprocess", "__import__",
    "rm -rf", "curl ", "wget ", "base64 -d", "chmod +x",
    "/dev/tcp", "nc -e", "mkfifo",
)

IGNORED_PREFIXES = ("__MACOSX/",)
IGNORED_NAMES = {".DS_Store", "Thumbs.db"}


def _is_text_path(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_EXTENSIONS


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    return slug[:64].rstrip("-")


def parse_frontmatter(entry_text: str) -> dict[str, str]:
    """Parse the leading YAML-ish frontmatter of SKILL.md (flat key: value)."""
    if not entry_text.startswith("---"):
        return {}
    lines = entry_text.splitlines()
    close = None
    for i in range(1, min(len(lines), 60)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        return {}
    out: dict[str, str] = {}
    for line in lines[1:close]:
        if ":" not in line or line.startswith((" ", "\t", "-")):
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip('"').strip("'")
        if value:
            out[key.strip()] = value
    return out


def check_script_syntax(path: str, raw: bytes) -> list[str]:
    """Syntax-level checks only (ast.parse / bash -n); never execute."""
    warnings: list[str] = []
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".py":
            import ast
            ast.parse(raw.decode("utf-8", errors="replace"))
        elif suffix == ".sh":
            proc = subprocess.run(
                ["bash", "-n", "/dev/stdin"], input=raw, capture_output=True, timeout=5,
            )
            if proc.returncode != 0:
                warnings.append(f"{path}: shell 语法检查未通过")
    except (SyntaxError, UnicodeDecodeError, subprocess.TimeoutExpired):
        warnings.append(f"{path}: 语法解析失败")
    return warnings


def scan_danger(path: str, raw: bytes) -> list[str]:
    if _is_text_path(path):
        text_content = raw.decode("utf-8", errors="replace")
        return [f"{path}: 含 {pat.strip()}" for pat in DANGER_PATTERNS if pat in text_content]
    return []


async def _load_accessible_skill_http(db, skill_id: int, actor: Actor | None) -> dict[str, Any]:
    """HTTP bridge: neutral access kernel → HTTP 404 原文映射(G2.6C)。

    只做 transport 映射, 无 SQL / 无 access predicate 判定;
    canonical access invariant 在 services.skills.load_accessible_skill。
    """
    try:
        return await load_accessible_skill(
            db, skill_id, actor_id=actor.id if actor else None)
    except SkillNotAccessibleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/skills/categories",
    operation_id="list_skill_categories",
    summary="分类字典（公开；公开页与工作台的分类唯一来源）",
)
async def list_skill_categories(
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    rows = (await db.execute(text("""
        SELECT name,abbr,color,sort_order FROM community.skill_categories
        WHERE active ORDER BY sort_order, id
    """))).mappings().all()
    return [dict(r) for r in rows]


@router.get(
    "/skills",
    operation_id="list_skills",
    summary="列出公开技能池或我的技能",
)
async def list_skills(
    scope: str = Query("public", pattern="^(public|mine)$"),
    q: str = Query("", max_length=120),
    category: str = Query("", max_length=40),
    page: int = Query(1, ge=1, le=500), page_size: int = Query(30, ge=1, le=100),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    if scope == "mine":
        if actor is None:
            raise HTTPException(401, "列出自己的技能需要登录或 API Token")
        owner_id: int | None = actor.id
    else:
        owner_id = None
    # G2.6B: query kernel 下沉 services/skills.list_skills
    # (skill.query.list), adapter 只余 validation+登录墙。
    return await list_skills_service(
        db, scope=scope, owner_id=owner_id, q=q, category=category,
        page=page, page_size=page_size,
    )


@router.get(
    "/skills/{skill_id}",
    operation_id="get_skill",
    summary="读取技能 manifest、文件树与 SKILL.md 全文",
)
async def get_skill(
    skill_id: int = PathParam(..., ge=1),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    # G2.6C: detail orchestration 下沉 services.skills.get_skill_detail,
    # adapter 只余 neutral → 404 映射。
    try:
        return await get_skill_detail_service(
            db, skill_id, actor_id=actor.id if actor else None)
    except SkillNotAccessibleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/skills/{skill_id}/content/{file_path:path}",
    operation_id="get_skill_file",
    summary="读取技能内单个文本文件",
)
async def get_skill_file(
    skill_id: int = PathParam(..., ge=1),
    file_path: str = PathParam(...),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    await _load_accessible_skill_http(db, skill_id, actor)
    # E4: manifest 行读取 + is_text 判定 + FS 读取归 services.skills.read_skill_file;
    # adapter 只余 access 404 桥 + neutral → 404 原文映射。
    try:
        return await read_skill_file(db, skill_id, file_path=file_path)
    except SkillFileNotFoundError as exc:
        raise HTTPException(404, exc.detail) from exc


@router.get(
    "/skills/{skill_id}/archive",
    operation_id="download_skill_archive",
    summary="下载技能完整 zip 包",
)
async def download_skill_archive(
    skill_id: int = PathParam(..., ge=1),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    manifest = await _load_accessible_skill_http(db, skill_id, actor)
    # E4: skill_files 查询 + 目录/文件缺失判定 + zip 组装归
    # services.skills.build_skill_archive; adapter 只余 access 404 桥 +
    # Response 构造(传输层: media_type / Content-Disposition)。
    try:
        payload = await build_skill_archive(db, skill_id)
    except SkillArchiveUnavailableError as exc:
        raise HTTPException(500, exc.detail) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{manifest["slug"]}.zip"'},
    )


@router.post(
    "/skills/validate",
    operation_id="validate_skill",
    summary="校验技能 zip 草稿（不保存）",
)
async def validate_skill(
    file: UploadFile = File(...),
    actor: Actor = Depends(current_actor),
):
    # REST 与 MCP 对齐(B4): validate_skill 统一要求 skill:write。
    # require_scope 只收紧 agent token, web session 行为不变。
    require_scope(actor, "skill:write")
    raw = await file.read(settings.skill_zip_max_bytes + 1)
    if len(raw) > settings.skill_zip_max_bytes:
        raise HTTPException(400, f"压缩包超过 {settings.skill_zip_max_bytes // (1024 * 1024)}MB 上限")
    # G3.1D: kernel owner 迁 services.skills; neutral → HTTP 400 原文。
    try:
        manifest = await asyncio.to_thread(extract_skill_zip, raw)
    except SkillArchiveValidationError as exc:
        raise HTTPException(400, exc.detail) from exc
    return {
        "ok": True,
        "slug": manifest["slug"],
        "title": manifest["title"],
        "description": manifest["description"],
        "license": manifest["license"],
        "has_scripts": manifest["has_scripts"],
        "file_count": manifest["file_count"],
        "size_bytes": manifest["size_bytes"],
        "warnings": manifest["warnings"],
        "files": [{"path": p, "size_bytes": len(d)} for p, d in manifest["files"]],
    }


@router.post(
    "/skills",
    status_code=201,
    operation_id="create_skill",
    summary="上传并保存技能（zip）",
)
async def create_skill(
    file: UploadFile = File(...),
    category: str | None = Query(None, max_length=40),
    request_idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    # G3.1D: rate/category/幂等/size/extract/事务全部下沉
    # services.skills.create_skill(payload loader); adapter 只余 auth/scope
    # + loader 构造 + neutral → HTTP 映射。读文件时机由 service 决定
    # (rate→category→key→预检 之后才 loader(max+1)), 保持原 ordering。
    require_scope(actor, "skill:write")

    async def archive_loader(limit: int) -> bytes:
        return await file.read(limit)

    try:
        return await create_skill_service(
            db, actor_id=actor.id, auth_kind=actor.auth_kind,
            category=category, idempotency_key=request_idempotency_key,
            archive_loader=archive_loader)
    except SkillArchiveValidationError as exc:
        raise HTTPException(400, exc.detail) from exc
    except SkillCategoryError as exc:
        raise HTTPException(400, exc.detail) from exc
    except SkillSlugConflictError as exc:
        raise HTTPException(409, exc.detail) from exc
    except MissingSkillIdempotencyKeyError as exc:
        raise HTTPException(400, exc.detail) from exc
    except SkillIdempotencyKeyTooLongError as exc:
        raise HTTPException(400, exc.detail) from exc
    except RateLimitError as exc:
        raise to_http_exception(exc) from exc


@router.patch(
    "/skills/{skill_id}",
    operation_id="update_skill",
    summary="更新技能标题或描述（分类与公开态由平台管理，不在此路径）",
)
async def update_skill(
    body: dict[str, Any],
    skill_id: int = PathParam(..., ge=1),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    if actor.auth_kind == "agent":
        raise HTTPException(403, "API Token 当前不开放技能编辑，请使用网页登录会话")
    current = await _load_accessible_skill_http(db, skill_id, actor)
    if current["owner_id"] != actor.id:
        raise HTTPException(403, "只能编辑自己创建的技能")
    # E4: validation + DB mutation + commit + readback 归
    # services.skills.update_skill_metadata; adapter 只余授权判定 + neutral → HTTP 映射。
    try:
        return await update_skill_metadata(
            db, skill_id, title=body.get("title"),
            description=body.get("description"), actor_id=actor.id)
    except SkillUpdateValidationError as exc:
        raise HTTPException(400, exc.detail) from exc


@router.delete(
    "/skills/{skill_id}",
    status_code=204,
    operation_id="delete_skill",
    summary="删除技能及其全部文件",
)
async def delete_skill(
    skill_id: int = PathParam(..., ge=1),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    if actor.auth_kind == "agent":
        raise HTTPException(403, "API Token 当前不开放技能删除，请使用网页登录会话")
    current = await _load_accessible_skill_http(db, skill_id, actor)
    if current["owner_id"] != actor.id:
        raise HTTPException(403, "只能删除自己创建的技能")
    # E4: 行锁 / DB 删除 / FS staging / 补偿 / 清理归
    # services.skills.delete_skill_lifecycle(user 与 admin 共用同一 owner)。
    # SkillNotFoundError = 授权检查与行锁之间的并发 delete 竞态 → 404(与重复删除同语义)。
    try:
        await delete_skill_lifecycle(db, skill_id)
    except SkillNotFoundError as exc:
        raise HTTPException(404, exc.detail) from exc
    except SkillFilesystemError as exc:
        raise HTTPException(500, exc.detail) from exc
