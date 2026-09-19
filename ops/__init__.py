"""Ops 编排包(部署单一 owner)。

约定: 本包只做运维编排 —— 不 import `api/*` / `worker/*` 应用代码,
不定义业务语义, 不跑 migration。Application 只提供既有 surface
(readiness = `/api/health`, HTTP/MCP 面由 nginx 透传)。
"""
