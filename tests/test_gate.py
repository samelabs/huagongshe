"""闸门阶梯单测(数据链收口§4) + 过渡判定映射(§1)。"""

from __future__ import annotations

import asyncio
import time
import unittest

from api.services.gate import LADDER, _silence_for, gate_record_error, gate_silence_remaining


class FauxRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}

    async def incr(self, key):
        v = int(self.kv.get(key, "0")) + 1
        self.kv[key] = str(v)
        return v

    async def set(self, key, val, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(val)
        return True

    async def get(self, key):
        return self.kv.get(key)

    async def delete(self, *keys):
        for k in keys:
            self.kv.pop(k, None)


class TestLadder(unittest.TestCase):
    def test_ladder_shape(self):
        # 定案: 5错→5分; +2(=7)→10分; +1(=8)→30分; +1(=9)→停(半开30分)
        self.assertEqual(LADDER, ((5, 300), (7, 600), (8, 1800), (9, 1800)))

    def test_silence_mapping(self):
        self.assertEqual(_silence_for(0), 0)
        self.assertEqual(_silence_for(4), 0)
        self.assertEqual(_silence_for(5), 300)
        self.assertEqual(_silence_for(6), 300)
        self.assertEqual(_silence_for(7), 600)
        self.assertEqual(_silence_for(8), 1800)
        self.assertEqual(_silence_for(9), 1800)   # 停止档=半开间隔
        self.assertEqual(_silence_for(50), 1800)

    def test_no_silence_below_threshold(self):
        r = FauxRedis()
        for _ in range(4):
            asyncio.run(gate_record_error(r, "cb"))
        self.assertEqual(asyncio.run(gate_silence_remaining(r, "cb")), 0.0)

    def test_silence_at_fifth_error(self):
        r = FauxRedis()
        for _ in range(5):
            asyncio.run(gate_record_error(r, "cb"))
        remaining = asyncio.run(gate_silence_remaining(r, "cb"))
        self.assertGreater(remaining, 290)
        self.assertLessEqual(remaining, 300)

    def test_success_resets(self):
        r = FauxRedis()
        for _ in range(9):  # 爬到停止档
            asyncio.run(gate_record_error(r, "pubchem"))
        self.assertGreater(asyncio.run(gate_silence_remaining(r, "pubchem")), 0)
        from api.services.gate import gate_record_success
        asyncio.run(gate_record_success(r, "pubchem"))
        self.assertEqual(asyncio.run(gate_silence_remaining(r, "pubchem")), 0.0)

    def test_redis_absent_is_permissive(self):
        self.assertEqual(asyncio.run(gate_silence_remaining(None, "cb")), 0.0)
        self.assertEqual(asyncio.run(gate_record_error(None, "cb")), 0)


class TestFetchMapping(unittest.TestCase):
    """过渡判定(§1): fetch 三态映射 — 用 cpp_page_state 真函数验判定边界。"""

    def test_busy_page_is_busy(self):
        from caslib.parse import cpp_page_state
        # busy 正则 + 长度 >500B(<500B 归 empty, 实测 14 字节页现归 not_found 路径)
        body = "系统忙" + "x" * 600
        self.assertEqual(cpp_page_state(body), "busy")

    def test_empty_page(self):
        from caslib.parse import cpp_page_state
        self.assertEqual(cpp_page_state(""), "empty")
        self.assertEqual(cpp_page_state(None), "empty")
        self.assertEqual(cpp_page_state("<html></html>"[:200]), "empty")

    def test_normal_page_is_ok(self):
        from caslib.parse import cpp_page_state
        body = "<html>" + "x" * 2000 + "</html>"
        self.assertEqual(cpp_page_state(body), "ok")


if __name__ == "__main__":
    unittest.main()
