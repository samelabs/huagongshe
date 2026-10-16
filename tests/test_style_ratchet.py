"""样式字面值棘轮契约(进 CI 的 unittest discover)。

见 tests/style_ratchet.py 模块注释:基线之外的间距/字重/行高/z-index/
断点/容器宽/rgba 字面值与新样式前缀一律失败;存量随版式迁移逐步清零。
"""

from __future__ import annotations

import unittest

from tests import style_ratchet


class StyleLiteralRatchetTests(unittest.TestCase):
    def test_no_new_literals_or_prefixes_beyond_baseline(self):
        offenders = style_ratchet.check()
        self.assertEqual([], offenders, "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
