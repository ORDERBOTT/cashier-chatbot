# FastAPI Project Starter

A production-ready FastAPI backend boilerplate with async SQLAlchemy, Alembic migrations, and developer tooling.

## Quick Start

```bash
# Install dependencies
pip install -r requirements/base.txt

# Set environment variables (see .env.example if available)
export DATABASE_URL="postgresql+asyncpg://user:pass@localhost/dbname"
export REDIS_URL="redis://localhost:6379/0"

# Run the server
uvicorn src.main:app --reload
```

## Project Structure

```
fastapi-backend-boilerplate/
├── alembic/              # Database migrations
│   ├── env.py            # Alembic environment config
│   ├── script.py.mako    # Migration script template
│   └── versions/         # Generated migration files
├── alembic.ini           # Alembic configuration
├── requirements/
│   ├── base.txt          # Core dependencies
│   ├── dev.txt           # Development tools
│   └── production.txt    # Production extras
├── scripts/
│   ├── create_app.py     # Scaffold new app modules
│   └── init_ai.py        # Initialize AI module structure
├── src/
│   ├── config.py         # Pydantic settings (env vars)
│   ├── constants.py      # Shared constants (e.g. Environment enum)
│   ├── database.py       # Async SQLAlchemy engine & session
│   ├── exceptions.py     # Custom exception handlers
│   ├── main.py           # FastAPI app entry point
│   └── models.py         # SQLAlchemy models
└── templates/
    └── index.html        # Static/HTML templates
```

## Scripts

### `create_app.py` — Scaffold New App Modules

Creates a full module layout under `src/<app_name>/` with router, schemas, models, service, and tests.

```bash
python scripts/create_app.py users
```

This generates:

- `src/users/` with: `router.py`, `schema.py`, `models.py`, `dependencies.py`, `config.py`, `constants.py`, `exceptions.py`, `service.py`, `utils.py`
- `tests/users.py` with a basic TestClient test

Then wire the router in `src/main.py`:

```python
from src.users.router import router
app.include_router(router)
```

### `init_ai.py` — Initialize AI Module Structure

Sets up an AI-focused module structure under `src/ai/` for agents, RAG, and MCP integrations.

```bash
python scripts/init_ai.py
```

Creates:

- `src/ai/clients/`, `prompts/`, `schemas/`, `retrieval/`, `services/`, `tools/`, `tools/local/`, `tools/mcp/`
- `src/ai/policies.py`, `config.py`, `exceptions.py`

---

## Ruff

[Ruff](https://docs.astral.sh/ruff/) is included as the linter and formatter. It’s fast and replaces tools like Flake8, isort, and Black.

**Commands:**

```bash
ruff check .           # Lint
ruff check --fix .     # Lint and auto-fix
ruff format .          # Format code
```

**Alembic integration:** You can auto-lint new migrations by uncommenting the Ruff post-write hook in `alembic.ini`:

```ini
[post_write_hooks]
hooks = ruff
ruff.type = module
ruff.module = ruff
ruff.options = check --fix REVISION_SCRIPT_FILENAME
```

---

## Alembic

[Alembic](https://alembic.sqlalchemy.org/) is used for SQLAlchemy database migrations.

**Initial setup:**

1. Set `sqlalchemy.url` in `alembic.ini` or load it from your config (e.g. via `env.py` from `src.config`).
2. Point `target_metadata` in `alembic/env.py` at your models’ metadata so autogenerate can detect schema changes:

```python
from src.database import Base
target_metadata = Base.metadata
```

**Common commands:**

```bash
alembic revision --autogenerate -m "Add users table"  # Generate migration from models
alembic upgrade head                                 # Apply all migrations
alembic downgrade -1                                 # Roll back one revision
alembic current                                     # Show current revision
```

---

## Configuration

The app uses Pydantic Settings for configuration. Required env vars:

| Variable      | Description                    |
|---------------|--------------------------------|
| `DATABASE_URL`| PostgreSQL (e.g. `postgresql+asyncpg://...`) |
| `REDIS_URL`   | Redis connection string        |
| `ENVIRONMENT` | `development`, `staging`, or `production` (optional, defaults to `development`) |

---

## License

MIT
