from __future__ import annotations

import os
import asyncio
import inspect
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from pydantic import ValidationError

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api import agent, reactions, social, users
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
        self.assertEqual(raised.exception.detail,
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
        feed_source = inspect.getsource(social.notifications)
        summary_source = inspect.getsource(users.dashboard_summary)
        for source in (feed_source, summary_source):
            self.assertIn("JOIN community.user_follows", source)
            self.assertIn("n.created_at>=", source)
            self.assertIn("r.visibility='public'", source)
            self.assertIn("r.moderation_status='visible'", source)
        self.assertIn("ORDER BY n.created_at DESC,n.id DESC", feed_source)

    def test_activity_feed_has_a_bounded_order_index(self) -> None:
        migration = Path("migrations/history/20260722_optimize_activity_feed.sql").read_text()
        self.assertIn("notifications(user_id,created_at DESC,id DESC)", migration)
        self.assertIn("WHERE event_type='new_reaction'", migration)

    def test_concurrent_idempotent_submission_returns_existing_reaction(self) -> None:
        source = inspect.getsource(reactions_service.create_reaction)
        self.assertIn("except IntegrityError", source)
        self.assertIn("return await reaction_response(db, int(existing))", source)

    def test_all_owned_reactions_use_bounded_visibility_branches(self) -> None:
        # G2.5C: SQL 下沉至 services/reactions.list_my_reactions(bounded
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

    def test_public_api_starts_at_version_one(self) -> None:
        self.assertEqual(settings.api_version, "1.0.0")

        routes_source = inspect.getsource(__import__("api.routes", fromlist=["unified_search"]))
        self.assertNotIn('"v1:stats:exact"', routes_source)  # /api/stats 已剥离
        # G2.3 final: unified-search cache key 唯一 owner = shared orchestration
        search_source = inspect.getsource(
            __import__("api.services.search", fromlist=["execute_search"]))
        self.assertIn('f"v2:unified-search', search_source)

    def test_agent_guide_is_a_bounded_connection_and_operation_surface(self) -> None:
        source = inspect.getsource(agent.agent_guide)
        self.assertIn("optional_skill_url", source)
        # P2 边界归一: HTTP API guide 不再携带 MCP discovery
        self.assertNotIn("mcp_url", source)
        self.assertNotIn("mcp_transport", source)
        self.assertNotIn("mcp-guide", source)
        self.assertNotIn("openapi_url", source)
        self.assertIn('"operations"', source)
        self.assertIn('"payload_hints"', source)
        self.assertIn("unique Idempotency-Key", source)
        self.assertIn("AI Key", source)
        self.assertNotIn("Agent Token", source)
        # P2.1: 机器可读契约统一 AI Key 术语
        self.assertNotIn("authorization_required", source)
        self.assertNotIn("AI 授权", source)

        actor = Actor(
            7, "chemist", "Chemist", "chemist@example.test", "member", None,
            "agent", scopes=("read", "reaction:write"),
        )
        db_mock = AsyncMock()
        db_mock.execute.return_value.scalar.return_value = None
        guide = asyncio.run(agent.agent_guide("Bearer hgs_test_token", actor, db=db_mock))
        self.assertEqual(guide["connection"]["status"], "authenticated")
        self.assertEqual(guide["connection"]["account"]["username"], "chemist")
        self.assertEqual(
            {item["id"] for item in guide["operations"]},
            {
                "search_chemistry_data", "get_chemical",
                "get_reaction", "render_molecule_svg", "render_reaction_svg",
                "list_my_reactions", "list_skills", "get_skill",
                "download_skill_archive", "calculate_stoichiometry",
                "validate_reaction", "validate_skill", "create_skill",
                "create_reaction",
            },
        )


class ApiTokenBoundaryTests(unittest.TestCase):
    """P2 边界归一: Token = credential, 与 API/MCP onboarding 解耦。"""

    def test_agent_guide_anonymous_is_public_ready(self) -> None:
        # P2.1: 匿名状态 = public_ready (公开操作无需 Key), account=null
        db_mock = AsyncMock()
        db_mock.execute.return_value.scalar.return_value = None
        guide = asyncio.run(agent.agent_guide(None, None, db=db_mock))
        self.assertEqual(guide["connection"]["status"], "public_ready")
        self.assertIsNone(guide["connection"]["account"])
        self.assertIn("AI Key", guide["connection"]["instruction"])
        self.assertIn("operations", guide)
        # A-fix: 机器契约无星号伪 placeholder
        self.assertEqual(
            guide["authentication"]["header"], "Authorization: Bearer <AI Key>")
        ops = {item["id"]: item for item in guide["operations"]}
        # MCP-15 B: validate_skill 要求 skill:write scope(REST/MCP 一致); 其他操作仍为 bearer
        self.assertEqual(ops["validate_skill"]["auth"], "bearer:skill:write")
        self.assertEqual(ops["create_skill"]["auth"], "bearer:skill:write")
        self.assertEqual(ops["validate_reaction"]["auth"], "bearer:reaction:write")
        # 已认证状态
        actor = Actor(
            7, "chemist", "Chemist", "chemist@example.test", "member", None,
            "agent", scopes=("read", "reaction:write"),
        )
        guide2 = asyncio.run(agent.agent_guide("Bearer hgs_t", actor, db=db_mock))
        self.assertEqual(guide2["connection"]["status"], "authenticated")
        self.assertEqual(
            guide2["authentication"]["header"], "Authorization: Bearer <AI Key>")

    def test_machine_contract_uses_ai_key_wording(self) -> None:
        source = inspect.getsource(agent)
        self.assertNotIn("authorization_required", source)
        self.assertNotIn("AI 授权", source)
        self.assertNotIn("API Token", source)
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
        # agent_connection_text 函数已删除, 无残留消费者
        import api.agent as agent_mod
        self.assertFalse(hasattr(agent_mod, "agent_connection_text"))


if __name__ == "__main__":
    unittest.main()
