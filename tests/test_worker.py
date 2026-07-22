from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from api.pubchem_core import chemical_core_values, validate_synonyms
from worker.chemistry import select_verified_cid
from worker.main import heartbeat
from worker.pubchem import (
    PROPERTY_NAMES,
    PubChemRateController,
    extract_synonyms,
    normalize_view,
    throttle_status,
)


class ChemicalCoreMappingTests(unittest.TestCase):
    def test_worker_requests_all_chemicals_core_properties(self) -> None:
        requested = set(PROPERTY_NAMES.split(","))
        self.assertTrue({
            "Title", "IUPACName", "MolecularFormula", "MolecularWeight",
            "MonoisotopicMass", "InChIKey",
        }.issubset(requested))

    def test_verified_pubchem_properties_map_to_chemicals(self) -> None:
        values = chemical_core_values({
            "Title": "Aspirin",
            "IUPACName": "2-acetyloxybenzoic acid",
            "MolecularFormula": "C9H8O4",
            "MolecularWeight": "180.16",
            "MonoisotopicMass": "180.04225873",
            "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        })
        self.assertEqual(values["preferred_name"], "Aspirin")
        self.assertEqual(values["average_mass"], 180.16)
        self.assertEqual(values["monoisotopic_mass"], 180.04225873)
        self.assertEqual(values["inchikey"], "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")

    def test_missing_or_invalid_values_do_not_clear_existing_core(self) -> None:
        values = chemical_core_values({
            "Title": " ",
            "MolecularWeight": "not-a-number",
            "MonoisotopicMass": -1,
            "InChIKey": "invalid",
        })
        self.assertTrue(all(value is None for value in values.values()))

    def test_complete_synonyms_preserve_source_order_and_duplicates(self) -> None:
        payload = {
            "InformationList": {
                "Information": [{"CID": 702, "Synonym": ["ethanol", "EtOH", "ethanol"]}]
            }
        }
        values = extract_synonyms(payload)
        self.assertEqual(values, ["ethanol", "EtOH", "ethanol"])
        self.assertIs(validate_synonyms(values), values)

    def test_malformed_synonyms_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_synonyms(["valid", 702])


class ThrottleTests(unittest.TestCase):
    def test_worst_pubchem_throttle_signal_wins(self) -> None:
        header = "Request Count status: Green (10%), Request Time status: Red (80%)"
        self.assertEqual(throttle_status(header), "red")

    def test_missing_signal_is_conservative_green(self) -> None:
        self.assertEqual(throttle_status(None), "green")


class LocalRateControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_feedback_changes_only_the_worker_local_spacing(self) -> None:
        controller = PubChemRateController(4)
        self.assertEqual(controller.spacing, 0.25)
        await controller.feedback("red", 200)
        self.assertEqual(controller.spacing, 1.0)
        await controller.feedback("green", 200)
        self.assertEqual(controller.spacing, 0.8)

    async def test_invalid_rate_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PubChemRateController(6)


class HeartbeatTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_does_not_stop_lease_renewal(self) -> None:
        stop = __import__("asyncio").Event()
        client = AsyncMock()

        async def post(_path, _payload):
            if client.post.await_count == 1:
                raise RuntimeError("temporary network failure")
            stop.set()
            return {}

        client.post.side_effect = post
        with patch("worker.main.asyncio.wait_for", new=AsyncMock(side_effect=[
            __import__("asyncio").TimeoutError(),
            __import__("asyncio").TimeoutError(),
        ])):
            await heartbeat(client, {"job_id": 7, "lease_token": "lease", "lease_seconds": 60}, stop)
        self.assertEqual(client.post.await_count, 2)


class IdentitySelectionTests(unittest.TestCase):
    def test_expected_cid_must_have_a_property_record(self) -> None:
        selected = select_verified_cid(
            [702], [], expected_cid=702, expected_smiles="CCO"
        )
        self.assertIsNone(selected)

    def test_structure_selects_one_candidate(self) -> None:
        selected = select_verified_cid(
            [702, 1234],
            [
                {"CID": 702, "SMILES": "C(C)O"},
                {"CID": 1234, "SMILES": "CC=O"},
            ],
            expected_cid=None,
            expected_smiles="CCO",
        )
        self.assertEqual(selected, 702)

    def test_ambiguous_structure_is_not_guessed(self) -> None:
        selected = select_verified_cid(
            [1, 2],
            [{"CID": 1, "SMILES": "CCO"}, {"CID": 2, "SMILES": "OCC"}],
            expected_cid=None,
            expected_smiles="CCO",
        )
        self.assertIsNone(selected)


class PugViewNormalizationTests(unittest.TestCase):
    @staticmethod
    def payload() -> dict:
        return {
            "Record": {
                "Reference": [
                    {
                        "ReferenceNumber": 1,
                        "SourceName": "Authoritative Registry",
                        "SourceID": "registry-1",
                    }
                ],
                "Section": [
                    {
                        "TOCHeading": "Names and Identifiers",
                        "Section": [
                            {
                                "TOCHeading": "Other Identifiers",
                                "Section": [
                                    {
                                        "TOCHeading": "CAS",
                                        "Information": [
                                            {
                                                "Value": {"StringWithMarkup": [{"String": "64-17-5"}]},
                                                "ReferenceNumber": [1],
                                            }
                                        ],
                                    },
                                    {
                                        "TOCHeading": "Related CAS",
                                        "Information": [
                                            {
                                                "Value": {"StringWithMarkup": [{"String": "42840-71-7"}]},
                                                "ReferenceNumber": [1],
                                            }
                                        ],
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        }

    def test_identifier_categories_and_source_evidence_stay_separate(self) -> None:
        normalized = normalize_view(self.payload(), "identifiers")
        paths = normalized["entries"]
        self.assertIn("Names and Identifiers > Other Identifiers > CAS", paths)
        self.assertIn("Names and Identifiers > Other Identifiers > Related CAS", paths)
        self.assertEqual(normalized["references"]["1"]["SourceName"], "Authoritative Registry")
        self.assertFalse(normalized["normalization"]["truncated"])

    def test_safety_information_is_split_by_meaning(self) -> None:
        payload = self.payload()
        section = payload["Record"]["Section"][0]["Section"][0]["Section"][0]
        section["TOCHeading"] = "GHS Classification"
        normalized = normalize_view(payload, "safety")
        self.assertTrue(normalized["ghs"]["entries"])
        self.assertFalse(normalized["measures"]["entries"])


if __name__ == "__main__":
    unittest.main()
