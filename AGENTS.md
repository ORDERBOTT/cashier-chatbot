# Repository Guidelines

## Project Structure & Module Organization
`src/main.py` is the FastAPI entry point. Core application code lives in `src/chatbot/` for conversation flow, tool logic, and AI integrations, and `src/menu/` for menu loading, pricing, and ingest routes. Shared infrastructure sits in files such as `src/config.py`, `src/cache.py`, `src/firebase.py`, and `src/database.py`. Keep browser-facing assets in `templates/`, seed and maintenance utilities in `scripts/`, menu data in `data/`, and automated tests in `tests/` plus `tests/tools/`.

## Build, Test, and Development Commands
Use `uv sync` to install pinned dependencies from `uv.lock`. Run the API locally with `uvicorn src.main:app --reload`. Lint with `ruff check .`, auto-fix safe issues with `ruff check --fix .`, and format with `ruff format .`. Run the full test suite with `pytest`. Database migrations are scaffolded, not central to the app today, but the standard commands are `alembic upgrade head` and `alembic revision --autogenerate -m "message"`.

## Coding Style & Naming Conventions
Follow Python 3.13 conventions with 4-space indentation, type hints, and Ruff-managed formatting. Match the existing module layout: feature packages typically use `router.py`, `schema.py`, `service.py`, `exceptions.py`, and related helpers. Use `snake_case` for modules, functions, and variables, `PascalCase` for classes, and keep FastAPI handlers and service functions `async` to stay consistent with the codebase’s async design.

## Testing Guidelines
Place tests under `tests/` and name files `test_*.py`; tool-specific coverage belongs in `tests/tools/`. Prefer focused pytest cases that exercise pricing, order-state transitions, and menu-matching edge cases using fixtures in `tests/fixtures/` or sample JSON in `tests/`. There is no published coverage threshold, so treat changed behavior as requiring corresponding tests before merge.

## Commit & Pull Request Guidelines
Recent commits use short, lowercase, imperative-style summaries such as `improved modifier flow` and `read me updated`. Keep commit subjects brief and specific. PRs should explain the user-visible behavior change, list the commands run (`pytest`, `ruff check .`), call out any `.env`, Redis, Firebase, or menu-data impacts, and include screenshots only when `templates/index.html` or other UI behavior changes.

## Configuration & Safety Notes
Secrets belong in `.env` and must not be committed. The app loads menu data from `data/inventory.json`, and current startup behavior flushes Redis, so use a dedicated Redis database during development.
