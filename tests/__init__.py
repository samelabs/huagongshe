"""Huagongshe tests."""

import sys
import unittest

# IsolatedAsyncioTestCase 每个用例一个事件循环；api.core.cache 按循环建 Redis
# 连接池。循环关闭前断开本循环的池，否则连接在循环关闭后才被回收，退出时报
# unclosed Connection / transport。未导入 api.core.cache 的测试不受影响。
_tear_down_runner = unittest.IsolatedAsyncioTestCase._tearDownAsyncioRunner


def _tear_down_runner_closing_redis(self):
    cache = sys.modules.get("api.core.cache")
    if cache is not None:
        self._asyncioRunner.get_loop().run_until_complete(cache.close_loop_pool())
    _tear_down_runner(self)


unittest.IsolatedAsyncioTestCase._tearDownAsyncioRunner = _tear_down_runner_closing_redis
