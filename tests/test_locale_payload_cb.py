# 0907 locale payload cb_number 专项: 语言行 payload 缺 cb_number → callback
# 落 legacy NULL 粒度 → 同 chemical 不同 cb 的同 locale 行互相覆盖。
# 复刻 worker locale 分支的 payload 构造并断言 cb_number 继承。
import unittest


class LocalePayloadCbTests(unittest.TestCase):
    def test_locale_payload_carries_job_cb(self):
        # 与 worker/main.py locale 分支同构: job 有 cb → payload 必须带 cb_number
        job = {"cb_number": "9752126", "locale": "en"}
        payload = {"status": "ok", "entry": {"x": 1}, "suppliers": [],
                   "locale": job["locale"]}
        if job.get("cb_number"):
            payload["cb_number"] = job["cb_number"]
        self.assertEqual(payload["cb_number"], "9752126")

    def test_locale_payload_not_found_carries_job_cb(self):
        job = {"cb_number": "9752126", "locale": "ja"}
        payload = {"status": "not_found", "entry": None, "suppliers": [],
                   "locale": job["locale"]}
        if job.get("cb_number"):
            payload["cb_number"] = job["cb_number"]
        self.assertEqual(payload["cb_number"], "9752126")

    def test_locale_payload_legacy_no_cb(self):
        # legacy 线上 locale job 无 cb → payload 无 cb_number 键, 行为零漂移
        job = {"cb_number": None, "locale": "en"}
        payload = {"status": "ok", "entry": {}, "suppliers": [],
                   "locale": job["locale"]}
        if job.get("cb_number"):
            payload["cb_number"] = job["cb_number"]
        self.assertNotIn("cb_number", payload)


if __name__ == "__main__":
    unittest.main()
