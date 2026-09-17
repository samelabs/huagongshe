"""Governance model (G1 final) — 按 G1A 冻结结论建立的治理词汇表。

纯 stdlib: 禁止导入 fastapi/mcp/sqlalchemy、Request/Response/UploadFile。
描述性账本, 不是运行时引擎: 不扫描/生成/修改 route, 不控制 runtime
authorization, 不做 startup 校验。治理失败只能导致 test/CI failure。

字段各自承担一个维度:
- Family/Scenario: 业务能力族与场景(selector 表达参数变体)
- Entrypoint: 物理/工具入口
- Contract: scenario 级契约(consumer 投影 + 兼容义务 + operation identity)
- AuthPolicy: 稳定可复用的身份/授权类别(无全序, 只做语义匹配)
- required_scope: 业务 scope(reaction:write / skill:write), 独立维度
- KernelLink: 共享实现关系(仅描述)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Transport(str, Enum):
    HTTP = "HTTP"
    MCP = "MCP"
    WORKAPI = "WORKAPI"


class Consumer(str, Enum):
    """契约投影面: 注册面即投影。不承载兼容义务(那是 Compatibility 的维度)。"""

    WEB = "WEB"                  # Web consumer binding(前端实际调用)
    AGENT_HTTP = "AGENT_HTTP"    # agent-guide 投影(curated HTTP agent projection)
    AGENT_MCP = "AGENT_MCP"      # MCP 投影(curated MCP projection)
    WORKER = "WORKER"            # WorkAPI 投影(trusted worker projection)
    ADMIN = "ADMIN"              # 管理面
    OPS = "OPS"                  # 运维面
    DISCOVERY = "DISCOVERY"      # llms.txt / sitemap 公布投影


class Effect(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"
    PRIVILEGED = "PRIVILEGED"


class Compatibility(str, Enum):
    """兼容义务 — 单一维度: 是否承担稳定外部兼容义务。

    不表达投影位置(那是 Consumer 的维度); Consumer 不得自动推导本字段。
    STABLE_EXTERNAL = 已通过公开契约(agent-guide operation / MCP tool /
    agent-guide 自身)对外的稳定承诺, 漂移须显式收口。
    NONE = 无对外兼容义务(trusted internal protocol / Web-only / OPS 等)。
    """

    NONE = "NONE"
    STABLE_EXTERNAL = "STABLE_EXTERNAL"


class AuthPolicy(str, Enum):
    """稳定、可复用的身份/授权类别。

    只表达类别, 类别之间没有全序; guide 对账用显式语义匹配,
    不用等级比较。参数条件差异用 scenario selector + 各自 auth 表达。
    未使用 policy 必须删除(测试锁定 unused=0)。
    """

    ANONYMOUS = "ANONYMOUS"                    # 不读取任何身份
    PUBLIC_OR_ACTOR = "PUBLIC_OR_ACTOR"        # 匿名可读, actor 可增强结果
    ACTOR = "ACTOR"                            # 需任意已解析 actor(session 或 agent token)
    SESSION = "SESSION"                        # 需交互式网页会话(agent 403)
    ADMIN_SESSION = "ADMIN_SESSION"            # SESSION + role=='admin'
    WORKER_HMAC = "WORKER_HMAC"                # worker HMAC 签名(具体 scope 见 scenario)


@dataclass(frozen=True)
class Contract:
    """scenario 级契约: consumer 投影 + 兼容义务 + operation identity。"""

    consumers: frozenset[Consumer]
    compatibility: Compatibility = Compatibility.NONE
    operation_id: str | None = None   # 稳定 operation identity(投影面才有)


@dataclass(frozen=True)
class Entrypoint:
    """一个物理/工具入口; 同一物理 route 可承载多个 selector scenario。"""

    transport: Transport
    # HTTP: "METHOD /full/path"; MCP: tool name; WorkAPI: "METHOD /workapi/..."
    name: str
    # selector: 参数条件(纯治理描述, 不进 runtime router), 如 "mode=exact"
    selector: str | None = None


@dataclass(frozen=True)
class Scenario:
    """family 内一个业务场景: 授权 + scope + 契约 + 入口绑定。"""

    id: str                          # family 内唯一, 如 "svg" / "png" / "exact"
    auth: AuthPolicy
    required_scope: tuple[str, ...] = ()   # 业务 scope, 如 ("reaction:write",)
    entrypoints: tuple[Entrypoint, ...] = ()
    contract: Contract | None = None
    note: str = ""                   # 事实注记


@dataclass(frozen=True)
class KernelLink:
    """共享实现关系(target shared-implementation relationship)。

    仅是 G1A 冻结的目标关系 annotation: 不导入生产代码验证、不构成
    runtime/code-sharing proof —— kernel 声明与实际实现可能暂时不一致
    (如 MCP 侧 SQL 复制, D008), 复用事实只能由代码审查/行为测试建立。
    """

    kernel_id: str                   # 如 "render.kernel.molecule"
    members: tuple[str, ...]         # 参与方 scenario 全名 "family/scenario"


@dataclass(frozen=True)
class Family:
    """业务能力族: 多 scenario, 共享 kernel 关系显式登记。"""

    id: str                          # 如 "molecule.rendering"
    effect: Effect
    scenarios: tuple[Scenario, ...] = field(default=())
    kernels: tuple[KernelLink, ...] = ()

    def scenario(self, sid: str) -> Scenario:
        for s in self.scenarios:
            if s.id == sid:
                return s
        raise KeyError(sid)
