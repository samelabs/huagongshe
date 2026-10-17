#!/usr/bin/env python3
"""注释与文案词表检查：只查新增行，拦过程语言回流。

编号代号（问题单/批次/轮次）与决策过程用语不得再进代码注释、文案
与文档——它们在仓库里已被清理为领域语言。检查范围限定为相对基线
分支的新增行，存量不追溯。

用法：
    python scripts/check_comment_vocabulary.py [--base origin/main]
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
]

# 领域语言里的合法用词（化合物身份治理的人工决断语义），不属过程引用
ALLOW_PHRASES = ("需人工裁定", "身份裁定", "身份未裁定", "参与裁定", "裁决")

# 不检查的路径：历史迁移档案（内容冻结）、验收工作区、依赖产物
# 不检查的路径：历史迁移档案（内容冻结）、验收工作区、依赖产物、
# 本脚本自身（词表模式定义必须包含被禁词）
EXCLUDED_PARTS = ("migrations/history/", ".rc-acceptance/", "node_modules/",
                  "package-lock.json", "scripts/check_comment_vocabulary.py")


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main",
                        help="基线分支/提交（默认 origin/main）")
    args = parser.parse_args()

    try:
        base_commit = merge_base(args.base)
    except subprocess.CalledProcessError:
        print(f"无法解析基线 {args.base}（本地无该引用时请先 fetch）")
        return 2

    violations: list[str] = []
    for path, lineno, text in added_lines(base_commit):
        if any(part in path for part in EXCLUDED_PARTS):
            continue
        if any(phrase in text for phrase in ALLOW_PHRASES):
            continue
        for name, pattern in PATTERNS:
            if pattern.search(text):
                violations.append(f"{path}:{lineno} [{name}] {text.strip()[:100]}")
                break

    if violations:
        print("新增行包含过程语言（编号代号与决策过程用语），请改写为领域语言：")
        for item in violations:
            print(f"  {item}")
        return 1
    print(f"词表检查通过（基线 {base_commit[:10]}，无新增过程语言）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
