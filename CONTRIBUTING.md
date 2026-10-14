# Contributing to Huagongshe

Thank you for your interest in contributing. This document covers the essentials.

## Development Setup

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 16+
- Redis

### Backend (FastAPI)

```bash
git clone <repo-url>
cd huagongshe

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Frontend (Next.js)

```bash
cd web
npm install
```

### Database

```bash
createdb huagongshe

psql huagongshe -f migrations/0000_baseline.sql
psql huagongshe -f migrations/0001_bootstrap_reference_data.sql
```

Migration 规则（顺序、命名、history 边界）见 `migrations/README.md`。

### Environment

Copy `ecosystem.config.cjs.example` and fill in required variables.
Production secrets live in `/etc/huagongshe.env` (chmod 600, never committed).

### Run locally

```bash
# API
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend
cd web && npm run dev

# Worker (optional, for PubChem enrichment)
python -m worker.main
```

## Testing

测试分级（固定规范，2026-10-14 起）——按改动类型选择最小充分集，不随手跑全量：

| 改动类型 | 必跑 |
|---|---|
| 只改文案 | `test:locale` + `tsc` |
| 改前端组件或样式 | 前者之外再加 `test_ui_token_contract`，只截改到的页面 |
| 改后端 | 只跑涉及的测试文件 + 直接相关的回归 |
| 数据库迁移 | 经 `scripts/migrate.py` 在测试库正向执行一次，附执行输出 |

```bash
# Backend tests（改后端时：只跑涉及的文件，例如）
cd /var/www/huagongshe
source venv/bin/activate
./venv/bin/python -m pytest tests/test_reactions.py tests/test_search.py -v

# DB integration tests 需要过闸的测试库（tests/db_gate.py）
TEST_DATABASE_URL='postgresql://...test_hgs?test_sentinel=hgs-test-db' \
  ./venv/bin/python -m pytest tests/test_xxx.py

# 迁移在测试库正向执行
./venv/bin/python scripts/migrate.py "postgresql://user:pass@host:5432/test_hgs"
```

全量测试只在两处各跑一次：CI 与发布门禁；全量截图只在发布门禁跑一次。日常
PR 与本地开发不得跑全量。

Test files: `test_reactions.py`, `test_search.py`, `test_security.py`, `test_worker.py`.

## Pull Request Process

1. **Branch** from `main` (`git checkout -b feature/your-feature`)
2. **Test**: ensure `./venv/bin/python -m unittest discover -s tests` passes
3. **Build**: ensure `cd web && npm run build` succeeds
4. **Commit**: clear messages with type prefix (`feat:`, `fix:`, `refactor:`, `docs:`)
5. **PR**: describe what changed and why

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
