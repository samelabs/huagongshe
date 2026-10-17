"""PUG View 整包解析器 (worker/whole_record.py) 回归。

该解析器是 PB 链唯一入库前解析点(390 行), 此前零测试引用(PB_ARCHITECTURE
曾虚称"回归在案", 历史两次生产修复无回归锁)。本文件用合成 PUG View
Section 树锁住核心契约:
- 空壳 Record → None(worker 报 pubchem_empty 的判定源)
- core 描述符/分子量/精确质量; 数值列(int/float cast)
- CAS 去重收集; Other Identifiers 的主表 ID 列与 external_ids 分流
- synonyms 多值; GHS 码(signal/pictogram Markup.Extra/H/P 正则)
- 证据树平铺(路径键 + 引文号), Computed Properties 跳过, 400 条截断
- Safety and Hazards 关键词三桶; Reference 整表; 创建/修改日期
纯单元(无 DB/无网络), 进 CI core job。
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.whole_record import parse_whole_record  # noqa: E402


def _swm(*texts: str) -> dict:
    return {"StringWithMarkup": [{"String": t} for t in texts]}


def _info(value: dict, *, name: str = "", ref: int | None = None) -> dict:
    info: dict = {"Value": value}
    if name:
        info["Name"] = name
    if ref is not None:
        info["ReferenceNumber"] = [ref]
    return info


def _section(heading: str, *infos: dict, children: tuple | tuple = ()) -> dict:
    sec: dict = {"TOCHeading": heading}
    if infos:
        sec["Information"] = list(infos)
    if children:
        sec["Section"] = list(children)
    return sec


def _record(*sections: dict, title: str = "Aspirin", references: tuple = ()) -> dict:
    rec: dict = {"RecordTitle": title, "Section": list(sections)}
    if references:
        rec["Reference"] = list(references)
    return rec


def _payload(record: dict) -> dict:
    return {"Record": record}


class EmptyRecordTests(unittest.TestCase):
    def test_missing_record_and_empty_sections_are_none(self):
        self.assertIsNone(parse_whole_record({}))
        self.assertIsNone(parse_whole_record({"Record": {}}))
        self.assertIsNone(parse_whole_record({"Record": {"Section": []}}))


class CoreAndNumericalTests(unittest.TestCase):
    def test_core_descriptors_and_masses(self):
        record = _record(
            _section("IUPAC Name", _info(_swm("acetylsalicylic acid"))),
            _section("SMILES", _info(_swm("CC(=O)Oc1ccccc1C(=O)O"))),
            _section("InChIKey", _info(_swm("BSYNRYMUTXBXSQ-UHFFFAOYSA-N"))),
            _section("Molecular Formula", _info(_swm("C9H8O4"))),
            _section("Molecular Weight", _info(_swm("180.16"))),
            _section("Exact Mass", _info({"Number": [180.042258]})),
        )
        out = parse_whole_record(_payload(record))
        self.assertEqual(out["core"], {
            "MolecularFormula": "C9H8O4",
            "SMILES": "CC(=O)Oc1ccccc1C(=O)O",
            "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
            "IUPACName": "acetylsalicylic acid",
            "MolecularWeight": 180.16,
            "MonoisotopicMass": 180.042258,
        })

    def test_numerical_columns_cast(self):
        record = _record(
            _section("XLogP3", _info({"Number": [1.19]})),
            _section("Topological Polar Surface Area", _info({"Number": [63.6]})),
            _section("Hydrogen Bond Donor Count", _info({"Number": [1]})),
            _section("Formal Charge", _info({"Number": [0]})),
        )
        out = parse_whole_record(_payload(record))
        self.assertEqual(out["xlogp"], 1.19)
        self.assertIsInstance(out["xlogp"], float)
        self.assertEqual(out["tpsa"], 63.6)
        self.assertEqual(out["hbd"], 1)
        self.assertIsInstance(out["hbd"], int)
        self.assertEqual(out["charge"], 0)

    def test_unparsable_number_is_skipped_not_crash(self):
        record = _record(
            _section("Molecular Weight", _info(_swm("not-a-number"))),
            _section("XLogP3", _info({"Number": ["oops"]})),
        )
        out = parse_whole_record(_payload(record))
        self.assertNotIn("MolecularWeight", out["core"])
        self.assertNotIn("xlogp", out)

    def test_record_dates(self):
        record = _record(
            _section("Create Date", _info({"DateISO8601": ["2005-08-09T00:00:00Z"]})),
            _section("Modify Date", _info({"DateISO8601": ["2024-02-01T13:00:00Z"]})),
        )
        out = parse_whole_record(_payload(record))
        self.assertEqual(str(out["pubchem_created_on"]), "2005-08-09")
        self.assertEqual(str(out["pubchem_modified_on"]), "2024-02-01")


class IdentifiersTests(unittest.TestCase):
    def test_cas_dedup_across_sections(self):
        record = _record(
            _section("Other Identifiers", children=(
                _section("CAS", _info(_swm("50-78-2"))),
            )),
            _section("CAS", _info(_swm("50-78-2")), _info(_swm("69-72-7"))),
        )
        out = parse_whole_record(_payload(record))
        self.assertEqual(out["cas_numbers"], ["50-78-2", "69-72-7"])

    def test_main_table_ids_vs_external_ids_split(self):
        record = _record(
            _section("Other Identifiers", children=(
                _section("Nikkaji Number", _info(_swm("J1.799H"))),
                _section("ChEMBL ID", _info(_swm("CHEMBL25"))),
                _section("Wikipedia ID", _info(_swm("Aspirin"))),  # 非跳过名单 → external
            )),
        )
        out = parse_whole_record(_payload(record))
        self.assertEqual(out["main_table_ids"], {
            "nikkaji_numbers": ["J1.799H"], "chembl_ids": ["CHEMBL25"]})
        self.assertEqual(out["external_ids"], {"wikipedia_id": "Aspirin"})

    def test_synonyms_multiple_values(self):
        record = _record(
            _section("Depositor-Supplied Synonyms",
                     _info(_swm("2-Acetoxybenzoic acid", "acetylsalicylic acid"))),
        )
        out = parse_whole_record(_payload(record))
        self.assertEqual(out["synonyms"],
                         ["2-Acetoxybenzoic acid", "acetylsalicylic acid"])


class GhsCodesTests(unittest.TestCase):
    def test_signal_pictograms_and_code_regex(self):
        record = _record(
            _section("GHS Classification",
                     _info(_swm("Danger"), name="Signal"),
                     _info({"StringWithMarkup": [{"String": "GHS07",
                                                  "Markup": [{"Extra": "GHS07"}]}]},
                           name="Pictogram(s)"),
                     _info(_swm("H302: Harmful if swallowed [Warning Specific target organ toxicity, single exposure]"),
                           name="GHS Hazard Statements"),
                     _info(_swm("P264+P265, P270, P301+P317"),
                           name="Precautionary Statement Codes")),
        )
        out = parse_whole_record(_payload(record))
        self.assertEqual(out["ghs_codes"]["signal_word"], "Danger")
        self.assertEqual(out["ghs_codes"]["pictogram"], ["GHS07"])
        self.assertEqual(out["ghs_codes"]["h_code"], ["H302"])
        self.assertEqual(out["ghs_codes"]["p_code"],
                         ["P264", "P265", "P270", "P301", "P317"])


class EvidenceTreeTests(unittest.TestCase):
    def test_flatten_with_refs_and_computed_skip(self):
        record = _record(
            _section("Chemical and Physical Properties",
                     children=(
                         _section("Computed Properties", _info({"Number": [1]})),
                         _section("Boiling Point", _info(_swm("140 °C"), ref=11),
                                  children=()),
                         _section("Experimental Properties", children=(
                             _section("Flash Point", _info(_swm("250 °C"), ref=12)),
                         )),
                     )),
        )
        out = parse_whole_record(_payload(record))
        entries = out["physical"]["entries"]
        # 平铺从证据子树的子节点起算(根 heading 不进键), Computed Properties
        # 整枝跳过(计算值非实验证据)
        self.assertEqual(sorted(entries), [
            "Boiling Point",
            "Experimental Properties > Flash Point",
        ])
        self.assertEqual(
            entries["Boiling Point"],
            [{"value": "140 °C", "references": ["11"]}])

    def test_entry_cap_400(self):
        leaves = tuple(
            _section(f"Property {i}", _info(_swm(f"v{i}"))) for i in range(500))
        record = _record(_section("Use and Manufacturing", children=leaves))
        out = parse_whole_record(_payload(record))
        self.assertEqual(len(out["uses"]["entries"]), 400)


class SafetyBucketTests(unittest.TestCase):
    def test_three_way_bucketing(self):
        record = _record(
            _section("Safety and Hazards", children=(
                _section("GHS Classification", _info(_swm("H302"), name="Hazard")),
                _section("First Aid Measures", _info(_swm("wash skin"))),
                _section("Fire Fighting", _info(_swm("use water"))),
                _section("Incompatibilities", _info(_swm("strong oxidizers"))),
            )),
        )
        out = parse_whole_record(_payload(record))
        # 分桶从 Safety and Hazards 的子节点起算(根不进键)
        self.assertEqual(list(out["ghs"]["entries"]), ["GHS Classification"])
        self.assertEqual(sorted(out["measures"]["entries"]), [
            "Fire Fighting", "First Aid Measures"])
        self.assertEqual(list(out["hazards"]["entries"]), ["Incompatibilities"])


class ReactivityAndReferencesTests(unittest.TestCase):
    def test_reactivity_first_six_with_refs(self):
        infos = tuple(_info(_swm(f"react {i}"), ref=i) for i in range(9))
        record = _record(_section("Air and Water Reactions", *infos))
        out = parse_whole_record(_payload(record))
        self.assertEqual(len(out["reactivity"]["air_water"]), 6)
        self.assertEqual(out["reactivity"]["air_water"][0]["references"], ["0"])

    def test_references_table(self):
        record = _record(
            _section("IUPAC Name", _info(_swm("x"))),  # 空 Section 树会早退 None
            references=(
                {"ReferenceNumber": 1, "SourceName": "PubChem",
                 "Name": "Aspirin", "URL": "https://example.com", "Ignored": "x"},
                {"ReferenceNumber": 2, "SourceName": "HSDB"},
            ))
        out = parse_whole_record(_payload(record))
        self.assertEqual(out["references"]["1"], {
            "SourceName": "PubChem", "Name": "Aspirin",
            "URL": "https://example.com"})
        self.assertEqual(out["references"]["2"], {"SourceName": "HSDB"})


class FNew01ContractTests(unittest.TestCase):
    def test_core_has_no_cid_key(self):
        """F-NEW-01 的事故形态锁: 解析器不产出 core.CID —— CID 回写只经
        query binding 授予(complete_pubchem_job), 两者不得重新耦合。"""
        record = _record(_section("InChIKey", _info(_swm("X"*14 + "-Y"*10 + "-N"))))
        out = parse_whole_record(_payload(record))
        self.assertNotIn("CID", out["core"])
        self.assertNotIn("pubchem_cid", out["core"])


if __name__ == "__main__":
    unittest.main()
