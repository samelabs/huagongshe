"""Skill read kernels(G2.6B)。

本轮只含 Skill List read kernel(G1 kernel: skill.query.list):
- public/mine 共用同一 query implementation, 仅 selector predicate 不同
  (public → visibility='public'; mine → owner_id=:owner)
- transport-neutral: 零 Web 框架与传输层依赖(HTTP 异常类型/请求响应
  对象/上传文件/MCP 工具报错), 只含 query/business transformation
- PURE_READ: 无 cache write / last_access / filesystem read / enqueue /
  rate limit
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text

from ..core.config import settings


async def list_skills(
    db,
    *,
    scope: str,
    owner_id: int | None,
    q: str | None,
    category: str | None,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """skill.query.list kernel —— 自 api/skills.py::list_skills 下沉(G2.6B)。

    caller contract(adapter 已验证):
    - scope = "public" | "mine"(validation/422/工具报错 留 adapter)
    - scope=mine 时 owner_id 必为 actor id(登录墙留 adapter)
    - q/category/limit 越界处理留 adapter(HTTP 422 / MCP truncate+clamp)
    """
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


class SkillNotAccessibleError(Exception):
    """skill 不存在或当前 viewer 不可读的 neutral 语义错误。

    detail 固定基线原文 "技能不存在"(anti-enumeration invariant:
    missing 与 private-unreadable 不可区分)。不含 status/headers,
    HTTP 边界映射 404、MCP 边界映射工具报错。
    """


def skill_fs_dir(skill_id: int) -> Path:
    """skill_id → canonical skill filesystem directory(G2.6C 自
    api/skills.py::_skill_fs_dir 原样迁移; path formula/root 不变)。"""
    return Path(settings.skill_root) / str(skill_id)


async def load_accessible_skill(
    db,
    skill_id: int,
    *,
    actor_id: int | None,
) -> dict[str, Any]:
    """单行 skill access kernel —— 自 api/skills.py::skill_accessible
    逐字迁移(G2.6C)。

    invariant(与原 helper 零差异):
    - missing → SkillNotAccessibleError("技能不存在")
    - visibility != 'public' 且 (actor_id is None 或 actor_id != owner_id)
      → 同一 neutral error(anonymous/non-owner/admin-non-owner 同语义,
      admin role 不参与判定)
    - public / private owner → 16 字段 dict(含 owner 子对象)
    """
    row = (await db.execute(text("""
        SELECT s.id,s.owner_id,s.slug,s.title,s.description,s.license,s.category,s.origin,
               s.visibility,s.has_scripts,s.file_count,s.size_bytes,s.created_at,s.updated_at,
               u.username,u.display_name
        FROM community.skills s JOIN community.users u ON u.id=s.owner_id
        WHERE s.id=:id
    """), {"id": skill_id})).fetchone()
    if row is None:
        raise SkillNotAccessibleError("技能不存在")
    if row[8] != "public" and (actor_id is None or actor_id != int(row[1])):
        raise SkillNotAccessibleError("技能不存在")
    return {
        "id": int(row[0]), "owner_id": int(row[1]), "slug": row[2], "title": row[3],
        "description": row[4], "license": row[5], "category": row[6], "origin": row[7],
        "visibility": row[8], "has_scripts": row[9], "file_count": row[10],
        "size_bytes": int(row[11]), "created_at": row[12], "updated_at": row[13],
        "owner": {"username": row[14], "display_name": row[15]},
    }


async def get_skill_detail(
    db,
    skill_id: int,
    *,
    actor_id: int | None,
) -> dict[str, Any]:
    """skill detail orchestration —— 自 api/skills.py::get_skill 下沉
    (G2.6C; HTTP/MCP 共用; slug 解析留 MCP adapter, 不在此层)。

    flow: load_accessible_skill → skill_files 查询 → SKILL.md 条件读取
    (missing → skill_md=None; decode errors="replace") → 组装。
    """
    manifest = await load_accessible_skill(db, skill_id, actor_id=actor_id)
    files = (await db.execute(text("""
        SELECT path,is_text,size_bytes,sha256,is_entry
        FROM community.skill_files WHERE skill_id=:id ORDER BY is_entry DESC, path
    """), {"id": skill_id})).mappings().all()
    entry_text: str | None = None
    if any(f["is_entry"] for f in files):
        entry_path = skill_fs_dir(skill_id) / "SKILL.md"
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
