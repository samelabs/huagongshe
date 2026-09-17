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

from typing import Any

from sqlalchemy import text


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
