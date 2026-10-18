#!/usr/bin/env python3
"""注释与文案词表检查：只查新增行，拦过程语言回流。

编号代号（问题单/批次/轮次）与决策过程用语不得再进代码注释、文案
与文档——它们在仓库里已被清理为领域语言。检查范围限定为相对基线
分支的新增行，存量不追溯。

用法：
    python scripts/check_comment_vocabulary.py [--base origin/main]
    python scripts/check_comment_vocabulary.py --all   # 全量扫描（对空树做差）
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 按门禁词表：编号系、轮次、裁定与「日期+裁定」组合
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("问题单编号", re.compile(r"\bI-\d{2,4}\b")),
    ("审计条目编号", re.compile(r"\bHGS-[A-Z0-9]+(?:-[A-Z0-9]+)*-[0-9]{2}\b")),
    ("PR 编号", re.compile(r"\bPR\d+-")),
    ("批次编号 P数字-数字", re.compile(r"\bP\d+-\d+\b")),
    ("批次编号 B数字-数字", re.compile(r"\bB\d+-\d+\b")),
    ("批次编号 G数字.R", re.compile(r"\bG\d+\.R\b")),
    ("批次编号 E数字-B", re.compile(r"\bE\d+-B\b")),
    ("轮次", re.compile(r"轮次")),
    ("裁定", re.compile(r"裁定")),
    ("日期+裁定", re.compile(
        r"(?:20\d{2}[-年/]\d{1,2}[-月/]\d{1,2})[^\n]{0,16}裁定"
        r"|裁定[^\n]{0,16}(?:20\d{2}[-年/]\d{1,2}[-月/]\d{1,2})")),
    # ── 残句形态（机械删词后留下的坏句，只查注释段）──
    # 版本演变引用（v1.x / 某版本起）
    ("版本演变", re.compile(r"\bv\d+\.\d+\b")),
    # 空括号：全角（）不论前一字符是什么都算命中；半角 () 前后不贴
    # 字词字符（foo() 是函数名不算）；括号内以分隔标点开头也算
    # （冒号后须跟空白，(:param) 是 SQL 具名参数不算）
    ("残句空括号", re.compile(r"[（]\s*[）)]|(?<![\w.])[(]\s*[)](?![\w])|[（(]\s*(?:[,;，；]|[：:]\s)")),
    # 注释以悬空冒号或"数字:"开头（删编号后残留）。冒号后须是空白或
    # 非 ASCII 字符：(:param) 是 SQL 具名参数、1:1 是比值，都不算
    ("残句悬空开头", re.compile(r"^\s*[：:](?:\s|[^\x00-\x7f])|^\s*\d+\s*[：:](?!\d)")),
    # 内部代号与注释内日期（只查注释段；代码字符串里的值不算）
    ("内部代号 ZX", re.compile(r"\bZX\b")),
    ("条目编号 F 数字", re.compile(r"\bF-\d{2}\b")),
    ("批次代号 M 数字", re.compile(r"\bM\d\b")),
    ("注释内日期", re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")),
]

# 领域语言里的合法用词（化合物身份治理的人工决断语义），不属过程引用
ALLOW_PHRASES = ("需人工裁定", "身份裁定", "身份未裁定", "参与裁定", "裁决")

# 不检查的路径：历史迁移档案（内容冻结）、验收工作区、依赖产物、
# 本脚本自身（词表模式定义必须包含被禁词）
EXCLUDED_PARTS = ("migrations/history/", ".rc-acceptance/", "node_modules/",
                  "package-lock.json", "scripts/check_comment_vocabulary.py")


def _docstring_lines(path: str) -> set[int]:
    """py 文件的 docstring 行集（模块/类/函数首语句），用于把新增的
    docstring 行也纳入残句判定。文件读不了（已删除等）返回空集。"""
    cache = getattr(_docstring_lines, "_cache", None)
    if cache is None:
        cache = _docstring_lines._cache = {}
    if path in cache:
        return cache[path]
    import ast

    lines: set[int] = set()
    target = REPO / path
    if target.exists():
        try:
            tree = ast.parse(target.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = getattr(node, "body", None)
                    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                            and isinstance(body[0].value.value, str):
                        lines.update(range(body[0].lineno, body[0].end_lineno + 1))
    cache[path] = lines
    return lines


def _comment_segment(path: str, line: str, lineno: int = 0) -> str | None:
    """取该行的注释文本（剥掉注释标记）；非注释行返回 None。"""
    stripped = line.strip()
    if path.endswith(".py"):
        pos = line.find("#")
        if pos >= 0 and (pos == 0 or line[pos - 1] in " \t"):
            return line[pos + 1:]
        return line if lineno in _docstring_lines(path) else None
    if path.endswith((".yml", ".yaml")):
        return stripped[1:] if stripped.startswith("#") else None
    if path.endswith((".ts", ".tsx", ".js", ".mjs", ".cjs")):
        if stripped.startswith("//"):
            return stripped[2:]
        # 块注释（含 JSDoc 首行与续行）；行中形态只认 JSX 的 {/* ——
        # 路径串里的 "/mcp/*" 之类不是注释
        if stripped.startswith("/*"):
            return stripped[2:]
        if stripped.startswith("*"):
            return stripped[1:]
        if stripped.startswith("{/*"):
            return stripped[3:]
        pos = line.find(" // ")
        return line[pos + 3:] if pos >= 0 else None
    if path.endswith(".conf"):
        return stripped[1:] if stripped.startswith("#") else None
    if path.endswith(".css"):
        if stripped.startswith("/*"):
            return stripped[2:]
        return stripped[1:] if stripped.startswith("*") else None
    if path.endswith(".sql"):
        pos = line.find("--")
        return line[pos + 2:] if pos >= 0 else None
    if path.endswith(".md"):
        return line
    return None


COMMENT_ONLY_PATTERNS = {"版本演变", "残句空括号", "残句悬空开头",
                         "内部代号 ZX", "条目编号 F 数字", "批次代号 M 数字",
                         "注释内日期"}


def merge_base(base: str) -> str:
    result = subprocess.run(
        ["git", "merge-base", base, "HEAD"], cwd=REPO,
        capture_output=True, text=True, check=True)
    return result.stdout.strip()


def added_lines(base_commit: str):
    diff = subprocess.run(
        ["git", "diff", "-U0", base_commit, "--", "."], cwd=REPO,
        capture_output=True, text=True, check=True).stdout
    current = None
    lineno = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            lineno = int(match.group(1)) if match else 0
            continue
        if line.startswith("+") and current is not None:
            yield current, lineno, line[1:]
            lineno += 1


def empty_tree() -> str:
    """当前对象库的空树哈希（--all 全量模式对它做差 = 每一行都是新增）。"""
    result = subprocess.run(
        ["git", "hash-object", "-t", "tree", "/dev/null"], cwd=REPO,
        capture_output=True, text=True, check=True)
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main",
                        help="基线分支/提交（默认 origin/main）")
    parser.add_argument("--all", action="store_true",
                        help="全量扫描（对空树做差）；额外排除 CHANGELOG.md、docs/、migrations/")
    args = parser.parse_args()

    excluded = list(EXCLUDED_PARTS)
    try:
        base_commit = empty_tree() if args.all else merge_base(args.base)
    except subprocess.CalledProcessError:
        print(f"无法解析基线 {args.base}（本地无该引用时请先 fetch）")
        return 2
    if args.all:
        # 过程档案与历史迁移不参与全量清零；命中清单在验收回执中单列报告
        excluded += ("CHANGELOG.md", "docs/", "migrations/")

    violations: list[str] = []
    for path, lineno, text in added_lines(base_commit):
        if any(part in path for part in excluded):
            continue
        if any(phrase in text for phrase in ALLOW_PHRASES):
            continue
        segment = _comment_segment(path, text, lineno)
        for name, pattern in PATTERNS:
            # 残句类只在注释文本上判；其余（编号/轮次/裁定）整行判
            target = segment if name in COMMENT_ONLY_PATTERNS else text
            if target and pattern.search(target):
                violations.append(f"{path}:{lineno} [{name}] {text.strip()[:100]}")
                break

    if violations:
        print("新增行包含过程语言（编号代号与决策过程用语），请改写为领域语言：")
        for item in violations:
            print(f"  {item}")
        return 1
    mode = "全量" if args.all else "新增"
    print(f"词表检查通过（{mode}扫描，基线 {base_commit[:10]}，无过程语言）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
