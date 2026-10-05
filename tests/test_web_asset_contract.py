"""Web 静态资产契约检查。

目的不是测试图片内容, 而是防止:
- 资产文件被重构误删
- 扩展名与真实二进制格式不符 (如 PNG 伪装成 .ico)
- PWA manifest(当前为 Next dynamic manifest)指向不存在的资产

纯文件系统检查, 不依赖网络/DB, 始终运行 (无 skip 模式)。
"""
from __future__ import annotations

import os
import re
import unittest

WEB_ROOT = os.path.join(os.path.dirname(__file__), "..", "web")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ICO_MAGIC = b"\x00\x00\x01\x00"


def _read_head(rel: str, n: int = 8) -> bytes:
    path = os.path.join(WEB_ROOT, rel)
    if not os.path.isfile(path):
        return b""
    with open(path, "rb") as f:
        return f.read(n)


class WebAssetContractTests(unittest.TestCase):
    """favicon / PWA 图标资产契约。"""

    def test_app_icon_png_exists_with_png_magic(self):
        head = _read_head(os.path.join("app", "icon.png"))
        self.assertTrue(head, "web/app/icon.png missing")
        self.assertEqual(head[:8], PNG_MAGIC, "app/icon.png is not PNG")

    def test_apple_icon_png_exists_with_png_magic(self):
        head = _read_head(os.path.join("app", "apple-icon.png"))
        self.assertTrue(head, "web/app/apple-icon.png missing")
        self.assertEqual(head[:8], PNG_MAGIC, "app/apple-icon.png is not PNG")

    def test_favicon_ico_is_real_ico(self):
        path = os.path.join(WEB_ROOT, "public", "favicon.ico")
        self.assertTrue(os.path.isfile(path), "web/public/favicon.ico missing")
        with open(path, "rb") as f:
            head = f.read(4)
        self.assertEqual(
            head, ICO_MAGIC,
            "favicon.ico magic bytes are not 00 00 01 00 — "
            "PNG-renamed-to-.ico regression detected",
        )
        # ICO header: reserved=0, type=1, 至少 1 个目录项
        with open(path, "rb") as f:
            f.seek(4)
            count = int.from_bytes(f.read(2), "little")
        self.assertGreaterEqual(count, 3, "favicon.ico should contain 16/32/48 sizes")

    def test_manifest_icons_all_exist(self):
        manifest_path = os.path.join(WEB_ROOT, "app", "manifest.ts")
        self.assertTrue(os.path.isfile(manifest_path), "web/app/manifest.ts missing")
        with open(manifest_path, "r", encoding="utf-8") as f:
            source = f.read()
        icons = re.findall(r'src:\s*["\'](/[^"\']+)["\']', source)
        self.assertTrue(icons, "dynamic manifest has no icon src declarations")
        for src in icons:
            rel = src.lstrip("/")
            self.assertTrue(
                os.path.isfile(os.path.join(WEB_ROOT, "public", rel)),
                f"manifest icon missing on disk: {rel}",
            )

    def test_dynamic_manifest_is_not_service_worker_cached(self):
        sw_path = os.path.join(WEB_ROOT, "public", "sw.js")
        self.assertTrue(os.path.isfile(sw_path), "web/public/sw.js missing")

        with open(sw_path, "r", encoding="utf-8") as f:
            source = f.read()

        static_pattern = next(
            (
                line
                for line in source.splitlines()
                if line.strip().startswith("const STATIC_PATTERN")
            ),
            "",
        )

        self.assertTrue(static_pattern, "Service Worker STATIC_PATTERN missing")
        self.assertNotIn(
            "manifest",
            static_pattern,
            "dynamic manifest must not be cached by Service Worker",
        )

    def test_manifest_has_stable_identity_and_start_url(self):
        manifest_path = os.path.join(WEB_ROOT, "app", "manifest.ts")
        self.assertTrue(os.path.isfile(manifest_path), "web/app/manifest.ts missing")

        with open(manifest_path, "r", encoding="utf-8") as f:
            source = f.read()

        self.assertRegex(
            source,
            r'id:\s*["\']/["\']',
            'PWA manifest id must stay stable at "/"',
        )
        self.assertRegex(
            source,
            r'start_url:\s*["\']/["\']',
            'PWA start_url must stay at "/" and delegate locale negotiation to root',
        )


if __name__ == "__main__":
    unittest.main()
