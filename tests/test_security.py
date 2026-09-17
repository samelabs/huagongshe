from __future__ import annotations

import asyncio
import inspect
import os
import unittest

from fastapi import HTTPException

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api import admin, social, users
from api.core.security import Actor, current_session


class SessionBoundaryTests(unittest.TestCase):
    def test_api_token_cannot_be_used_as_a_web_session(self) -> None:
        actor = Actor(1, "user", "User", "user@example.test", "member", None, "agent")
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(current_session(actor))
        self.assertEqual(raised.exception.status_code, 403)

    def test_account_mutations_require_web_session(self) -> None:
        for endpoint in (
            users.update_profile, users.change_password, users.upload_avatar,
            users.list_tokens, users.create_token, users.revoke_token,
        ):
            self.assertIn("Depends(current_session)", inspect.getsource(endpoint))

    def test_community_and_admin_mutations_require_web_session(self) -> None:
        for endpoint in (
            social.follow_user, social.unfollow_user,
            social.follow_chemical, social.unfollow_chemical,
            social.follow_reaction, social.unfollow_reaction,
            social.read_notifications, admin.admin,
        ):
            self.assertIn("Depends(current_session)", inspect.getsource(endpoint))

    def test_public_reads_use_public_or_actor(self) -> None:
        """H1 方案 D: 公开读端点一律 public_or_actor —— 匿名公网与已鉴权
        actor 都可读(公开数据是产品 use-case policy, 与 transport 无关);
        loopback 不再是 authorization evidence。端点自身可叠加业务墙
        (结构检索 mode!=exact 需 actor, 见 test_search)。"""
        import api.routes as routes
        for endpoint in (
            routes.search, routes.chemical_detail, routes.chemical_externals,
            routes.chemical_synonyms, routes.chemical_reactions,
            routes.reaction_detail, routes.datasets,
        ):
            self.assertIn("Depends(public_or_actor)", inspect.getsource(endpoint))

    def test_no_loopback_authorization_in_normal_api(self) -> None:
        """H1: 普通 /api authorization 与 refresh policy 不得依赖
        loopback / client.host。is_loopback_host 仅存于 rate_limit 定义处,
        无任何 authorization 调用方。断言只查函数体 AST/docstring 之外的
        代码, 不对整模块 assertNotIn(docstring 合法出现说明文字)。"""
        import re
        from api.core import security, rate_limit
        from api.services import enrichment as enrichment_service

        def code_only(func) -> str:
            """返回函数源码中剥离全部三引号字符串(docstring 含说明文字,
            合法出现 request/client.host 字样不构成依赖)后的纯代码段。"""
            return re.sub(r'""".*?"""', "", inspect.getsource(func), flags=re.S)

        self.assertNotIn("is_loopback_host", code_only(security.public_or_actor))
        self.assertNotIn("client.host", code_only(security.public_or_actor))
        self.assertNotIn("Request", code_only(security.public_or_actor).replace("REQUEST", ""))
        # security 模块级 import 面也不再引入 loopback
        self.assertNotIn("is_loopback_host", inspect.getsource(security))
        self.assertNotIn(
            "is_loopback_host",
            code_only(enrichment_service.enqueue_chemical_if_needed),
        )
        # 函数仍存在(非权限用途保留), 但生产 api/ 内零调用方
        self.assertTrue(callable(rate_limit.is_loopback_host))

    def test_auth_budgets_are_account_and_global_not_address(self) -> None:
        """限流键与地址脱钩: login=账号桶(代理池换IP无效), register=全局宽松桶; request_identity 已删."""
        import api.users as users
        import api.core.rate_limit as rate_limit
        login_source = inspect.getsource(users.login)
        self.assertIn('enforce_http("login"', login_source)
        self.assertIn("sha256(account", login_source)
        self.assertNotIn("request_identity", login_source)
        self.assertIn('enforce_http("register", "global", 60, 3600)', inspect.getsource(users.register))
        self.assertFalse(hasattr(rate_limit, "request_identity"))


if __name__ == "__main__":
    unittest.main()
