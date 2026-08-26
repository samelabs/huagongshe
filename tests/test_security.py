from __future__ import annotations

import asyncio
import inspect
import os
import unittest

from fastapi import HTTPException

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api import admin, social, users
from api.security import Actor, current_session


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

    def test_public_reads_are_gated_by_internal_or_actor(self) -> None:
        """B2 通道规范: 公开读端点一律 internal_or_actor(loopback=SSR 或已鉴权; 匿名公网 401)."""
        import api.routes as routes
        for endpoint in (
            routes.search, routes.chemical_detail, routes.chemical_externals,
            routes.chemical_synonyms, routes.chemical_reactions, routes.reaction_detail,
            routes.stats, routes.datasets,
        ):
            self.assertIn("Depends(internal_or_actor)", inspect.getsource(endpoint))

    def test_auth_budgets_are_account_and_global_not_address(self) -> None:
        """限流键与地址脱钩: login=账号桶(代理池换IP无效), register=全局宽松桶; request_identity 已删."""
        import api.users as users
        import api.rate_limit as rate_limit
        login_source = inspect.getsource(users.login)
        self.assertIn('enforce("login"', login_source)
        self.assertIn("sha256(account", login_source)
        self.assertNotIn("request_identity", login_source)
        self.assertIn('enforce("register", "global", 60, 3600)', inspect.getsource(users.register))
        self.assertFalse(hasattr(rate_limit, "request_identity"))


if __name__ == "__main__":
    unittest.main()
