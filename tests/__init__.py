"""Huagongshe tests."""

import sys
import unittest

# IsolatedAsyncioTestCase 每个用例一个事件循环；api.core.cache 按循环建 Redis
# 连接池。循环关闭前断开本循环的池，否则连接在循环关闭后才被回收，退出时报
# unclosed Connection / transport。未导入 api.core.cache 的测试不受影响。
# 收尾钩子是 3.11+ 的 asyncio.Runner 形态（CI 与 API 容器 3.12）；宿主机
# 旧解释器只跑源码契约测试，不建池，无需挂钩。
_tear_down_runner = getattr(unittest.IsolatedAsyncioTestCase, "_tearDownAsyncioRunner", None)


def _tear_down_runner_closing_redis(self):
    cache = sys.modules.get("api.core.cache")
    if cache is not None:
        try:
            loop = self._asyncioRunner.get_loop()
        except RuntimeError:  # __del__ 的二次收尾：runner 已关闭
            loop = None
        if loop is not None:
            loop.run_until_complete(cache.close_loop_pool())
    _tear_down_runner(self)


if _tear_down_runner is not None:
    unittest.IsolatedAsyncioTestCase._tearDownAsyncioRunner = _tear_down_runner_closing_redis
