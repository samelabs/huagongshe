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

## Testing

```bash
# Backend tests
cd /var/www/huagongshe
source venv/bin/activate
./venv/bin/python -m unittest discover -s tests
```

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
