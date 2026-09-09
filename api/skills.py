"""User-owned and platform-public skill registry: validate, store, fetch.

存储模型：DB 索引（community.skills / skill_files）+ FS 内容
（settings.skill_root/{skill_id}/{path}）。服务端永不执行 skill 内容；
脚本仅做语法级检查与危险调用扫描，结果作为警告披露，执行责任在拉取者。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Path as PathParam, Query, Response, UploadFile
from sqlalchemy import text

from .core.config import settings
from .core.database import get_db
from .core.rate_limit import enforce
from .core.security import Actor, current_actor, public_or_actor, require_scope

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


def extract_skill_zip(raw: bytes) -> dict[str, Any]:
    """Validate and normalize an uploaded skill zip entirely in memory.

    Returns manifest + normalized files; raises HTTPException on any violation.
    """
    if len(raw) > settings.skill_zip_max_bytes:
        raise HTTPException(400, f"压缩包超过 {settings.skill_zip_max_bytes // (1024 * 1024)}MB 上限")

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(400, "不是有效的 zip 文件")

    entries: list[tuple[str, bytes]] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name.startswith(IGNORED_PREFIXES) or Path(name).name in IGNORED_NAMES:
            continue
        if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
            raise HTTPException(400, f"非法路径：{name}")
        if not SAFE_PATH_RE.match(name) or len(name) > MAX_PATH_LEN:
            raise HTTPException(400, f"非法路径：{name}")
        if len(Path(name).parts) > MAX_DEPTH:
            raise HTTPException(400, f"目录层级过深：{name}")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise HTTPException(400, f"不允许符号链接：{name}")
        raw_bytes = archive.read(info)
        if info.compress_size and len(raw_bytes) > info.compress_size * MAX_COMPRESSION_RATIO:
            raise HTTPException(400, f"压缩比异常（疑似 zip 炸弹）：{name}")
        entries.append((name, raw_bytes))

    if not entries:
        raise HTTPException(400, "压缩包内没有文件")
    if len(entries) > settings.skill_max_files:
        raise HTTPException(400, f"文件数超过 {settings.skill_max_files} 上限")
    total = sum(len(data) for _, data in entries)
    if total > settings.skill_total_max_bytes:
        raise HTTPException(400, f"解包后总量超过 {settings.skill_total_max_bytes // (1024 * 1024)}MB 上限")
    for name, data in entries:
        if len(data) > settings.skill_file_max_bytes:
            raise HTTPException(400, f"单文件超过 {settings.skill_file_max_bytes // (1024 * 1024)}MB 上限：{name}")

    # 单一根目录则剥掉（kdense 等打包习惯）
    first_parts = {Path(name).parts[0] for name, _ in entries}
    if len(first_parts) == 1 and "SKILL.md" not in first_parts:
        stripped: list[tuple[str, bytes]] = []
        for name, data in entries:
            parts = Path(name).parts[1:]
            if not parts:
                continue
            stripped.append(("/".join(parts), data))
        entries = stripped

    if not any(name == "SKILL.md" for name, _ in entries):
        raise HTTPException(400, "压缩包根目录必须包含 SKILL.md")

    # 二进制只允许 assets/、examples/（与 DB CHECK 一致；kdense 实证二进制在 examples/）
    for name, data in entries:
        if b"\x00" in data[:4096] and not _is_text_path(name):
            if not name.startswith(BINARY_DIRS):
                raise HTTPException(400, f"二进制文件只能放在 assets/ 或 examples/ 目录：{name}")

    entry_text = next(data.decode("utf-8", errors="replace") for name, data in entries if name == "SKILL.md")
    frontmatter = parse_frontmatter(entry_text)
    name = frontmatter.get("name", "").strip()
    description = frontmatter.get("description", "").strip()
    if not name or not description:
        raise HTTPException(400, "SKILL.md frontmatter 必须包含 name 和 description")
    slug = _slugify(name)
    if not SLUG_RE.match(slug):
        raise HTTPException(400, f"技能名无法转为合法 slug：{name!r}")

    warnings: list[str] = []
    has_scripts = any(Path(n).suffix.lower() in SCRIPT_EXTENSIONS for n, _ in entries)
    if has_scripts:
        for fname, fdata in entries:
            if Path(fname).suffix.lower() in {".py", ".sh"}:
                warnings.extend(check_script_syntax(fname, fdata))
            warnings.extend(scan_danger(fname, fdata))
        warnings = warnings[:20]

    return {
        "slug": slug,
        "title": (frontmatter.get("title") or name)[:120],
        "description": description[:500],
        "license": (frontmatter.get("license") or "MIT")[:80],
        "has_scripts": has_scripts,
        "file_count": len(entries),
        "size_bytes": total,
        "warnings": warnings,
        "files": entries,
    }


async def validate_category(db, category: str | None) -> str | None:
    """分类必须来自字典表（active），违例 400；空值放行（未分类）。"""
    if not category:
        return None
    ok = (await db.execute(text("""
        SELECT 1 FROM community.skill_categories WHERE name=:n AND active
    """), {"n": category})).scalar()
    if ok is None:
        raise HTTPException(400, f"分类不存在或已停用：{category}")
    return category


async def skill_accessible(db, skill_id: int, actor: Actor | None) -> dict[str, Any]:
    row = (await db.execute(text("""
        SELECT s.id,s.owner_id,s.slug,s.title,s.description,s.license,s.category,s.origin,
               s.visibility,s.has_scripts,s.file_count,s.size_bytes,s.created_at,s.updated_at,
               u.username,u.display_name
        FROM community.skills s JOIN community.users u ON u.id=s.owner_id
        WHERE s.id=:id
    """), {"id": skill_id})).fetchone()
    if row is None:
        raise HTTPException(404, "技能不存在")
    if row[8] != "public" and (actor is None or actor.id != int(row[1])):
        raise HTTPException(404, "技能不存在")
    return {
        "id": int(row[0]), "owner_id": int(row[1]), "slug": row[2], "title": row[3],
        "description": row[4], "license": row[5], "category": row[6], "origin": row[7],
        "visibility": row[8], "has_scripts": row[9], "file_count": row[10],
        "size_bytes": int(row[11]), "created_at": row[12], "updated_at": row[13],
        "owner": {"username": row[14], "display_name": row[15]},
    }


def _skill_fs_dir(skill_id: int) -> Path:
    return Path(settings.skill_root) / str(skill_id)


def _write_skill_files(skill_id: int, files: list[tuple[str, bytes]]) -> None:
    root = _skill_fs_dir(skill_id)
    root.mkdir(parents=True, exist_ok=True)
    for rel_path, data in files:
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


async def _create_skill_record(db, actor: Actor, manifest: dict[str, Any], category: str | None, idempotency_key: str | None) -> dict[str, Any]:
    existing_slug = (await db.execute(text("""
        SELECT id FROM community.skills WHERE owner_id=:owner AND slug=:slug
    """), {"owner": actor.id, "slug": manifest["slug"]})).scalar()
    if existing_slug is not None:
        raise HTTPException(409, f"已存在同名技能（slug={manifest['slug']}），请先删除或改名")
    row = (await db.execute(text("""
        INSERT INTO community.skills
          (owner_id,slug,title,description,license,category,origin,visibility,
           has_scripts,file_count,size_bytes,idempotency_key)
        VALUES (:owner,:slug,:title,:description,:license,:category,'user','private',
                :has_scripts,:file_count,:size_bytes,:idem)
        RETURNING id,created_at
    """), {
        "owner": actor.id, "slug": manifest["slug"], "title": manifest["title"],
        "description": manifest["description"], "license": manifest["license"],
        "category": category,
        "has_scripts": manifest["has_scripts"], "file_count": manifest["file_count"],
        "size_bytes": manifest["size_bytes"], "idem": idempotency_key,
    })).fetchone()
    skill_id = int(row[0])
    try:
        await asyncio.to_thread(_write_skill_files, skill_id, manifest["files"])
        for rel_path, data in manifest["files"]:
            await db.execute(text("""
                INSERT INTO community.skill_files (skill_id,path,is_text,size_bytes,sha256,is_entry)
                VALUES (:skill,:path,:is_text,:size,:sha,:entry)
            """), {
                "skill": skill_id, "path": rel_path,
                "is_text": _is_text_path(rel_path) and not (b"\x00" in data[:4096]),
                "size": len(data),
                "sha": hashlib.sha256(data).hexdigest(),
                "entry": rel_path == "SKILL.md",
            })
        await db.commit()
    except Exception:
        await db.rollback()
        await asyncio.to_thread(shutil.rmtree, _skill_fs_dir(skill_id), True)
        raise
    return await skill_accessible(db, skill_id, actor)


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
    page: int = Query(1, ge=1, le=500),
    page_size: int = Query(30, ge=1, le=100),
    actor: Actor | None = Depends(public_or_actor),
    db=Depends(get_db),
):
    if scope == "mine":
        if actor is None:
            raise HTTPException(401, "列出自己的技能需要登录或 API Token")
        owner_id = actor.id
    else:
        owner_id = None

    conditions = ["s.visibility='public'"] if owner_id is None else ["s.owner_id=:owner"]
    params: dict[str, Any] = {"limit": page_size, "offset": (page - 1) * page_size}
    if owner_id is not None:
        params["owner"] = owner_id
    if q.strip():
        conditions.append("(s.slug ILIKE :q OR s.title ILIKE :q OR s.description ILIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if category.strip():
        conditions.append("s.category=:category")
        params["category"] = category.strip()
    where = " AND ".join(conditions)

    total = (await db.execute(text(f"""
        SELECT count(*) FROM community.skills s WHERE {where}
    """), params)).scalar() or 0
    rows = (await db.execute(text(f"""
        SELECT s.id,s.slug,s.title,s.description,s.category,s.origin,s.visibility,
               s.has_scripts,s.file_count,s.size_bytes,s.updated_at,
               u.username,u.display_name
        FROM community.skills s JOIN community.users u ON u.id=s.owner_id
        WHERE {where}
        ORDER BY s.updated_at DESC, s.id DESC
        LIMIT :limit OFFSET :offset
    """), params)).mappings().all()
    return {
        "total": int(total), "page": page, "page_size": page_size,
        "items": [
            {
                "id": row["id"], "slug": row["slug"], "title": row["title"],
                "description": row["description"], "category": row["category"],
                "origin": row["origin"], "visibility": row["visibility"],
                "has_scripts": row["has_scripts"], "file_count": row["file_count"],
                "size_bytes": int(row["size_bytes"]), "updated_at": row["updated_at"],
                "owner": {"username": row["username"], "display_name": row["display_name"]},
            }
            for row in rows
        ],
    }


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
    manifest = await skill_accessible(db, skill_id, actor)
    files = (await db.execute(text("""
        SELECT path,is_text,size_bytes,sha256,is_entry
        FROM community.skill_files WHERE skill_id=:id ORDER BY is_entry DESC, path
    """), {"id": skill_id})).mappings().all()
    entry_text: str | None = None
    if any(f["is_entry"] for f in files):
        entry_path = _skill_fs_dir(skill_id) / "SKILL.md"
        if entry_path.is_file():
            entry_text = entry_path.read_text(encoding="utf-8", errors="replace")
    manifest["files"] = [dict(f) for f in files]
    manifest["skill_md"] = entry_text
    if manifest["has_scripts"]:
        manifest["script_warning"] = (
            "该技能包含脚本文件。平台仅做语法级检查，不保证安全；"
            "执行前请人工审阅全部脚本内容。"
        )
    return manifest


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
    await skill_accessible(db, skill_id, actor)
    row = (await db.execute(text("""
        SELECT is_text,size_bytes FROM community.skill_files
        WHERE skill_id=:id AND path=:path
    """), {"id": skill_id, "path": file_path})).fetchone()
    if row is None:
        raise HTTPException(404, "文件不存在")
    if not row[0]:
        raise HTTPException(404, "二进制文件请通过 archive 端点获取 zip")
    target = _skill_fs_dir(skill_id) / file_path
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return {"path": file_path, "size_bytes": int(row[1]), "content": target.read_text(encoding="utf-8", errors="replace")}


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
    manifest = await skill_accessible(db, skill_id, actor)
    rows = (await db.execute(text("""
        SELECT path FROM community.skill_files WHERE skill_id=:id ORDER BY path
    """), {"id": skill_id})).fetchall()

    def build_zip() -> bytes:
        buffer = io.BytesIO()
        root = _skill_fs_dir(skill_id)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for (rel_path,) in rows:
                archive.write(root / rel_path, rel_path)
        return buffer.getvalue()

    payload = await asyncio.to_thread(build_zip)
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
    raw = await file.read(settings.skill_zip_max_bytes + 1)
    if len(raw) > settings.skill_zip_max_bytes:
        raise HTTPException(400, f"压缩包超过 {settings.skill_zip_max_bytes // (1024 * 1024)}MB 上限")
    manifest = await asyncio.to_thread(extract_skill_zip, raw)
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
    require_scope(actor, "skill:write")
    await enforce("skill-write-hour", str(actor.id), settings.api_skill_write_limit_per_hour, 3600)

    # 规范：发布默认私有；公开态仅后台管理动作设置，创建时不存在公开路径
    category = await validate_category(db, category)

    idempotency_key = request_idempotency_key
    if actor.auth_kind == "agent" and not idempotency_key:
        raise HTTPException(400, "使用 API Token 提交必须提供 Idempotency-Key")
    if idempotency_key and len(idempotency_key) > 200:
        raise HTTPException(400, "Idempotency-Key 不能超过 200 个字符")
    if idempotency_key:
        existing = (await db.execute(text("""
            SELECT id FROM community.skills
            WHERE owner_id=:user_id AND idempotency_key=:key
        """), {"user_id": actor.id, "key": idempotency_key})).scalar()
        if existing is not None:
            return await skill_accessible(db, int(existing), actor)

    raw = await file.read(settings.skill_zip_max_bytes + 1)
    if len(raw) > settings.skill_zip_max_bytes:
        raise HTTPException(400, f"压缩包超过 {settings.skill_zip_max_bytes // (1024 * 1024)}MB 上限")
    manifest = await asyncio.to_thread(extract_skill_zip, raw)
    created = await _create_skill_record(db, actor, manifest, category, idempotency_key)
    created["warnings"] = manifest["warnings"]
    return created


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
    current = await skill_accessible(db, skill_id, actor)
    if current["owner_id"] != actor.id:
        raise HTTPException(403, "只能编辑自己创建的技能")
    title = body.get("title")
    description = body.get("description")
    if title is None and description is None:
        raise HTTPException(400, "没有可更新的字段")
    await db.execute(text("""
        UPDATE community.skills SET
          title=coalesce(:title,title),
          description=coalesce(:description,description),
          updated_at=now()
        WHERE id=:id
    """), {
        "id": skill_id,
        "title": str(title)[:120] if title is not None else None,
        "description": str(description)[:500] if description is not None else None,
    })
    await db.commit()
    return await skill_accessible(db, skill_id, actor)


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
    current = await skill_accessible(db, skill_id, actor)
    if current["owner_id"] != actor.id:
        raise HTTPException(403, "只能删除自己创建的技能")
    await db.execute(text("DELETE FROM community.skills WHERE id=:id"), {"id": skill_id})
    await db.commit()
    await asyncio.to_thread(shutil.rmtree, _skill_fs_dir(skill_id), True)
