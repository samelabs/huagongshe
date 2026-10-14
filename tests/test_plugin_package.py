"""Agent Plugin 下载包与 plugins/huagongshe 源文件一致(防止包与源漂移)。"""
import unittest
import zipfile

from scripts.build_plugin_package import SOURCE, package_path, source_files


class PluginPackageTests(unittest.TestCase):
    def test_package_matches_source(self):
        out = package_path()
        self.assertTrue(out.is_file(), f"缺少下载包 {out}; 运行 scripts/build_plugin_package.py")
        with zipfile.ZipFile(out) as zf:
            packed = {name: zf.read(name) for name in zf.namelist()}
        expected = {p.relative_to(SOURCE).as_posix(): p.read_bytes() for p in source_files()}
        self.assertEqual(sorted(packed), sorted(expected))
        for name, data in expected.items():
            self.assertEqual(packed[name], data, f"{name} 与源文件不一致; 重跑打包脚本")


if __name__ == "__main__":
    unittest.main()
