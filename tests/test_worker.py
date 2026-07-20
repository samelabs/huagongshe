from __future__ import annotations

import unittest

from worker.chemistry import select_verified_cid
from worker.pubchem import normalize_view, throttle_status


class ThrottleTests(unittest.TestCase):
    def test_worst_pubchem_throttle_signal_wins(self) -> None:
        header = "Request Count status: Green (10%), Request Time status: Red (80%)"
        self.assertEqual(throttle_status(header), "red")

    def test_missing_signal_is_conservative_green(self) -> None:
        self.assertEqual(throttle_status(None), "green")


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
