"""R4.1 静态锁: receipt prune systemd scheduler 定义。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SVC = REPO / "ops" / "systemd" / "huagongshe-receipt-prune@.service"
TMR = REPO / "ops" / "systemd" / "huagongshe-receipt-prune@.timer"


class SchedulerFilesExist(unittest.TestCase):
    def test_service_and_timer_exist(self):
        self.assertTrue(SVC.exists(), SVC)
        self.assertTrue(TMR.exists(), TMR)


class ServiceContract(unittest.TestCase):
    def setUp(self):
        self.svc = SVC.read_text()

    def test_uses_template_user_not_hardcoded(self):
        self.assertIn("User=%i", self.svc)
        self.assertNotIn("User=ubuntu", self.svc)
        self.assertNotIn("User=root", self.svc)

    def test_oneshot_with_env_file_and_workdir(self):
        self.assertIn("Type=oneshot", self.svc)
        self.assertIn("EnvironmentFile=/etc/huagongshe.env", self.svc)
        self.assertIn("WorkingDirectory=/var/www/huagongshe", self.svc)

    def test_execstart_canonical_venv_and_params(self):
        self.assertIn(
            "/var/www/huagongshe/venv/bin/python "
            "/var/www/huagongshe/scripts/prune_workapi_receipts.py "
            "--retention-days 30 --batch 10000", self.svc)

    def test_retention_30_batch_10000(self):
        self.assertIn("--retention-days 30", self.svc)
        self.assertIn("--batch 10000", self.svc)


class TimerContract(unittest.TestCase):
    def setUp(self):
        self.tmr = TMR.read_text()

    def test_daily_persistent_randomized(self):
        self.assertIn("OnCalendar=daily", self.tmr)
        self.assertIn("Persistent=true", self.tmr)
        self.assertIn("RandomizedDelaySec=", self.tmr)

    def test_targets_matching_instance_service(self):
        self.assertIn("Unit=huagongshe-receipt-prune@%i.service", self.tmr)


class NoSecondScheduler(unittest.TestCase):
    def test_repo_has_single_receipt_scheduler_definition(self):
        hits = [
            p for p in (REPO / "ops").rglob("*receipt-prune*")
            if p.is_file()
        ]
        self.assertEqual(sorted(p.name for p in hits),
                         ["huagongshe-receipt-prune@.service",
                          "huagongshe-receipt-prune@.timer"])


if __name__ == "__main__":
    unittest.main()
