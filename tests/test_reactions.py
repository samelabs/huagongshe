from __future__ import annotations

import os
import asyncio
import inspect
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from pydantic import ValidationError

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api import reactions, social, users
from api.services import reactions as reactions_service
from api.core.config import settings
from api.services.reactions import (ReactionValidationError,
                                    canonical_participants)
from api.schemas.reactions import ParticipantBody, ReactionBody
from api.core.security import Actor


def body(**overrides) -> ReactionBody:
    values = {
        "visibility": "public",
        "participants": [
            {"role": "REACTANT", "smiles": "C(C)O"},
            {"role": "PRODUCT", "smiles": "CC=O", "yield_percent": 81.5},
        ],
        "source_type": "self",
    }
    values.update(overrides)
    return ReactionBody.model_validate(values)


class ReactionContractTests(unittest.TestCase):
    def test_canonical_expression_is_built_from_one_contract(self) -> None:
        participants, expression = canonical_participants(body())
        self.assertEqual(expression, "CCO>>CC=O")
        self.assertEqual(participants[0]["canonical_smiles"], "CCO")

    def test_external_source_requires_matching_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            body(source_type="doi")
        self.assertEqual(body(source_type="doi", doi="10.1000/example").doi, "10.1000/example")

    def test_doi_is_normalized_for_storage(self) -> None:
        self.assertEqual(
            body(source_type="doi", doi="https://doi.org/10.1039/C8SC04228D").doi,
            "10.1039/c8sc04228d",
        )

    def test_unknown_optional_facts_can_stay_empty(self) -> None:
        value = body()
        self.assertIsNone(value.procedure_details)
        self.assertIsNone(value.temperature_value)

    def test_yield_is_product_only(self) -> None:
        with self.assertRaises(ValidationError):
            ParticipantBody(role="REACTANT", smiles="CCO", yield_percent=50)

    def test_duplicate_role_and_structure_is_rejected(self) -> None:
        value = body(participants=[
            {"role": "REACTANT", "smiles": "CCO"},
            {"role": "REACTANT", "smiles": "C(C)O"},
            {"role": "PRODUCT", "smiles": "CC=O"},
        ])
        with self.assertRaises(ReactionValidationError) as raised:
            canonical_participants(value)
        self.assertEqual(raised.exception.kind,
                         ReactionValidationError.DUPLICATE_PARTICIPANT)
        self.assertEqual(
            raised.exception.detail,
            "第 2 个参与物与前面的参与物重复："
            "同一化合物和角色请合并为一项，并填写出现次数")

    def test_occurrence_count_preserves_stoichiometric_repetition(self) -> None:
        _, expression = canonical_participants(body(participants=[
            {"role": "REACTANT", "smiles": "CCO", "occurrence_count": 2},
            {"role": "PRODUCT", "smiles": "CC=O"},
        ]))
        self.assertEqual(expression, "CCO.CCO>>CC=O")

    def test_notification_keys_cast_numeric_parameters(self) -> None:
        source = inspect.getsource(reactions_service)
        self.assertIn('"reaction_id_text": str(reaction_id)', source)

    def test_activity_is_only_new_reactions_from_followed_users(self) -> None:
        source = inspect.getsource(reactions_service.notify_new_reaction)
        self.assertIn("FROM community.user_follows", source)
        self.assertNotIn("chemical_follows", source)
        self.assertNotIn("reaction_updated", inspect.getsource(reactions_service.update_reaction))

    def test_activity_cannot_block_the_core_reaction_transaction(self) -> None:
        source = inspect.getsource(reactions_service.notify_new_reaction_safely)
        self.assertIn("statement_timeout='1000ms'", source)
        self.assertIn("await db.rollback()", source)
        create_source = inspect.getsource(reactions_service.create_reaction)
        self.assertLess(create_source.index("await db.commit()"), create_source.index("notify_new_reaction_safely"))

    def test_activity_feed_only_returns_current_visible_followed_reactions(self) -> None:
        # feed 过滤条件提取为 social 模块级共享常量(notifications 端点
        # 与 unread_activity_count 同一过滤), 静态断言随之看模块源; dashboard
        # 未读数委托 unread_activity_count(不再自带 SQL)。
        social_source = inspect.getsource(social)
        self.assertIn("JOIN community.user_follows", social_source)
        self.assertIn("n.created_at>=", social_source)
        self.assertIn("r.visibility='public'", social_source)
        self.assertIn("r.moderation_status='visible'", social_source)
        # 笔记事件与反应事件同构过滤
        self.assertIn("nt.visibility='public'", social_source)
        self.assertIn("nt.moderation_status='visible'", social_source)
        feed_source = inspect.getsource(social.notifications)
        self.assertIn("ORDER BY n.created_at DESC,n.id DESC", feed_source)
        summary_source = inspect.getsource(users.dashboard_summary)
        self.assertIn("unread_activity_count", summary_source)

    def test_activity_feed_has_a_bounded_order_index(self) -> None:
        migration = Path("migrations/history/20260722_optimize_activity_feed.sql").read_text()
        self.assertIn("notifications(user_id,created_at DESC,id DESC)", migration)
        self.assertIn("WHERE event_type='new_reaction'", migration)

    def test_concurrent_idempotent_submission_returns_existing_reaction(self) -> None:
        source = inspect.getsource(reactions_service.create_reaction)
        self.assertIn("except IntegrityError", source)
        self.assertIn("return await reaction_response(db, int(existing))", source)

    def test_all_owned_reactions_use_bounded_visibility_branches(self) -> None:
        # SQL 下沉至 services/reactions.list_my_reactions(bounded
        # UNION ALL 是硬 contract), 断言迁新 owner。
        from api.services.reactions import list_my_reactions as _svc
        source = inspect.getsource(_svc)
        self.assertIn("WITH owned AS MATERIALIZED", source)
        self.assertIn("visibility='public'", source)
        self.assertIn("visibility='private'", source)
        self.assertIn("LIMIT :window", source)
        self.assertIn('"items": [dict(row) for row in rows]', source)
        self.assertIn('"all": sum(counts.values())', source)
        adapter_source = inspect.getsource(reactions.my_reactions)
        self.assertNotIn("WITH owned", adapter_source)
        self.assertNotIn("OFFSET", adapter_source)
        self.assertIn("list_my_reactions(", adapter_source)

    def test_api_version_matches_version_file(self) -> None:
        # 版本号单一来源(仓库根 VERSION); 旧的 "1.0.0 公共 API 版本"
        # 约定已撤销
        from pathlib import Path as _Path
        version_file = (_Path(__file__).resolve().parents[1] / "VERSION")
        self.assertEqual(settings.api_version,
                         version_file.read_text(encoding="utf-8").strip())

        routes_source = inspect.getsource(__import__("api.routes", fromlist=["unified_search"]))
        self.assertNotIn('"v1:stats:exact"', routes_source)  # /api/stats 已剥离
        # unified-search cache key 唯一 owner = shared orchestration
        search_source = inspect.getsource(
            __import__("api.services.search", fromlist=["execute_search"]))
        self.assertIn('f"v2:unified-search', search_source)

class ApiTokenBoundaryTests(unittest.TestCase):
    """P2 边界归一: Token = credential, 与 API/MCP onboarding 解耦。"""

    def test_machine_contract_uses_ai_key_wording(self) -> None:
        # /api/agent-guide 已删, 机器契约术语只剩 MCP 面
        mcp_source = Path(inspect.getsourcefile(__import__("api.mcp_server", fromlist=["x"]))).read_text()
        self.assertNotIn("API Token", mcp_source)
        self.assertIn("AI Key", mcp_source)

    def test_token_create_response_only_returns_credential_and_metadata(self) -> None:
        # create_token handler 源码契约: 只返回 row(id/name/prefix/scopes/created_at/expires_at)+token
        import api.users as users_mod
        source = inspect.getsource(users_mod.create_token)
        return_source = source[source.rindex("return {"):]
        self.assertIn('"token": plain', return_source)
        for coupling in ("agent_connection_text", "agent_guide_url", "api_base_url"):
            self.assertNotIn(f'"{coupling}"', return_source)
        # api.agent 模块整体退役(REST 不再对外, guide 端点删除)
        import importlib.util
        self.assertIsNone(importlib.util.find_spec("api.agent"))


if __name__ == "__main__":
    unittest.main()
