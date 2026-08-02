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

# Apply migrations in order
psql huagongshe -f migrations/20260720_unify_core_schemas.sql
# ... continue with remaining migration files in chronological order
```

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

## Architecture

```
api/          FastAPI backend (Python, async)
  routes.py     Chemicals CRUD, search, stats
  reactions.py  Reactions CRUD, participants
  users.py      Auth, profiles, settings
  workapi.py    Worker maintenance API (job queue)
  enrichment.py PubChem data backfill logic
  mol.py        RDKit SVG rendering
  social.py     Follows, activity feed
  cache.py      Redis cache client
  security.py   Session + API key auth
web/          Next.js 16 frontend (TypeScript)
worker/       PubChem enrichment worker (independent process)
migrations/   PostgreSQL schema migrations
tests/        Backend pytest tests
```

### Data Flow

```
User/Bot → nginx → Next.js SSR → FastAPI API → PostgreSQL
                                          ↘ Redis (cache)
                                          ↘ RDKit (SVG render)
                  Worker ← job queue ← API (enrichment trigger)
```

## Code Standards

### Backend (Python)

- **Async first**: all endpoints are `async def`. CPU-bound work (RDKit) uses `asyncio.to_thread`.
- **SQL**: parameterized queries via SQLAlchemy `text()` with named params. Never string interpolation.
- **Cache failures must not change results**: Redis is best-effort. A cache miss or error returns the database result, never an exception to the user.
- **Layering**: API routes → enrichment/cache/database. No upward imports.

### Frontend (TypeScript)

- All text inputs ≥ 16px (prevents iOS Safari focus-zoom).
- `"use client"` components for interactive elements (FollowButton, etc).
- Design tokens from `globals.css`, not hardcoded colors.

### Database

- Three schemas: `chemistry` (core data), `community` (users/social), `maintenance` (worker queue).
- `chemistry.chemicals` is the identity backbone. PubChem/DSSTox/ORD/RDKit are sources only.
- Migrations are sequential SQL files in `migrations/`.

## Testing

```bash
# Backend tests
cd /var/www/huagongshe
source venv/bin/activate
pytest tests/
```

Test files: `test_reactions.py`, `test_search.py`, `test_security.py`, `test_worker.py`.

## Pull Request Process

1. **Branch** from `main` (`git checkout -b feature/your-feature`)
2. **Test**: ensure `pytest tests/` passes
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
