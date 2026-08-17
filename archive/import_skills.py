"""One-shot import: kdense 158 skills + reaction-publisher → skills registry (DB + FS).

Usage (from project root, as a user with write access to skill_root):
    sudo -u postgres venv/bin/python archive/import_skills.py
Idempotent: re-running replaces content for existing (owner, slug) pairs.
"""

import asyncio
import hashlib
import json
import shutil
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "web/public/kdense-skills.json"
SRC = ROOT / "web/public/kdense-skills"
PUB = ROOT / "web/public/skills/huagongshe-reaction-publisher"
DEST = Path("/var/lib/huagongshe/skills")
OWNER_ID = 5  # samelabs (admin) — platform account

TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".sh", ".js", ".ts", ".json", ".csv", ".tsv",
    ".xsd", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".tex",
    ".rst", ".html", ".css", ".svg", ".env",
}
SCRIPT_EXTENSIONS = {".py", ".sh", ".js", ".ts", ".rb", ".pl"}


def collect(d: Path, exclude_zip: str | None = None) -> list[tuple[str, bytes]]:
    out = []
    for f in sorted(d.rglob("*")):
        if not f.is_file() or (exclude_zip and f.name == exclude_zip):
            continue
        out.append((f.relative_to(d).as_posix(), f.read_bytes()))
    return out


def is_text(rel: str, data: bytes) -> bool:
    if Path(rel).suffix.lower() in TEXT_EXTENSIONS:
        return True
    return b"\x00" not in data[:4096]


def frontmatter(text: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].strip().splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()
    return fm


def build_payload() -> list[dict]:
    rows = json.loads(META.read_text(encoding="utf-8"))
    print(f"[meta] {len(rows)} kdense entries")
    payload = []
    for row in rows:
        d = SRC / row["name"]
        if not d.is_dir():
            print(f"[skip] missing dir {row['name']}")
            continue
        files = collect(d, f"{row['name']}.zip")
        entry = next((data.decode("utf-8", "replace") for rel, data in files if rel == "SKILL.md"), "")
        fm = frontmatter(entry)
        payload.append({
            "slug": row["name"],
            "title": fm.get("title") or row["name"],
            "description": (row.get("description") or fm.get("description") or "")[:500],
            "license": fm.get("license") or row.get("license") or "MIT",
            "category": row.get("category"),
            "origin": "kdense",
            "files": files,
        })

    if PUB.is_dir():
        files = collect(PUB)
        entry = next((data.decode("utf-8", "replace") for rel, data in files if rel == "SKILL.md"), "")
        fm = frontmatter(entry)
        payload.append({
            "slug": "huagongshe-reaction-publisher",
            "title": fm.get("title") or "huagongshe-reaction-publisher",
            "description": (fm.get("description") or "")[:500],
            "license": fm.get("license") or "MIT",
            "category": "化学反应记录",
            "origin": "official",
            "files": files,
        })
        print(f"[pub] reaction-publisher files: {len(files)}")
    else:
        print("[warn] reaction-publisher dir missing, skipped")

    print(f"[payload] total skills: {len(payload)}")
    return payload


async def main() -> None:
    payload = build_payload()
    conn = await asyncpg.connect(host="/var/run/postgresql", database="huagongshe")
    inserted = updated = 0
    try:
        await conn.execute("BEGIN")
        for item in payload:
            size = sum(len(d) for _, d in item["files"])
            has_scripts = any(Path(r).suffix.lower() in SCRIPT_EXTENSIONS for r, _ in item["files"])
            exist = await conn.fetchval(
                "SELECT id FROM community.skills WHERE owner_id=$1 AND slug=$2",
                OWNER_ID, item["slug"],
            )
            if exist is not None:
                skill_id = exist
                await conn.execute(
                    """UPDATE community.skills SET title=$1, description=$2, license=$3,
                         category=$4, origin=$5, has_scripts=$6, file_count=$7, size_bytes=$8,
                         updated_at=now()
                       WHERE id=$9""",
                    item["title"], item["description"], item["license"], item["category"],
                    item["origin"], has_scripts, len(item["files"]), size, skill_id,
                )
                await conn.execute("DELETE FROM community.skill_files WHERE skill_id=$1", skill_id)
                shutil.rmtree(DEST / str(skill_id), ignore_errors=True)
                updated += 1
            else:
                skill_id = await conn.fetchval(
                    """INSERT INTO community.skills
                         (owner_id, slug, title, description, license, category, origin,
                          visibility, has_scripts, file_count, size_bytes)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,'public',$8,$9,$10)
                       RETURNING id""",
                    OWNER_ID, item["slug"], item["title"], item["description"], item["license"],
                    item["category"], item["origin"], has_scripts, len(item["files"]), size,
                )
                inserted += 1

            root = DEST / str(skill_id)
            root.mkdir(parents=True, exist_ok=True)
            for rel, data in item["files"]:
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                await conn.execute(
                    """INSERT INTO community.skill_files
                         (skill_id, path, is_text, size_bytes, sha256, is_entry)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    skill_id, rel, is_text(rel, data), len(data),
                    hashlib.sha256(data).hexdigest(), rel == "SKILL.md",
                )
        await conn.execute("COMMIT")
        print(f"[done] inserted={inserted} updated={updated} total={len(payload)}")
        n, nf = await conn.fetchrow("SELECT count(*), sum(file_count) FROM community.skills")
        print(f"[db] skills rows: {n}, file rows: {nf}")
    except Exception:
        await conn.execute("ROLLBACK")
        raise
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
