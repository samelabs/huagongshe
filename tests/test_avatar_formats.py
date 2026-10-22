"""头像解码白名单：前端允许的类型之外一律按无法识别处理。"""

import io
import unittest

from fastapi import HTTPException
from PIL import Image

from api.users import avatar_variants


def _encode(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


class AvatarSourceFormatsTest(unittest.TestCase):
    def test_whitelisted_formats_decode_to_variants(self):
        for fmt in ("JPEG", "PNG", "WEBP"):
            with self.subTest(fmt=fmt):
                variants = avatar_variants(_encode(fmt))
                self.assertEqual(sorted(variants), [128, 512])
                for size, blob in variants.items():
                    out = Image.open(io.BytesIO(blob))
                    self.assertEqual(out.format, "WEBP")
                    self.assertEqual(out.size, (size, size))

    def test_formats_outside_frontend_whitelist_rejected(self):
        for fmt in ("GIF", "BMP", "TIFF"):
            with self.subTest(fmt=fmt):
                with self.assertRaises(HTTPException) as ctx:
                    avatar_variants(_encode(fmt))
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertEqual(ctx.exception.detail["kind"], "avatar_unrecognized")

    def test_non_image_bytes_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            avatar_variants(b"not an image at all")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["kind"], "avatar_unrecognized")


if __name__ == "__main__":
    unittest.main()
