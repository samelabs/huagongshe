"""Pydantic 请求模型 — 自各路由文件集中, 逻辑零改动(批次2)。"""
from pydantic import BaseModel, Field
from typing import Any

class LeaseBody(BaseModel):
    max_jobs: int = Field(default=2, ge=1, le=20)
    capabilities: list[str] = Field(default_factory=lambda: ["pubchem"], max_length=20)



class LeaseProof(BaseModel):
    job_id: int = Field(gt=0)
    lease_token: str = Field(min_length=32, max_length=256)



class CasLeaseBody(BaseModel):
    max_jobs: int = Field(default=2, ge=1, le=20)
    capabilities: list[str] = Field(default_factory=lambda: ["cas"], max_length=20)



class CasResultBody(BaseModel):
    # 2026-08-30 CB链重构(准线§3): error 载荷 = 拿不到状态, 只刷 last_status+
    # fetched_at, 不写 entry/供应商/name_index, 不冒充 not_found。
    status: str = Field(pattern="^(ok|not_found|error)$")
    entry: dict[str, Any] | None = None
    suppliers: list[dict[str, Any]] = Field(default_factory=list)
    # CB molfile 原文(可选): 详情页有 MOL 外链时 worker 附带; 服务端只补空不覆盖
    mol: str | None = Field(default=None, max_length=1_000_000)
    # CB 条目号(可选, 身份标识): 纯数字字符串, 落主表 chemicals.cb_number
    cb_number: str | None = Field(default=None, pattern=r"^\d{1,16}$")
    # locale(可选, 默认 zh-CN 主行): en 等语言行只写 entry, suppliers 由主行独占
    locale: str = Field(default="zh-CN", pattern="^(zh-CN|en|ja|de|ko)$")  # ru已摘(0831, 与 CB_LOCALES 对齐)



class CompleteBody(LeaseProof):
    result: dict[str, Any]



class ErrorBody(LeaseProof):
    """worker error 报告(数据链收口§3): 没拿到有效回应。

    不写数据层; job 留 error 行, not_before=阶梯档时间, 通道计数+1。
    """
    error_code: str = Field(min_length=1, max_length=100)
    error_detail: str = Field(default="", max_length=2000)


class IdentityCompleteBody(LeaseProof):
    """§3 discovery complete: cid_list = PubChem /cids 原始集合(零裁剪)。

    §3.1: 无数量上限 — ">1 → AMBIGUOUS" 契约不允许语义截断。
    资源边界仍由既有层承担: PubChem response 8MiB cap /
    worker WorkAPI body 9.5MB cap / server worker body cap。
    """
    cid_list: list[int] = Field(default_factory=list)



class CasCompleteBody(LeaseProof):
    result: CasResultBody


