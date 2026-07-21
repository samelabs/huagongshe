from __future__ import annotations

import os
import inspect
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

os.environ.setdefault("HGS_DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")

from api import reactions
from api.config import settings
from api.reactions import ParticipantBody, ReactionBody, canonical_participants


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
        with self.assertRaises(HTTPException) as raised:
            canonical_participants(value)
        self.assertEqual(raised.exception.status_code, 409)

    def test_occurrence_count_preserves_stoichiometric_repetition(self) -> None:
        _, expression = canonical_participants(body(participants=[
            {"role": "REACTANT", "smiles": "CCO", "occurrence_count": 2},
            {"role": "PRODUCT", "smiles": "CC=O"},
        ]))
        self.assertEqual(expression, "CCO.CCO>>CC=O")

    def test_notification_keys_cast_numeric_parameters(self) -> None:
        source = inspect.getsource(reactions)
        self.assertIn('"reaction_id_text": str(reaction_id)', source)
        self.assertIn('"reaction_text": str(reaction_id)', source)

    def test_all_owned_reactions_use_bounded_visibility_branches(self) -> None:
        source = inspect.getsource(reactions.my_reactions)
        self.assertIn("WITH owned AS MATERIALIZED", source)
        self.assertIn("visibility='public'", source)
        self.assertIn("visibility='private'", source)
        self.assertIn("LIMIT :window", source)
        self.assertIn('"items": [dict(row) for row in rows]', source)
        self.assertIn('"all": sum(counts.values())', source)

    def test_public_api_starts_at_version_one(self) -> None:
        self.assertEqual(settings.api_version, "1.0")

        routes_source = inspect.getsource(__import__("api.routes", fromlist=["unified_search"]))
        self.assertIn('"v1:stats:exact"', routes_source)
        self.assertIn('f"v1:unified-search', routes_source)

    def test_agent_guide_links_the_public_skill_and_confirmation_flow(self) -> None:
        source = inspect.getsource(reactions.agent_guide)
        self.assertIn("huagongshe-reaction-publisher/SKILL.md", source)
        self.assertIn("用户确认后携带唯一 Idempotency-Key", source)
        self.assertIn("用户创建的 API Token", source)
        self.assertNotIn("Agent Token", source)


if __name__ == "__main__":
    unittest.main()
