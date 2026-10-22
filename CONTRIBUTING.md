# Contributing to Huagongshe

Thank you for your interest in contributing. This document covers the essentials.
开发与测试运行的权威手册是 `docs/TESTING.md`; 本文件只保留贡献流程要点。

## Development Setup

本地开发使用受管的 Docker 栈 + 宿主前端(唯一入口), 不手装散件服务:

```bash
git clone <repo-url>
cd huagongshe

# 本地栈: db(pg16+rdkit) / redis / api, 全部 127.0.0.1(见 local/README.md)
cd local/stack
cp .env.local.example .env.local    # 改掉 change-me 假值
docker compose --env-file .env.local up -d --build

# 前端依赖(宿主 Node ≥22 系列, 与 CI 基准一致)
cd ../../web && npm ci

# 前端唯一入口(next dev 3000 + uploads 3010)
cd .. && local/dev.sh
```

数据库 schema 由栈首次启动自动初始化(baseline + bootstrap + forward);
迁移规则(顺序、命名、history 边界)见 `migrations/README.md`。

### Environment

生产环境变量从 `ecosystem.config.cjs.example` 起步; 生产 secrets 放
`/etc/huagongshe.env`(chmod 600, never committed)。生产部署命令在
`docs/DEPLOYMENT.md`, 不要在本地用生产命令跑开发实例。

## Testing

测试分级(最小充分集)与全部运行细节见 `docs/TESTING.md`。要点:

| 改动类型 | 必跑 |
|---|---|
| 只改文案 | `python3 local/check.py web` 中的 test:locale + tsc |
| 改前端组件或样式 | 再加 test:unit、check:api-layer、`tests.test_ui_token_contract`、`tests.test_style_ratchet`, 只截改到的页面 |
| 改后端 | `python3 local/check.py backend --tests tests.<涉及模块> …` + 直接相关回归 |
| 数据库迁移 | run 专有库经 `scripts/migrate.py` 正向执行一次, 附执行输出 |

跨全局契约变更(错误响应格式、对外接口面、被删除的函数或字符串)不适用
上表最小集:「涉及的测试」要用 grep 找全 —— 凡引用了被改字符串、被删
符号的测试文件都要跑(例: `grep -rn "被改的旧文案" tests/`), 否则只跑
表面相关的文件会漏, 最终 CI 才暴露批量红。

全量测试只在两处各跑一次: CI 与 `python3 local/check.py release` 发布
门禁; 全量截图只在发布门禁跑一次。日常 PR 与本地开发不得跑全量。

## Pull Request Process

1. **Branch**: 以当前在飞基座建分支 — 有未合入 `origin/main` 的在飞批次
   线时必须叠在其上(`git checkout -b <new> <在飞分支>`), 不从旧 main
   起头丢修复(详见根 AGENTS.md「分支对齐与基座」)。
2. **Test**: 按上表最小充分集跑绿后再提交; `git commit` 不盲排在测试
   命令之后。
3. **Commit**: clear messages with type prefix (`feat:`, `fix:`,
   `refactor:`, `docs:`).
4. **PR**: describe what changed and why.

### Commit Message Format

```
type: short description

Optional longer explanation.
```

Types: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`.

## Reporting Security Issues

Do not open a public issue for security vulnerabilities. Email the maintainers directly.

## License

By contributing, you agree that your contributions are licensed under the project's license.
