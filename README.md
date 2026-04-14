# Cashier Chatbot

FastAPI backend for an AI-assisted restaurant cashier: natural-language ordering, menu Q&A, restaurant Q&A, pickup cues, and staff escalation. The browser UI is a small vanilla-JS page served from `templates/index.html`.

## Contents

- [Stack](#stack)
- [Architecture (request path)](#architecture-request-path)
- [Conversation states](#conversation-states)
- [Setup](#setup)
- [Running the server](#running-the-server)
- [Project structure](#project-structure-high-level)
- [Development commands](#development-commands)

---

## Stack

| Layer | Choice |
|--------|--------|
| Runtime | Python 3.13 |
| Web | FastAPI, Uvicorn, Starlette |
| LLM | [Google Gen AI SDK](https://github.com/googleapis/python-genai) (`google-genai`) — model name from `GEMINI_MODEL` (default in code: `gemini-3-flash-preview`) |
| Structured output | Pydantic v2 schemas + Gemini JSON / text helpers in `src/chatbot/gemini_client.py` |
| Menu in memory | `data/inventory.json` loaded at startup (`src/menu/loader.py`) |
| Menu persistence (ingest) | Firebase Admin → Async Firestore (`src/firebase.py`, `src/menu/sync.py`) |
| Cache / summaries | Redis (`src/cache.py`) — conversation summaries and optional restaurant profile overrides |
| Fuzzy matching | RapidFuzz (`src/chatbot/clarification/`) |
| Tooling | [uv](https://github.com/astral-sh/uv), Ruff, pytest |
| DB (scaffold) | SQLAlchemy async + Alembic under `src/database.py` / `alembic/` — **not** wired into `src/main.py` today |

---

## Architecture (request path)

```
Browser
  POST /api/bot/message  (BotInteractionRequest)
       │
       ▼
ChatReplyService  (src/chatbot/infrastructure/service.py)
  │
  ├─ compress_history_if_needed  — long histories → Redis-backed summary + recent tail
  │     (src/chatbot/infrastructure/summarizer.py)
  │
  ├─ ConversationStateResolver  — intent → ConversationState (high confidence + valid transition)
  │     (src/chatbot/intent/resolver.py, ai_client.py, transitions.py)
  │
  └─ StateHandlerFactory  — reply per conversation state
        (src/chatbot/visibility/handlers.py)
        │
        ├─ greeting / farewell / vague / misc / human_escalation / pickup_* / order_*  → visibility AI helpers
        ├─ restaurant_question / menu_question  → context + Gemini replies
        └─ food_order  → OrderStateHandler
              (src/chatbot/cart/handlers.py)
              ├─ OrderExtractor  (src/chatbot/extraction/) — deltas, confirmation replies, etc.
              ├─ FuzzyMatcher + ClarificationBuilder  (src/chatbot/clarification/) — menu line matching
              ├─ modifier resolution / pricing  (src/menu/loader.py)
              └─ combos / polish  (src/chatbot/cart/combo_service.py, cart/ai_client.py)
```

**Design notes**

- **Stateless HTTP**: the client sends `message_history`, `order_state`, and `previous_state` each turn; the server does not keep HTTP sessions (Redis is only for summaries and optional cached restaurant fields).
- **Intent gating**: only **high**-confidence intents that satisfy `VALID_TRANSITIONS` are accepted; otherwise the flow falls back to `vague_message`.
- **Menu source of truth for the bot**: in-process menu built from `data/inventory.json` (see [Menu data](#menu-data)). Ingest pushes the same shape to Firestore for storage/sync.

---

## Conversation states

Defined in `src/chatbot/constants.py` (`ConversationState`). High-level set:

`greeting`, `farewell`, `vague_message`, `restaurant_question`, `menu_question`, `food_order`, `pickup_ping`, `pickup_time_suggestion`, `misc`, `human_escalation`, `order_complete`, `order_review`.

Food-order behaviour (extract, match, clarify, finalize) lives under `src/chatbot/cart/` and `src/chatbot/extraction/` rather than a single monolithic handler file.

---

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)
- Redis reachable at the URL you configure
- A **Gemini** API key (`GEMINI_API_KEY`, or `OPENAI_API_KEY` as a supported alias name in code)
- Firebase **service account** fields for Firestore (used by menu ingest)

### Install

```bash
git clone <repo-url>
cd cashier-chatbot
uv sync
```

### Environment variables

Create a `.env` in the project root. These map to `src/config.py` (`Config`).

| Variable | Required | Description |
|----------|----------|-------------|
| `REDIS_URL` | Yes | e.g. `redis://127.0.0.1:6379/0` |
| `GEMINI_API_KEY` | Yes* | Google AI Studio / Gemini API key |
| `OPENAI_API_KEY` | No | Alternative env name read by the same code path if `GEMINI_API_KEY` is unset |
| `GEMINI_MODEL` | No | Overrides default model id from settings |
| `FIREBASE_PROJECT_ID` | Yes | GCP project id |
| `FIREBASE_CLIENT_EMAIL` | Yes | Service account email |
| `FIREBASE_PRIVATE_KEY` | Yes | PEM private key; use `\n` in `.env` for newlines |
| `RESTAURANT_ID` | Yes | Firestore document id under `menus/{RESTAURANT_ID}` when ingesting |
| `ENVIRONMENT` | No | `development` (default), `staging`, or `production` |
| `USER_ID` | No | Optional default used by some helpers |

\*One of `GEMINI_API_KEY` or `OPENAI_API_KEY` must be set so `gemini_client` can authenticate.

> **Note:** `src/database.py` expects `DATABASE_URL` on settings for SQLAlchemy, but `src/main.py` does not import the DB layer. Add `DATABASE_URL` to settings only if you start using the database module or Alembic against a live engine.

### Menu data

1. **Local file (what the bot reads):** `data/inventory.json` — loaded on app startup via `init_menu()` in `src/menu/loader.py`. Ensure this file exists and is valid JSON before running the server.
2. **Firestore sync:** `POST /menu/ingest` accepts an inventory payload, writes categories/items under `menus/{RESTAURANT_ID}` in Firestore (`src/menu/sync.py`), then calls `init_menu()` to refresh the in-memory menu.

Reference payloads: `data/example_menu.json`, `data/normalized_menu.json`.

### Redis and startup behaviour

On startup, `src/main.py`:

1. Connects to Redis  
2. Runs **`FLUSHALL`** (`cache_flush_all`) — **every key in that Redis DB is cleared**  
3. Initializes Firebase and reloads the menu from disk  

Use a dedicated Redis database index (or instance) for this project. After restart, re-seed any optional Redis keys you rely on (see below).

### Optional Redis keys (restaurant profile overrides)

Handlers in `src/chatbot/visibility/` read Redis keys templated with `user_id` when present (see `src/chatbot/visibility/constants.py`), for example:

- `restaurant_name_location:{user_id}` — name and location string  
- `restaurant_context:{user_id}` — free-text context for restaurant Q&A  
- `restaurant_name:{user_id}`, `restaurant_city:{user_id}`, `restaurant_phone:{user_id}`, …  
- `restaurantContext:{user_id}` — JSON blob merged into profile  

If absent, code uses fallbacks or empty profile fields as implemented in `src/chatbot/visibility/utils.py`.

### Legacy seed script

`scripts/seed_menu.py` seeds older `menu_context:*` / `menu_item_names:*` keys from `src/constants.py`. The **live** menu Q&A path uses `get_menu_context()` from `src/menu/loader.py` (inventory file), not those Redis keys. Prefer updating `data/inventory.json` or using `/menu/ingest` for current behaviour.

---

## Running the server

```bash
uvicorn src.main:app --reload
```

Open `http://localhost:8000` — root route serves `templates/index.html`.

### API

**Chat**

`POST /api/bot/message`

Request body (`BotInteractionRequest` in `src/chatbot/schema.py`):

```json
{
  "user_id": "1",
  "latest_message": "I'll have two wings combos please",
  "message_history": [],
  "order_state": null,
  "previous_state": null,
  "customer_name": null
}
```

Response (`ChatbotResponse`):

```json
{
  "chatbot_message": "...",
  "pickup_ping": false,
  "ping_for_human": false,
  "order_state": { "items": [] },
  "previous_state": "food_order",
  "customer_name": null,
  "pickup_time_suggestion": null,
  "pickup_time_suggestion_timestamp": null
}
```

The demo UI may send extra fields (e.g. `awaiting_order_confirmation`); Pydantic ignores unknown keys on the request model.

**Save test transcripts (dev helper)**

`POST /api/bot/save-test-results` — writes `body.content` under `test_results/`.

**Menu ingest**

`POST /menu/ingest` — body is a flat map of item id → inventory item (see `src/menu/schema.py`). Requires Firebase env vars and `RESTAURANT_ID`.

---

## Project structure (high level)

```
cashier-chatbot/
├── data/
│   ├── inventory.json          # Menu loaded into memory at startup
│   ├── example_menu.json
│   └── normalized_menu.json
├── scripts/                    # seed_menu, fetch/build menu helpers, create_app, init_ai, …
├── src/
│   ├── main.py                 # FastAPI app, lifespan (Redis, Firebase, menu init)
│   ├── config.py               # Settings from environment
│   ├── cache.py                # Async Redis helpers
│   ├── firebase.py             # Firebase Admin + Firestore async client
│   ├── database.py             # SQLAlchemy async scaffold (unused by main today)
│   ├── constants.py            # Shared constants (includes legacy menu map for seed script)
│   ├── menu/
│   │   ├── loader.py           # inventory.json → in-memory menu + pricing / modifiers
│   │   ├── router.py           # POST /menu/ingest
│   │   ├── sync.py             # Firestore write path
│   │   └── …
│   └── chatbot/
│       ├── router.py           # /api/bot/*
│       ├── infrastructure/     # ChatReplyService, history summarization
│       ├── intent/             # Conversation-level intent
│       ├── visibility/         # Non-order replies + StateHandlerFactory
│       ├── cart/               # Food order pipeline
│       ├── extraction/         # Structured extraction from user text
│       ├── clarification/      # Fuzzy menu matching + merge/remove builders
│       ├── gemini_client.py    # Shared Gemini calls
│       ├── schema.py           # Request/response Pydantic models
│       └── …
├── templates/index.html
├── tests/
├── pyproject.toml
├── alembic.ini
└── .env                        # Local secrets (do not commit)
```

---

## Development commands

```bash
# Dev server
uvicorn src.main:app --reload

# Lint / format
ruff check .
ruff check --fix .
ruff format .

# Tests
pytest

# Scaffold a new feature module
python scripts/create_app.py <module_name>

# Alembic (once models and env are wired to a real DATABASE_URL)
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
alembic current
```
