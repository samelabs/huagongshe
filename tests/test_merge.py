"""merge_entry 单测(0902 P3a) + 真页合并实测"""
import unittest
from caslib.merge import merge_entry


class TestMergeEntry(unittest.TestCase):
    def test_cpp_wins_on_conflict(self):
        cpp = {"props": {"密度": "0.79"}, "basic": [["中文名", "丙酮"]]}
        cas = {"props": {"密度": "0.80", "溶解性": "混溶"}, "basic": [["中文名", "丙酮"], ["EINECS", "200-662-2"]]}
        m = merge_entry(cpp, cas)
        self.assertEqual(m["props"]["密度"], "0.79")       # CPP 恒胜
        self.assertEqual(m["props"]["溶解性"], "混溶")      # 只补缺
        self.assertEqual(dict(m["basic"])["EINECS"], "200-662-2")  # basic 补行
        self.assertEqual(len(m["basic"]), 2)                # 同 key 不重复

    def test_cas_only_block_whole_inherit(self):
        cpp = {"props": {"密度": "1"}}
        cas = {"reagents": [{"name": "x"}]}
        m = merge_entry(cpp, cas)
        self.assertEqual(m["reagents"], [{"name": "x"}])   # CAS 独有块整体并入

    def test_aliases_dedupe_append(self):
        cpp = {"aliases": ["丙酮", "醋酮"]}
        cas = {"aliases": ["醋酮", "二甲酮"]}
        m = merge_entry(cpp, cas)
        self.assertEqual(m["aliases"], ["丙酮", "醋酮", "二甲酮"])

    def test_empty_cas_noop(self):
        cpp = {"props": {"a": "1"}}
        self.assertEqual(merge_entry(cpp, {}), cpp)

    def test_empty_cpp_block_takes_cas(self):
        cpp = {"safety": {}, "props": {"a": "1"}}
        cas = {"safety": {"危险": "易燃"}}
        m = merge_entry(cpp, cas)
        self.assertEqual(m["safety"], {"危险": "易燃"})


if __name__ == "__main__":
    unittest.main()
