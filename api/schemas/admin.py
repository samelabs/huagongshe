"""Pydantic 请求模型 — 自各路由文件集中, 逻辑零改动(批次2)。"""
from pydantic import BaseModel, Field
from typing import Literal

class UserStatusBody(BaseModel):
    status: Literal["active", "disabled"]



class UserRoleBody(BaseModel):
    role: Literal["member", "admin"]



class ModerationBody(BaseModel):
    status: Literal["visible", "hidden"]


# ---------------------------------------------------------------- workers
# Worker 凭据治理: 签发/停权/scopes 编辑. scopes 是一等自由数组(受已知任务族校验),
# 未来内部负载 worker 化时此处零改动 — 认证协议(HMAC/租约)与任务族解耦.

WORKER_SCOPES = ("pubchem", "cas")



class WorkerCreateBody(BaseModel):
    worker_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=10)
    max_lease_jobs: int = Field(default=4, ge=1, le=20)



class WorkerPatchBody(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    scopes: list[str] | None = Field(default=None, min_length=1, max_length=10)
    max_lease_jobs: int | None = Field(default=None, ge=1, le=20)
    enabled: bool | None = None



class SkillVisibilityBody(BaseModel):
    visibility: Literal["private", "public"]
    note: str | None = None



class CategoryBody(BaseModel):
    name: str
    abbr: str
    color: str
    sort_order: int = 100
    active: bool = True


