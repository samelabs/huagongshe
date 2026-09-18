"""E7 §5/§11 — registry 事实新鲜度(只做事实更新, 不扩治理框架)。

锁:
1. 陈旧口径不得再出现: `request=None` 直调描述、D001 类未解决标记;
2. reaction family 的 effect 必须与真实能力一致:
   list_own 是 ACTOR 自读 → 落在 E.READ family; E.WRITE family 只放需 scope 的写操作;
3. 同一 scenario 不得同时挂两个 family(描述歧义的来源)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

REGISTRY_PATH = REPO / "api" / "contracts" / "registry.py"

# 陈旧口径标记(拼接构造, 避免本文件自匹配)
STALE_MARKERS = (
    "request" + "=None",
    "D001" + " 挂账",
    "挂账",
    "未解决",
    "TODO",
    "FIXME",
)


class RegistryFactFreshnessTests(unittest.TestCase):
    def test_no_stale_markers_in_registry(self):
        text = REGISTRY_PATH.read_text(encoding="utf-8")
        hits = [m for m in STALE_MARKERS if m in text]
        self.assertEqual(hits, [], f"registry 仍含陈旧标记: {hits}")

    def test_reaction_list_own_sits_in_read_family(self):
        from api.contracts.registry import FAMILIES
        fams = [f for f in FAMILIES if any(s.id == "list_own" for s in f.scenarios)]
        self.assertEqual(len(fams), 1,
                         f"list_own 应只属一个 family, 实际: {[f.id for f in fams]}")
        self.assertEqual(fams[0].effect.name, "READ",
                         f"list_own 是 ACTOR 自读, 却挂在 {fams[0].id}"
                         f"({fams[0].effect.name})")

    def test_reaction_write_family_holds_only_mutating_entrypoints(self):
        """E.WRITE family 的 HTTP 入口必须是写方法(不做 scope 全局规则)。"""
        from api.contracts.registry import FAMILIES
        fam = next(f for f in FAMILIES if f.id == "reaction.write")
        self.assertEqual(fam.effect.name, "WRITE")
        non_mutating = [
            f"{sc.id}:{ep.name}" for sc in fam.scenarios for ep in sc.entrypoints
            if ep.name.startswith(("GET ", "HEAD "))
        ]
        self.assertEqual(non_mutating, [],
                         f"E.WRITE family 混入只读入口: {non_mutating}")

    def test_reaction_read_family_holds_only_read_entrypoints(self):
        from api.contracts.registry import FAMILIES
        fam = next(f for f in FAMILIES if f.id == "reaction.read")
        self.assertEqual(fam.effect.name, "READ")
        mutating = [
            f"{sc.id}:{ep.name}" for sc in fam.scenarios for ep in sc.entrypoints
            if ep.name.startswith(("POST ", "PUT ", "PATCH ", "DELETE "))
        ]
        self.assertEqual(mutating, [], f"E.READ family 混入写入口: {mutating}")

    def test_scenario_ids_unique_within_family(self):
        from api.contracts.registry import FAMILIES
        for fam in FAMILIES:
            ids = [sc.id for sc in fam.scenarios]
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            self.assertEqual(dupes, [], f"{fam.id} 内 scenario 重名: {dupes}")


if __name__ == "__main__":
    unittest.main()
