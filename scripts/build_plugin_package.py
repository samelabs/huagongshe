"""打包 Agent Plugin 下载包: plugins/huagongshe → web/public/downloads/*.zip。

下载包是代码的一部分, 随仓库提交、随部署发布, 不在服务器上手动放置。
plugins/huagongshe 有改动时重跑本脚本并提交产物; 一致性由
tests/test_plugin_package.py 校验。

    python scripts/build_plugin_package.py
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "plugins" / "huagongshe"
OUT_DIR = REPO / "web" / "public" / "downloads"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # 固定时间戳: 同一源文件 → 同一字节产物


def package_path() -> Path:
    version = json.loads((SOURCE / "plugin.json").read_text(encoding="utf-8"))["version"]
    return OUT_DIR / f"huagongshe-agent-plugin-{version}.zip"


def source_files() -> list[Path]:
    return sorted(p for p in SOURCE.rglob("*") if p.is_file())


def build() -> Path:
    out = package_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in source_files():
            info = zipfile.ZipInfo(path.relative_to(SOURCE).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return out


if __name__ == "__main__":
    print(build().relative_to(REPO))
