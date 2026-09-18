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

import asyncio
import hashlib
import io
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ..core.config import settings
from ..core.rate_limit import enforce

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


# ---------------------------------------------------------------------------
# G3.1D — neutral semantic errors(create/archive 域)
# ---------------------------------------------------------------------------

class SkillArchiveValidationError(Exception):
    """技能 zip 校验失败的 neutral 语义错误(G3.1D; 原 18 类 HTTP 400 全集)。

    kind ∈ {ARCHIVE_TOO_LARGE, INVALID_ARCHIVE, UNSAFE_PATH, DECOMPRESSION,
             EMPTY_ARCHIVE, ARCHIVE_LIMIT, MANIFEST_INVALID};
    只携带 kind + detail(原文), 不含传输层 status/headers。
    """

    ARCHIVE_TOO_LARGE = "archive_too_large"
    INVALID_ARCHIVE = "invalid_archive"
    UNSAFE_PATH = "unsafe_path"
    DECOMPRESSION = "decompression"
    EMPTY_ARCHIVE = "empty_archive"
    ARCHIVE_LIMIT = "archive_limit"
    MANIFEST_INVALID = "manifest_invalid"

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


class SkillCategoryError(Exception):
    """分类不存在或已停用(原 HTTP 400 同文案)。"""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class SkillSlugConflictError(Exception):
    """owner+slug 撞名(原 HTTP 409 同文案)。"""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class MissingSkillIdempotencyKeyError(Exception):
    """agent 提交缺 Idempotency-Key(原 HTTP 400 同文案)。"""

    def __init__(self) -> None:
        super().__init__("使用 API Token 提交必须提供 Idempotency-Key")
        self.detail = "使用 API Token 提交必须提供 Idempotency-Key"


class SkillIdempotencyKeyTooLongError(Exception):
    """Idempotency-Key 超 200 字符(原 HTTP 400 同文案)。"""

    def __init__(self) -> None:
        super().__init__("Idempotency-Key 不能超过 200 个字符")
        self.detail = "Idempotency-Key 不能超过 200 个字符"


def _is_text_path(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_EXTENSIONS


def _has_binary_content(data: bytes) -> bool:
    """内容级二进制嗅探(与 DB CHECK 同口径: 只看前 4096 字节是否含 NUL)。"""
    return b"\x00" in data[:4096]


def _skill_file_is_text(rel_path: str, data: bytes) -> bool:
    """community.skill_files.is_text 的唯一判定点。

    与 DB CHECK skill_files_text_only (is_text OR path LIKE 'assets/%' OR
    'examples/%') 同口径:
      * 内容含 NUL → 二进制 → is_text=false(此时路径必须在 assets/ 或 examples/,
        由 extract_skill_zip 的内容级校验保证);
      * 内容为文本 → assets/examples 之外的路径必须 is_text=true(.gitignore、
        LICENSE、Makefile 等无扩展名文本文件不能被误判为二进制);
      * assets/examples 内保留扩展名保守标记(二进制资产 → false)。
    """
    if _has_binary_content(data):
        return False
    return _is_text_path(rel_path) or not rel_path.startswith(BINARY_DIRS)


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
    """唯一 canonical 技能 zip 校验/安全 kernel(G3.1D 自 api/skills.py 迁移)。

    纯内存校验; 原 18 类传输层 400 → SkillArchiveValidationError(kind),
    detail 原文逐字保持。
    """
    if len(raw) > settings.skill_zip_max_bytes:
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.ARCHIVE_TOO_LARGE,
            f"压缩包超过 {settings.skill_zip_max_bytes // (1024 * 1024)}MB 上限")

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.INVALID_ARCHIVE, "不是有效的 zip 文件")

    entries: list[tuple[str, bytes]] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name.startswith(IGNORED_PREFIXES) or Path(name).name in IGNORED_NAMES:
            continue
        if name.startswith("/") or "\\" in name or ".." in Path(name).parts:
            raise SkillArchiveValidationError(
                SkillArchiveValidationError.UNSAFE_PATH, f"非法路径：{name}")
        if not SAFE_PATH_RE.match(name) or len(name) > MAX_PATH_LEN:
            raise SkillArchiveValidationError(
                SkillArchiveValidationError.UNSAFE_PATH, f"非法路径：{name}")
        if len(Path(name).parts) > MAX_DEPTH:
            raise SkillArchiveValidationError(
                SkillArchiveValidationError.UNSAFE_PATH, f"目录层级过深：{name}")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise SkillArchiveValidationError(
                SkillArchiveValidationError.UNSAFE_PATH, f"不允许符号链接：{name}")
        raw_bytes = archive.read(info)
        if info.compress_size and len(raw_bytes) > info.compress_size * MAX_COMPRESSION_RATIO:
            raise SkillArchiveValidationError(
                SkillArchiveValidationError.DECOMPRESSION,
                f"压缩比异常（疑似 zip 炸弹）：{name}")
        entries.append((name, raw_bytes))

    if not entries:
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.EMPTY_ARCHIVE, "压缩包内没有文件")
    if len(entries) > settings.skill_max_files:
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.ARCHIVE_LIMIT,
            f"文件数超过 {settings.skill_max_files} 上限")
    total = sum(len(data) for _, data in entries)
    if total > settings.skill_total_max_bytes:
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.ARCHIVE_LIMIT,
            f"解包后总量超过 {settings.skill_total_max_bytes // (1024 * 1024)}MB 上限")
    for name, data in entries:
        if len(data) > settings.skill_file_max_bytes:
            raise SkillArchiveValidationError(
                SkillArchiveValidationError.ARCHIVE_LIMIT,
                f"单文件超过 {settings.skill_file_max_bytes // (1024 * 1024)}MB 上限：{name}")

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
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.MANIFEST_INVALID,
            "压缩包根目录必须包含 SKILL.md")

    # 二进制只允许 assets/、examples/（与 DB CHECK 一致；kdense 实证二进制在 examples/）
    # 判定按内容(NUL 嗅探),不按扩展名: 扩展名不再能豁免放行目录(否则 .csv/.json 内嵌
    # NUL 会绕过此校验并在 INSERT 时触发 skill_files_text_only → 500)。
    for name, data in entries:
        if _has_binary_content(data) and not name.startswith(BINARY_DIRS):
            raise SkillArchiveValidationError(
                SkillArchiveValidationError.MANIFEST_INVALID,
                f"二进制文件只能放在 assets/ 或 examples/ 目录：{name}")

    entry_text = next(data.decode("utf-8", errors="replace") for name, data in entries if name == "SKILL.md")
    frontmatter = parse_frontmatter(entry_text)
    name = frontmatter.get("name", "").strip()
    description = frontmatter.get("description", "").strip()
    if not name or not description:
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.MANIFEST_INVALID,
            "SKILL.md frontmatter 必须包含 name 和 description")
    slug = _slugify(name)
    if not SLUG_RE.match(slug):
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.MANIFEST_INVALID,
            f"技能名无法转为合法 slug：{name!r}")

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
    """分类必须来自字典表（active），违例 neutral error；空值放行（未分类）。"""
    if not category:
        return None
    ok = (await db.execute(text("""
        SELECT 1 FROM community.skill_categories WHERE name=:n AND active
    """), {"n": category})).scalar()
    if ok is None:
        raise SkillCategoryError(f"分类不存在或已停用：{category}")
    return category


def _write_skill_files(skill_id: int, files: list[tuple[str, bytes]]) -> None:
    root = skill_fs_dir(skill_id)
    root.mkdir(parents=True, exist_ok=True)
    for rel_path, data in files:
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


async def _create_skill_record(
    db, actor_id: int, manifest: dict[str, Any],
    category: str | None, idempotency_key: str | None,
) -> dict[str, Any]:
    """neutral lower-level create transaction helper(G3.1D 迁移)。

    slug 撞名预检(409 原文案) → INSERT skills → fs write(to_thread)
    → INSERT skill_files → commit; 失败: rollback + rmtree 补偿 + re-raise。
    尾部 detail readback 直调 neutral load_accessible_skill。
    """
    existing_slug = (await db.execute(text("""
        SELECT id FROM community.skills WHERE owner_id=:owner AND slug=:slug
    """), {"owner": actor_id, "slug": manifest["slug"]})).scalar()
    if existing_slug is not None:
        raise SkillSlugConflictError(
            f"已存在同名技能（slug={manifest['slug']}），请先删除或改名")
    row = (await db.execute(text("""
        INSERT INTO community.skills
          (owner_id,slug,title,description,license,category,origin,visibility,
           has_scripts,file_count,size_bytes,idempotency_key)
        VALUES (:owner,:slug,:title,:description,:license,:category,'user','private',
                :has_scripts,:file_count,:size_bytes,:idem)
        RETURNING id,created_at
    """), {
        "owner": actor_id, "slug": manifest["slug"], "title": manifest["title"],
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
                "is_text": _skill_file_is_text(rel_path, data),
                "size": len(data),
                "sha": hashlib.sha256(data).hexdigest(),
                "entry": rel_path == "SKILL.md",
            })
        await db.commit()
    except Exception:
        await db.rollback()
        await asyncio.to_thread(shutil.rmtree, skill_fs_dir(skill_id), True)
        raise
    return await load_accessible_skill(db, skill_id, actor_id=actor_id)


async def create_skill(
    db,
    *,
    actor_id: int,
    auth_kind: str,
    category: str | None,
    idempotency_key: str | None,
    archive_loader: Callable[[int], Awaitable[bytes]],
) -> dict[str, Any]:
    """shared skill create orchestration(G3.1D; HTTP/MCP 共用)。

    payload loader 为 transport-neutral contract: await loader(limit) -> bytes;
    service 只决定读取时机与上限。硬冻结顺序:
    skill-write-hour rate → validate_category → agent key 规则 → key 长度
    → 幂等预检 → loader(max+1) → size → to_thread(extract) → 事务
    → IntegrityError 竞态恢复 → warnings append → canonical detail。
    """
    await enforce("skill-write-hour", str(actor_id), settings.api_skill_write_limit_per_hour, 3600)
    category = await validate_category(db, category)
    if auth_kind == "agent" and not idempotency_key:
        raise MissingSkillIdempotencyKeyError()
    if idempotency_key and len(idempotency_key) > 200:
        raise SkillIdempotencyKeyTooLongError()
    if idempotency_key:
        existing = (await db.execute(text("""
            SELECT id FROM community.skills
            WHERE owner_id=:user_id AND idempotency_key=:key
        """), {"user_id": actor_id, "key": idempotency_key})).scalar()
        if existing is not None:
            return await load_accessible_skill(db, int(existing), actor_id=actor_id)

    raw = await archive_loader(settings.skill_zip_max_bytes + 1)
    if len(raw) > settings.skill_zip_max_bytes:
        raise SkillArchiveValidationError(
            SkillArchiveValidationError.ARCHIVE_TOO_LARGE,
            f"压缩包超过 {settings.skill_zip_max_bytes // (1024 * 1024)}MB 上限")
    manifest = await asyncio.to_thread(extract_skill_zip, raw)
    try:
        created = await _create_skill_record(db, actor_id, manifest, category, idempotency_key)
    except IntegrityError:
        # concurrent race: 第二个请求越过 existing_slug pre-check 后被
        # (owner_id, slug) UNIQUE 拦截 — 回滚后按序回读:
        # ① idempotency_key 命中 → 同一请求 retry, 返回第一次的 skill;
        # ② owner+slug 命中 → 不同请求撞同名, 保持顺序请求的 409 语义;
        # ③ 其余(不相关 IntegrityError)不吞, 原异常 raise。
        await db.rollback()
        if idempotency_key:
            existing = (await db.execute(text("""
                SELECT id FROM community.skills
                WHERE owner_id=:user_id AND idempotency_key=:key
            """), {"user_id": actor_id, "key": idempotency_key})).scalar()
            if existing is not None:
                return await load_accessible_skill(db, int(existing), actor_id=actor_id)
        conflict = (await db.execute(text("""
            SELECT id FROM community.skills
            WHERE owner_id=:user_id AND slug=:slug
        """), {"user_id": actor_id, "slug": manifest["slug"]})).scalar()
        if conflict is not None:
            raise SkillSlugConflictError(
                f"已存在同名技能（slug={manifest['slug']}），请先删除或改名")
        raise
    created["warnings"] = manifest["warnings"]
    return created
