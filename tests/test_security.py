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


if __name__ == "__main__":
    unittest.main()
