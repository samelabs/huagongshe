"""E7 §2/§3/§4/§11 — fixture 可复现性与测试环境卫生闸。

锁:
1. tests/ 内不得再出现仓库外 fixture 路径(个人 HOME / ~/ops / /tmp 预置样本);
2. 相关测试引用的样本常量必须落在仓库 tests/fixtures/ 且文件真实存在;
3. 原先因外部样本缺失而 skip 的测试现在必须真跑(不得用 SkipTest 换写法藏起来);
4. skill 目录不得在测试结束后留下新残留(/tmp/g0a_skills_a1 类残留的 owner 已修)。

结构断言优先于文案: 扫描的是路径形态与真实执行结果, 不是某句中文是否存在。
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.db_gate import test_db_or_skip  # noqa: E402

TESTS_DIR = REPO / "tests"
FIXTURE_DIR = TESTS_DIR / "fixtures"

# 禁止形态: 仓库外 fixture 路径(拼接构造, 避免本文件自匹配)
FORBIDDEN = (
    "expanduser(" + "\"~",
    "expanduser(" + "'~",
    "/tmp/" + "cpp_",
    "/tmp/" + "chem_",
    "/tmp/" + "cas_",
    "/tmp/" + "CAS_",
    "/tmp/" + "g0a_",
    "~/" + "ops",
)


def _code_lines(path: Path):
    """只扫描代码行: 用 tokenize 排除注释与字符串(含 docstring)。

    文档里出现历史路径说明(例如"原先读 ~/ops 下的样本")不算代码依赖;
    只有真正的代码行才算 —— 避免把注释/文案当成依赖证据。
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    skip: set[int] = set()
    try:
        import io
        import tokenize
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                for ln in range(tok.start[0], tok.end[0] + 1):
                    skip.add(ln)
    except Exception:  # noqa: BLE001  tokenize 失败则退化为逐行扫描
        skip = set()
    for n, raw in enumerate(lines, 1):
        if n in skip:
            continue
        line = raw.strip()
        if line:
            yield n, line


class NoExternalFixturePathsTests(unittest.TestCase):
    def test_tests_dir_has_no_external_fixture_paths(self):
        hits: list[str] = []
        for path in sorted(TESTS_DIR.glob("*.py")):
            if path.resolve() == Path(__file__).resolve():
                continue  # 本闸自身持有禁止形态字面量
            for n, line in _code_lines(path):
                for pat in FORBIDDEN:
                    if pat in line:
                        hits.append(f"{path.name}:{n}: {pat}")
        self.assertEqual(hits, [], "tests/ 仍依赖仓库外 fixture 路径")


class FixtureLocationTests(unittest.TestCase):
    def test_caslib_fixture_dir_is_repo_relative(self):
        from tests import test_caslib
        self.assertTrue(
            Path(test_caslib.FIXTURES).resolve().is_relative_to(FIXTURE_DIR.resolve()),
            f"caslib fixtures 不在仓库内: {test_caslib.FIXTURES}")
        self.assertTrue(Path(test_caslib.FIXTURES).is_dir())

    def test_cb_mol_fixture_constants_are_in_repo(self):
        from tests import test_cb_mol
        for name in ("FIXTURE", "FIXTURE_HTML", "FIXTURE_CPP_CN", "FIXTURE_CPP_EN"):
            p = Path(getattr(test_cb_mol, name))
            self.assertTrue(p.resolve().is_relative_to(FIXTURE_DIR.resolve()), name)
            self.assertTrue(p.is_file(), f"{name} 不存在: {p}")

    def test_caslib_requires_all_samples_present(self):
        """_require_fixtures 是硬失败(不是 skip): 缺样本直接 AssertionError。"""
        from tests import test_caslib
        test_caslib._require_fixtures(
            "CAS_65-85-0.htm", "CAS_67-64-1.htm", "CAS_50-00-7.htm",
            "CAS_99999-99-9.htm", "CAS_69-72-7.htm", "CAS_77-92-9.htm")
        with self.assertRaises(AssertionError):
            test_caslib._require_fixtures("CAS_0000000-00-0.htm")

    def test_all_fixture_files_are_non_empty(self):
        files = sorted(p for p in FIXTURE_DIR.iterdir() if p.is_file())
        self.assertGreaterEqual(len(files), 6, [p.name for p in files])
        empty = [p.name for p in files if p.stat().st_size == 0]
        self.assertEqual(empty, [], "fixture 空文件")


class FormerlySkippedTestsRunTests(unittest.TestCase):
    """原外部样本缺失而 skip 的用例, 现在必须真跑(0 skip / 0 failure)。"""

    def _run_modules(self, names: tuple[str, ...]):
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for name in names:
            suite.addTests(loader.loadTestsFromName(name))
        result = unittest.TextTestRunner(verbosity=0).run(suite)
        return result

    def test_caslib_and_cb_mol_run_without_skips(self):
        result = self._run_modules(
            ("tests.test_caslib", "tests.test_cb_mol"))
        self.assertEqual(result.skipped, [], [str(s[0]) for s in result.skipped])
        self.assertTrue(result.wasSuccessful(),
                        f"failures={result.failures} errors={result.errors}")
        self.assertGreaterEqual(result.testsRun, 20)


class SkillRootResidueTests(unittest.TestCase):
    """§4: skill 目录残留 owner 已修 —— 真跑 owner 用例, 断言零新增残留。"""

    LEAKERS = (
        "tests.test_token_revoke_idempotency.SkillsRaceTests."
        "test_concurrent_same_key_returns_same_skill",
        "tests.test_token_revoke_idempotency.SkillsRaceTests."
        "test_no_key_conflict_still_raises",
    )

    def test_owner_tests_leave_no_new_skill_dirs(self):
        test_db_or_skip()
        from api.core.config import settings

        root = Path(settings.skill_root)
        before = set(root.iterdir()) if root.is_dir() else set()

        loader = unittest.TestLoader()
        suite = unittest.TestSuite(
            loader.loadTestsFromName(name) for name in self.LEAKERS)
        result = unittest.TextTestRunner(verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(),
                        f"failures={result.failures} errors={result.errors}")

        after = set(root.iterdir()) if root.is_dir() else set()
        new = sorted(p.name for p in (after - before))
        self.assertEqual(new, [], f"skill_root 新残留: {new} (root={root})")

    def test_skill_root_is_configured_path(self):
        """残留检查的对象必须是 settings.skill_root(而不是猜的目录)。"""
        from api.core.config import settings
        from api.services.skills import skill_fs_dir
        d = Path(skill_fs_dir(424242))
        self.assertEqual(d.parent, Path(settings.skill_root))


if __name__ == "__main__":
    unittest.main()
