"""Runtime configuration. Production values are provided by systemd."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    public_base_url: str = "https://huagongshe.com"
    redis_url: str = "redis://127.0.0.1:6379/1"
    cache_ttl: int = 600
    api_title: str = "化工社AIchem API"
    api_version: str = "1.0.0"
    cors_origins: list[str] = ["https://huagongshe.com", "https://www.huagongshe.com"]
    session_cookie: str = "hgs_session"
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
    worker_max_body_bytes: int = 10 * 1024 * 1024
    worker_signature_skew_seconds: int = 300
    worker_job_lease_seconds: int = 180

    model_config = SettingsConfigDict(env_prefix="HGS_", env_file=".env", extra="ignore")


settings = Settings()
