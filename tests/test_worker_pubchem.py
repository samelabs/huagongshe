from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from worker.main import heartbeat
from worker.pubchem import (
    PubChemRateController,
    throttle_status,
)


class ThrottleTests(unittest.TestCase):
    def test_worst_pubchem_throttle_signal_wins(self) -> None:
        header = "Request Count status: Green (10%), Request Time status: Red (80%)"
        self.assertEqual(throttle_status(header), "red")

    def test_missing_signal_is_conservative_green(self) -> None:
        self.assertEqual(throttle_status(None), "unknown")


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
        stop = asyncio.Event()
        client = AsyncMock()

        async def post(_path, _payload):
            if client.post.await_count == 1:
                raise RuntimeError("temporary network failure")
            stop.set()
            return {}

        client.post.side_effect = post
        async def timeout_immediately(awaitable, timeout):
            awaitable.close()
            raise asyncio.TimeoutError

        with patch("worker.main.asyncio.wait_for", new=timeout_immediately):
            await heartbeat(client, {"job_id": 7, "lease_token": "lease", "lease_seconds": 60}, stop)
        self.assertEqual(client.post.await_count, 2)


if __name__ == "__main__":
    unittest.main()
