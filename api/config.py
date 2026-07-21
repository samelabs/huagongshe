"""Runtime configuration. Production values are provided by systemd."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://127.0.0.1:6379/1"
    cache_ttl: int = 600
    api_title: str = "化工社 API"
    api_version: str = "4.1.0"
    page_size: int = 20
    max_page_size: int = 50
    cors_origins: list[str] = ["https://huagongshe.com", "https://www.huagongshe.com"]
    session_cookie: str = "hgs_session"
    session_days: int = 30
    avatar_root: str = "/var/lib/huagongshe/uploads/avatars"
    avatar_max_bytes: int = 5 * 1024 * 1024
    api_query_limit_per_minute: int = 60
    api_structure_limit_per_minute: int = 20
    api_reaction_write_limit_per_minute: int = 10
    api_reaction_write_limit_per_day: int = 200
    api_avatar_limit_per_hour: int = 5
    worker_max_body_bytes: int = 10 * 1024 * 1024
    worker_signature_skew_seconds: int = 300
    worker_job_lease_seconds: int = 180

    model_config = SettingsConfigDict(env_prefix="HGS_", env_file=".env", extra="ignore")


settings = Settings()
