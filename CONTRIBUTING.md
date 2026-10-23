# Contributing to Huagongshe

开发与测试的权威手册是 `docs/TESTING.md`; 部署与生产基线见
`docs/DEPLOYMENT.md`、`docs/PRODUCTION_BASELINE.md`。本文件只保留贡献流程要点。

## Development Setup

本地开发使用受管的 Docker 栈 + 宿主前端(唯一入口):

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
`/etc/huagongshe.env`(chmod 600, 永不入库)。生产部署流程见
`docs/DEPLOYMENT.md`。

## Testing

按 `docs/TESTING.md` 的测试分级表选最小充分集跑绿后提交; 全量只在 CI
与 `python3 local/check.py release` 发布门禁各跑一次。

## Pull Request Process

1. **Branch**: 以当前在飞基座建分支 — 有未合入 `origin/main` 的在飞批次
   线时必须叠在其上(`git checkout -b <new> <在飞分支>`), 详见根
   AGENTS.md「分支对齐与基座」。
2. **Test**: 最小充分集跑绿后再提交; `git commit` 排在测试之后。
3. **Commit**: `type: short description` — `feat` / `fix` / `refactor` /
   `docs` / `chore` / `test`。

## Reporting Security Issues

安全漏洞不走公开 issue, 直接邮件维护者。
