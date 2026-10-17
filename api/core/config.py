"""Runtime configuration loaded from environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _version_from_repo() -> str:
    """产品版本唯一来源 = 仓库根 VERSION 文件(与 MCP serverInfo 同源)。

    版本号只有一个来源: 硬编码 "1.0.0"(所谓 "HTTP API contract
    version")会让 /api/health 与 app.version 和 MCP serverInfo(VERSION)
    漂移, 已删除。读取方式与 api/mcp_server.py 的 _release_version 一致。
    """
    version_file = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError as exc:  # pragma: no cover - 文件缺失即发布产物不完整
        raise RuntimeError("仓库根 VERSION 文件缺失: api_version 无权威来源") from exc
    if not value:
        raise RuntimeError("仓库根 VERSION 文件为空: api_version 无权威来源")
    return value


class Settings(BaseSettings):
    database_url: str
    public_base_url: str = "https://huagongshe.com"
    redis_url: str = "redis://127.0.0.1:6379/1"
    cache_ttl: int = 600
    api_title: str = "化工社AIchem API"
    api_version: str = Field(default_factory=_version_from_repo)
    cors_origins: list[str] = ["https://huagongshe.com", "https://www.huagongshe.com"]
    session_cookie: str = "hgs_session"
    # 会话 cookie 的 Secure 标记。线上恒为 True；本地经局域网 http 访问时设 False，
    # 否则浏览器丢弃 Secure cookie，登录成功却留不住会话。
    session_cookie_secure: bool = True
    session_days: int = 30
    avatar_root: str = "/var/lib/huagongshe/uploads/avatars"
    avatar_max_bytes: int = 5 * 1024 * 1024
    api_reaction_write_limit_per_minute: int = 10
    api_reaction_write_limit_per_day: int = 200
    api_stoich_limit_per_minute: int = 30
    api_avatar_limit_per_hour: int = 5
    skill_root: str = "/var/lib/huagongshe/skills"
    skill_zip_max_bytes: int = 12 * 1024 * 1024
    skill_file_max_bytes: int = 2 * 1024 * 1024
    skill_total_max_bytes: int = 10 * 1024 * 1024
    skill_max_files: int = 128
    api_skill_write_limit_per_hour: int = 20
    api_note_write_limit_per_minute: int = 10
    api_note_max_per_user: int = 5000
    worker_max_body_bytes: int = 10 * 1024 * 1024
    worker_signature_skew_seconds: int = 300
    worker_job_lease_seconds: int = 180

    model_config = SettingsConfigDict(env_prefix="HGS_", env_file=".env", extra="ignore")


settings = Settings()
