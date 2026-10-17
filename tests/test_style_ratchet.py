"""样式字面值棘轮契约(进 CI 的 unittest discover)。

见 tests/style_ratchet.py 模块注释:基线之外的间距/字重/行高/z-index/
断点/容器宽/rgba 字面值与新样式前缀一律失败;存量随版式迁移逐步清零。
次数对账:同一取值当前出现次数不得超过基线次数(只许减少、不许反弹)。
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tests import style_ratchet


class StyleLiteralRatchetTests(unittest.TestCase):
    def test_no_new_literals_or_prefixes_beyond_baseline(self):
        offenders = style_ratchet.check()
        self.assertEqual([], offenders, "\n".join(offenders))

    def test_count_rebound_detected(self):
        """负向测试:基线内取值的出现次数回升必须失败(只查成员不查次数时漏检)。"""
        import json
        from pathlib import Path
        baseline = json.loads(style_ratchet.BASELINE.read_text(encoding="utf-8"))
        # 取基线里真实存在的 spacing 取值,当前次数 +1 模拟反弹
        victim = next(iter(baseline["spacing_px"]))
        fake_scan = dict(style_ratchet.scan())
        fake_scan["spacing_px"] = dict(fake_scan["spacing_px"])
        fake_scan["spacing_px"][victim] = fake_scan["spacing_px"].get(victim, 0) + 1
        with patch.object(style_ratchet, "scan", return_value=fake_scan):
            offenders = style_ratchet.check()
        rebound = [o for o in offenders if "次数反弹" in o]
        self.assertTrue(rebound, "次数回升必须产生 次数反弹 违规")
        self.assertIn(victim, rebound[0])

    def test_new_member_detected(self):
        """负向测试:基线外新取值必须失败(成员规则回归保护)。"""
        fake_scan = dict(style_ratchet.scan())
        fake_scan["spacing_px"] = dict(fake_scan["spacing_px"])
        fake_scan["spacing_px"]["777"] = 1
        with patch.object(style_ratchet, "scan", return_value=fake_scan):
            offenders = style_ratchet.check()
        self.assertTrue(any("777" in o for o in offenders))


if __name__ == "__main__":
    unittest.main()
